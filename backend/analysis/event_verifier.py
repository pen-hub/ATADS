from __future__ import annotations

from collections import deque
from typing import Any


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return intersection / area if area else 0.0


class EventVerifier:
    """Temporal evidence organizer. It never makes a final accident decision."""

    def __init__(self, rules: dict[str, Any]):
        self.rules = rules
        self.history: deque[dict[str, Any]] = deque(maxlen=240)
        self.last_sample_at: float | None = None
        self.started_at: float | None = None
        self.transitions: list[dict[str, Any]] = []

    def add(self, timestamp: float, predictions: list[dict[str, Any]], *, occluded: bool = False,
            vehicle_tracks: list[dict[str, Any]] | None = None,
            trajectory_change: dict[str, Any] | None = None,
            frame_index: int | None = None) -> dict[str, Any]:
        vehicle_tracks = vehicle_tracks or []
        interval = float(self.rules.get("verifier_sample_interval_seconds", 0.5))
        sampled = self.last_sample_at is None or timestamp - self.last_sample_at >= interval
        accident = [p for p in predictions if p.get("class_name", "").casefold() == "accident"]
        confidence = max((float(p.get("confidence", 0)) for p in accident), default=0.0)
        associated_tracks: set[int] = set()
        for box in accident:
            for track in vehicle_tracks:
                track_id = track.get("track_id")
                if track_id is not None and _overlap_ratio(box["bbox"], track["bbox"]) >= 0.01:
                    associated_tracks.add(int(track_id))
        positive = bool(sampled and confidence >= float(self.rules["verifier_min_confidence"])
                        and (not vehicle_tracks or associated_tracks))
        if sampled:
            if self.started_at is None:
                self.started_at = timestamp
            self.last_sample_at = timestamp
            self.history.append({"timestamp": timestamp, "frame_index": frame_index if frame_index is not None else
                                 (int(trajectory_change.get("frame_index", 0)) if trajectory_change else None),
                                 "confidence": confidence, "positive": positive, "boxes": accident,
                                 "occluded": bool(occluded), "related_track_ids": sorted(associated_tracks),
                                 "trajectory_change": trajectory_change})
        window_seconds = float(self.rules["verifier_window_seconds"])
        window = [entry for entry in self.history if 0 <= timestamp - entry["timestamp"] <= window_seconds]
        positives = [entry for entry in window if entry["positive"]]
        positive_count = len(positives)
        max_confidence = max((entry["confidence"] for entry in window), default=0.0)
        elapsed = max(0.0, timestamp - self.started_at) if self.started_at is not None else 0.0
        observation_quality = "poor" if occluded or not vehicle_tracks else "partial" if any(e["occluded"] for e in window) else "good"
        expected_ids = set(int(value) for value in (self.rules.get("event_track_ids") or []))
        observed_ids = {int(value) for track in vehicle_tracks if track.get("track_id") is not None
                        for value in [track["track_id"]]}
        if expected_ids and not expected_ids.issubset(observed_ids):
            observation_quality = "poor"
        timeout_seconds = float(self.rules.get("accident_verification_timeout_seconds",
                                                self.rules.get("uncertain_after_seconds", window_seconds)))
        if elapsed >= timeout_seconds:
            status = "UNCERTAIN"
            reason = ("vùng nghi vấn bị che khuất hoặc mất track; cần người duyệt" if observation_quality != "good"
                      else "hết thời gian quan sát tự động; cần người duyệt kết luận")
        else:
            status = "SUSPECTED"
            review_ready = positive_count >= int(self.rules.get("verifier_min_positive_frames", 2))
            if review_ready and observation_quality == "good":
                status = "READY_FOR_REVIEW"
                reason = "đủ mẫu hỗ trợ; chuyển người duyệt, hệ thống không tự xác nhận"
            elif positive_count:
                reason = "model accident có tín hiệu; bằng chứng chỉ hỗ trợ người duyệt"
            elif trajectory_change:
                reason = "có thay đổi quỹ đạo ảnh; chưa đủ căn cứ kết luận tai nạn"
            else:
                reason = "đang thu thập bằng chứng; chưa đủ căn cứ kết luận tai nạn"
        related_ids = sorted({track_id for entry in window for track_id in entry["related_track_ids"]})
        if not self.transitions or self.transitions[-1]["status"] != status:
            self.transitions.append({"status": status, "timestamp": timestamp, "reason": reason})
        return {"status": status, "reason": reason, "max_confidence": max_confidence,
                "positive_observations": positive_count, "positive_frames": positive_count,
                "window_frames": len(window), "sampled": sampled, "temporal_consistency": round(positive_count / len(window), 3) if window else 0.0,
                "review_ready": positive_count >= int(self.rules.get("verifier_min_positive_frames", 2)),
                "observation_quality": observation_quality, "related_track_ids": related_ids,
                "timeline": list(window[-20:]), "detections": [p for e in window for p in e["boxes"]]}
