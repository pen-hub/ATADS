from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_lock = RLock()
DEFAULT_SETTINGS = {
    "vehicle_model": str(ROOT / "runs" / "detect" / "phuong_tien" / "huan_luyen" / "weights" / "best.pt"),
    "accident_model": str(ROOT / "runs" / "detect" / "yolo_v11_small_accident" / "huan_luyen" / "weights" / "best.pt"),
    "device": "0", "vehicle_confidence": 0.5, "accident_confidence": 0.45,
    "vehicle_imgsz": 640, "accident_imgsz": 640, "verification_interval_frames": 5,
    "verification_interval_seconds": 0.5, "verification_queue_size": 3, "data_dir": "data", "port": 8765,
    "trajectory_history_seconds": 6.0, "trajectory_max_gap_seconds": 0.75,
    "trajectory_max_points": 96, "trajectory_min_direction_pixels": 8,
}
DEFAULT_RULES = {
    "suspicion_iou_threshold": 0.08, "suspicion_distance_ratio": 0.16,
    "suspicion_consecutive_frames": 3, "verifier_window_seconds": 3,
    "verifier_min_positive_frames": 2, "verifier_min_confidence": 0.55,
    "uncertain_after_seconds": 3.0, "accident_verification_timeout_seconds": 3.0,
    "evidence_pre_seconds": 5, "evidence_post_seconds": 5,
    "max_events_per_source": 1000, "upload_max_mb": 1024,
    "verifier_sample_interval_seconds": 0.5, "trajectory_min_displacement_ratio": 0.025,
    "trajectory_turn_threshold_degrees": 75,
    "candidate_observation_seconds": 0.6, "candidate_min_observations": 3,
    "candidate_max_age_seconds": 2.0, "candidate_max_track_gap_seconds": 0.75,
    "diagnostics_enabled": False,
}


class ConfigurationError(ValueError):
    pass


class Settings:
    def __init__(self) -> None:
        self.settings_path = ROOT / "config" / "settings.json"
        self.rules_path = ROOT / "config" / "rules.json"
        self.roi_path = ROOT / "config" / "roi.json"
        self._settings = {**DEFAULT_SETTINGS, **self._read(self.settings_path)}
        self._rules = {**DEFAULT_RULES, **self._read(self.rules_path)}
        self._rois = self._read(self.roi_path) if self.roi_path.exists() else {}
        self._settings["device"] = os.getenv("ATADS_DEVICE", self._settings["device"])
        self._settings["port"] = int(os.getenv("ATADS_PORT", self._settings["port"]))
        self.validate(self._settings, self._rules)

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Không thể đọc cấu hình {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigurationError(f"Cấu hình phải là JSON object: {path}")
        return value

    @property
    def values(self) -> dict[str, Any]:
        with _lock:
            return dict(self._settings)

    @property
    def rules(self) -> dict[str, Any]:
        with _lock:
            return dict(self._rules)

    def get_roi(self, source_id: str) -> dict[str, Any]:
        with _lock:
            return dict(self._rois.get(source_id, {"enabled": False, "points": []}))

    def set_roi(self, source_id: str, value: dict[str, Any]) -> dict[str, Any]:
        if len(source_id) != 64 or any(ch not in "0123456789abcdef" for ch in source_id.casefold()):
            raise ConfigurationError("source_id không hợp lệ")
        points = value.get("points")
        enabled = value.get("enabled", False)
        if not isinstance(points, list) or len(points) > 32 or 0 < len(points) < 3:
            raise ConfigurationError("ROI cần 3–32 điểm hoặc danh sách rỗng")
        normalized = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ConfigurationError("Mỗi điểm ROI phải có tọa độ x, y")
            x, y = float(point[0]), float(point[1])
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise ConfigurationError("Tọa độ ROI phải chuẩn hóa trong [0, 1]")
            normalized.append([round(x, 6), round(y, 6)])
        if len(normalized) >= 3:
            area = abs(sum(normalized[i][0] * normalized[(i + 1) % len(normalized)][1] -
                           normalized[(i + 1) % len(normalized)][0] * normalized[i][1]
                           for i in range(len(normalized))))
            if area < 1e-6:
                raise ConfigurationError("Polygon ROI phải bao quanh một vùng có diện tích")
        if not isinstance(enabled, bool) or enabled and len(normalized) < 3:
            raise ConfigurationError("Chỉ bật ROI sau khi lưu ít nhất 3 điểm")
        from backend.core.roi import validate_polygon
        if normalized:
            validate_polygon(normalized)
        anchor = value.get("anchor", "bottom_center")
        if anchor not in ("center", "bottom_center"):
            raise ConfigurationError("Điểm xét ROI không hợp lệ")
        entry = {"enabled": enabled, "points": normalized, "anchor": anchor}
        with _lock:
            updated = {**self._rois, source_id: entry}
            self._atomic_json(self.roi_path, updated)
            self._rois = updated
        return entry

    @staticmethod
    def validate(settings: dict[str, Any], rules: dict[str, Any]) -> None:
        for name in ("vehicle_model", "accident_model", "data_dir", "device"):
            if not isinstance(settings.get(name), str) or not settings[name].strip():
                raise ConfigurationError(f"Thiếu cấu hình {name}")
        for name in ("vehicle_confidence", "accident_confidence"):
            if not 0 < float(settings[name]) <= 1:
                raise ConfigurationError(f"{name} phải thuộc (0, 1]")
        if "diagnostics_enabled" in settings and not isinstance(settings["diagnostics_enabled"], bool):
            raise ConfigurationError("diagnostics_enabled phải là boolean")
        if "diagnostics_enabled" in rules and not isinstance(rules["diagnostics_enabled"], bool):
            raise ConfigurationError("diagnostics_enabled phải là boolean")
        for name in ("vehicle_imgsz", "accident_imgsz", "verification_interval_frames", "verification_queue_size"):
            if int(settings[name]) <= 0:
                raise ConfigurationError(f"{name} phải là số nguyên dương")
        if "verification_interval_seconds" in settings and not 0.1 <= float(settings["verification_interval_seconds"]) <= 10:
            raise ConfigurationError("verification_interval_seconds phải thuộc [0.1, 10]")
        if "trajectory_history_seconds" in settings and not 1 <= float(settings["trajectory_history_seconds"]) <= 30:
            raise ConfigurationError("trajectory_history_seconds phải thuộc [1, 30]")
        if "trajectory_max_gap_seconds" in settings and not 0.1 <= float(settings["trajectory_max_gap_seconds"]) <= 5:
            raise ConfigurationError("trajectory_max_gap_seconds phải thuộc [0.1, 5]")
        if "trajectory_max_points" in settings and not 2 <= int(settings["trajectory_max_points"]) <= 1000:
            raise ConfigurationError("trajectory_max_points phải thuộc [2, 1000]")
        if "trajectory_min_direction_pixels" in settings and not 0 <= float(settings["trajectory_min_direction_pixels"]) <= 500:
            raise ConfigurationError("trajectory_min_direction_pixels phải thuộc [0, 500]")
        for name in ("trajectory_enabled", "show_track_ids", "show_direction"):
            if name in settings and not isinstance(settings[name], bool):
                raise ConfigurationError(f"{name} phải là boolean")
        for name in ("suspicion_iou_threshold", "suspicion_distance_ratio", "verifier_min_confidence"):
            if not 0 <= float(rules[name]) <= 1:
                raise ConfigurationError(f"{name} phải thuộc [0, 1]")
        for name in ("suspicion_consecutive_frames", "verifier_min_positive_frames", "evidence_pre_seconds", "evidence_post_seconds", "upload_max_mb"):
            if int(rules[name]) <= 0:
                raise ConfigurationError(f"{name} phải là số nguyên dương")
        if "verifier_sample_interval_seconds" in rules and not 0.1 <= float(rules["verifier_sample_interval_seconds"]) <= 5:
            raise ConfigurationError("verifier_sample_interval_seconds phải thuộc [0.1, 5]")
        for name in ("verifier_window_seconds", "accident_verification_timeout_seconds", "uncertain_after_seconds"):
            if name in rules and not 0.5 <= float(rules[name]) <= 30:
                raise ConfigurationError(f"{name} phải thuộc [0.5, 30]")
        for name in ("candidate_observation_seconds", "candidate_max_age_seconds", "candidate_max_track_gap_seconds"):
            if name in rules and not 0.1 <= float(rules[name]) <= 10:
                raise ConfigurationError(f"{name} phải thuộc [0.1, 10]")
        if "candidate_min_observations" in rules and not 2 <= int(rules["candidate_min_observations"]) <= 100:
            raise ConfigurationError("candidate_min_observations phải thuộc [2, 100]")
        if "trajectory_min_displacement_ratio" in rules and not 0 <= float(rules["trajectory_min_displacement_ratio"]) <= 1:
            raise ConfigurationError("trajectory_min_displacement_ratio phải thuộc [0, 1]")
        if "trajectory_turn_threshold_degrees" in rules and not 1 <= float(rules["trajectory_turn_threshold_degrees"]) <= 179:
            raise ConfigurationError("trajectory_turn_threshold_degrees phải thuộc [1, 179]")
        if not 1 <= int(settings["port"]) <= 65535:
            raise ConfigurationError("port không hợp lệ")

    def update(self, settings_patch: dict[str, Any], rules_patch: dict[str, Any] | None = None) -> dict[str, Any]:
        allowed = set(self._settings)
        if set(settings_patch) - allowed:
            raise ConfigurationError(f"Trường cấu hình không được hỗ trợ: {sorted(set(settings_patch) - allowed)}")
        settings = {**self._settings, **settings_patch}
        rules = {**self._rules, **(rules_patch or {})}
        if rules_patch and set(rules_patch) - set(self._rules):
            raise ConfigurationError(f"Luật phát hiện không được hỗ trợ: {sorted(set(rules_patch) - set(self._rules))}")
        self.validate(settings, rules)
        with _lock:
            self._atomic_json(self.settings_path, settings)
            if rules_patch:
                self._atomic_json(self.rules_path, rules)
            self._settings, self._rules = settings, rules
        return {"settings": dict(settings), "rules": dict(rules)}

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
