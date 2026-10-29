from __future__ import annotations

import logging
import math
import queue
import secrets
import threading
import time
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.analysis.event_verifier import EventVerifier
from backend.core.roi import contains, mask_full
from backend.analysis.suspicion import SuspicionAnalyzer
from backend.detection.models import ModelManager
from backend.evidence.buffer import EvidenceBuffer
from backend.storage.local_storage import LocalStorageService
from backend.tracking.trajectory import TrajectoryTracker

log = logging.getLogger("atads.pipeline")


class BoundedWorker:
    def __init__(self, maximum: int):
        self.tasks: queue.Queue = queue.Queue(maxsize=maximum)
        self.dropped = 0
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()

    def start(self, callback) -> None:
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, args=(callback,), daemon=True, name="atads-accident-inference")
        self.thread.start()

    def submit(self, item: Any) -> tuple[bool, Any | None]:
        try:
            self.tasks.put_nowait(item)
            return True, None
        except queue.Full:
            with self.lock:
                self.dropped += 1
            try:
                dropped = self.tasks.get_nowait()  # discard oldest delayed frame; retain current observation
                self.tasks.task_done()
                log.warning("Queue xác minh đầy; bỏ mẫu frame=%s cho event=%s", dropped[3], dropped[1])
            except queue.Empty:
                dropped = None
            try:
                self.tasks.put_nowait(item)
                return True, dropped
            except queue.Full:
                return False, dropped

    def _run(self, callback) -> None:
        while not self.stop_event.is_set() or not self.tasks.empty():
            try:
                item = self.tasks.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                callback(item)
            except Exception:
                log.exception("Lỗi tác vụ xác minh accident")
            finally:
                self.tasks.task_done()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)


class Pipeline:
    def __init__(self, models: ModelManager, storage: LocalStorageService, settings, rules):
        self.models, self.storage, self.settings, self.rules = models, storage, settings, rules
        self._lock = threading.RLock()
        self._update_sequence = 0
        self._generation = 0
        values = settings.values
        self._visualization = {"trajectory_enabled": bool(values.get("trajectory_enabled", True)),
                               "show_track_ids": bool(values.get("show_track_ids", True)),
                               "show_direction": bool(values.get("show_direction", True)),
                               "history_seconds": float(values.get("trajectory_history_seconds", 6.0)),
                               "selected_track_id": None}
        self._worker = BoundedWorker(int(settings.values["verification_queue_size"]))
        self._worker.start(self._run_verification)
        self.reset()

    def reset(self) -> None:
        self._generation += 1
        self._suspect = SuspicionAnalyzer(self.rules)
        self._verifier = EventVerifier(self.rules)
        values = self.settings.values
        self._trajectory = TrajectoryTracker(history_seconds=self._visualization["history_seconds"],
                    max_gap_seconds=float(values.get("trajectory_max_gap_seconds", 0.75)),
                    max_points=int(values.get("trajectory_max_points", 96)),
                    min_direction_distance=float(values.get("trajectory_min_direction_pixels", 8)))
        self._event_verifiers: dict[str, EventVerifier] = {}
        self._verification_pending: set[str] = set()
        self._evidence = EvidenceBuffer(int(self.rules["evidence_pre_seconds"]), int(self.rules["evidence_post_seconds"]))
        self._history: deque[dict[str, Any]] = deque(maxlen=240)
        self._frame_index = 0
        self._frequency_bins: dict[int, set[int]] = {}
        self._active_event: dict[str, Any] | None = None
        self._active_events: dict[str, dict[str, Any]] = {}
        self._active_event_keys: dict[tuple[int, ...], str] = {}
        self._event_keys: dict[str, tuple[int, ...]] = {}
        self._event_cooldowns: dict[tuple[int, ...], float] = {}
        self._last_event_verify_timestamp: dict[str, float] = {}
        self._last_input_timestamp: float | None = None
        self._pair_candidates: dict[tuple[int, int], dict[str, Any]] = {}
        self._diagnostics_enabled = bool(self.rules.get("diagnostics_enabled", False))
        self._last_suspect_tracks: list[int] = []
        self._read_fps = 0.0
        self._frame_times: deque[float] = deque(maxlen=30)
        self._last_error: str | None = None
        self._started = time.time()
        self._jpeg_frame: bytes | None = None
        self._jpeg_sequence = 0
        self._source_upload_id: str | None = None
        self._reader_thread: threading.Thread | None = None
        self._roi = {"enabled": False, "points": []}
        self._speed = 1.0
        self._runtime = {"source": None, "source_type": None, "state": "STOPPED", "width": 0, "height": 0,
                         "source_fps": 0.0, "output_fps": 0.0, "output_latency_ms": 0.0,
                         "tracked_vehicles": [], "last_suspicion": None, "last_verification": None, "accident_detections": [], "frequency_bins": [],
                         "frame_index": 0, "processed": 0, "dropped_frames": 0, "queue_size": 0}
        self._diagnostics_enabled = bool(self.rules.get("diagnostics_enabled", False))
        self._worker.stop_event.clear()
        if self._worker.thread is None or not self._worker.thread.is_alive():
            self._worker.start(self._run_verification)

    def _emit(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._update_sequence += 1
            self._history.append({**payload, "sequence": self._update_sequence})

    def poll(self, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [item for item in self._history if item["sequence"] > after]

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {**self._runtime, "uptime_seconds": round(time.time() - self._started, 1),
                    "queue_size": self._worker.tasks.qsize(), "dropped_frames": self._worker.dropped,
                    "vehicle_inference_ms": round(self.models.vehicle_inference_ms, 2),
                    "accident_inference_ms": round(self.models.accident_inference_ms, 2),
                    "last_error": self._last_error, "visualization": dict(self._visualization)}

    def start(self, source: str, source_type: str = "video", roi: dict[str, Any] | None = None) -> None:
        if source_type == "video":
            uploads = (self.storage.root / "uploads").resolve()
            upload_id = Path(source).name
            path = (uploads / upload_id).resolve()
            if (path.parent != uploads or not upload_id.startswith("UP-") or
                    path.suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv", ".m4v"} or not path.is_file()):
                raise ValueError("Video không hợp lệ hoặc không nằm trong thư mục uploads")
            reader_args = (path, "video", path.name[3:])
            display_source = path.name[3:]
            self._source_upload_id = path.stem
        elif source_type == "camera":
            source = str(source).strip()
            if source.isdecimal():
                if int(source) > 16:
                    raise ValueError("Chỉ số webcam phải nằm trong khoảng 0–16")
                display_source = f"Webcam {int(source)}"
            elif source.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
                display_source = "Camera IP"
            else:
                raise ValueError("Nguồn camera phải là chỉ số webcam (0–16) hoặc URL RTSP/HTTP(S)")
            reader_args = (source, "camera", display_source)
            self._source_upload_id = None
        else:
            raise ValueError("Loại nguồn không hợp lệ")
        previous_reader = self._reader_thread
        if previous_reader and previous_reader.is_alive() and previous_reader is not threading.current_thread():
            previous_reader.join(timeout=5)
            if previous_reader.is_alive():
                raise RuntimeError("Luồng video cũ chưa giải phóng xong")
        with self._lock:
            if self._runtime["state"] in {"RUNNING", "PAUSED"}:
                raise RuntimeError("Pipeline đang chạy")
            self.models.reset_tracking()
            self.reset()
            self._frequency_bins.clear()
            self._runtime.update({"source": display_source, "source_type": source_type, "state": "RUNNING", "frequency_bins": [],
                                  "source_fps": 0.0, "frame_index": 0, "processed": 0,
                                  "last_error": None, "accident_detections": [], "last_verification": None, "last_suspicion": None})
            self._roi = roi or {"enabled": False, "points": []}
        target = self._read_video if source_type == "video" else self._read_camera
        thread = threading.Thread(target=target, args=reader_args, daemon=True, name="atads-video-reader")
        self._reader_thread = thread
        thread.start()

    def _read_video(self, path: Path, source_type: str = "video", display_source: str | None = None) -> None:
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            self._fail(f"Không giải mã được video: {path.name}")
            return
        self._capture_loop(capture, source_type, display_source or path.name[3:])

    def _read_camera(self, source: str, source_type: str, display_source: str) -> None:
        if source.isdecimal():
            camera_index = int(source)
            capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(camera_index)
        else:
            try:
                capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                                                                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000])
            except (TypeError, cv2.error):
                capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG) if hasattr(cv2, "CAP_FFMPEG") else cv2.VideoCapture(source)
        if not capture.isOpened():
            capture.release()
            self._fail(f"Không mở được {display_source}. Kiểm tra kết nối, URL/đăng nhập camera và quyền truy cập camera.")
            return
        # Keep only the newest frames where the capture backend supports low-latency buffering.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._capture_loop(capture, source_type, display_source)

    def _capture_loop(self, capture, source_type: str, display_source: str) -> None:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        self._speed = 1.0
        with self._lock:
            self._runtime.update({"source_fps": fps if source_type == "video" else max(0.0, fps), "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                  "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))})
        frames_read = 0
        live_started = time.monotonic()
        try:
            while True:
                with self._lock:
                    if self._runtime["state"] == "STOPPED":
                        break
                    paused = self._runtime["state"] == "PAUSED"
                if paused:
                    time.sleep(0.05)
                    continue
                ok, frame = capture.read()
                if not ok:
                    if source_type == "camera" and self._runtime["state"] != "STOPPED":
                        self._fail(f"Mất kết nối {display_source}; kiểm tra nguồn và kết nối camera rồi thử lại.")
                    break
                if source_type == "video":
                    position_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0)
                    timestamp = position_ms / 1000 if position_ms > 0 else frames_read / fps if fps > 0 else float(frames_read)
                    if self._last_input_timestamp is not None and timestamp <= self._last_input_timestamp:
                        timestamp = self._last_input_timestamp + (1 / fps if fps > 0 else 0.001)
                else:
                    timestamp = time.monotonic() - live_started
                self._last_input_timestamp = timestamp
                frames_read += 1
                self._process(frame, timestamp)
        except Exception as exc:
            self._fail(f"Lỗi pipeline: {exc}")
        finally:
            capture.release()
            for event_id, clip_path, clip_error in self._evidence.finish_pending():
                event = self.storage.get_event(event_id)
                if event:
                    event["evidence"]["video"] = clip_path.relative_to(self.storage.root).as_posix() if clip_path else None
                    event.setdefault("evidence_issues", []).append(clip_error or "post_event_window_incomplete")
                    self.storage.save_event(event)
            with self._lock:
                if self._runtime["state"] != "STOPPED":
                    self._runtime["state"] = "STOPPED"
            self._emit({"type": "state", "state": self._runtime["state"], "message": f"Đã kết thúc nguồn {display_source}"})

    def _process(self, frame: np.ndarray, timestamp: float) -> None:
        started = time.perf_counter()
        self._frame_times.append(started)
        self._frame_index += 1
        if len(self._frame_times) >= 2:
            elapsed = self._frame_times[-1] - self._frame_times[0]
            if elapsed > 0:
                self._read_fps = (len(self._frame_times) - 1) / elapsed
        values = self.settings.values
        all_detections = self.models.vehicle_track(frame, conf=float(values["vehicle_confidence"]), imgsz=int(values["vehicle_imgsz"]), **({"roi": self._roi} if self._roi.get("enabled") else {}))
        height, width = frame.shape[:2]
        detections = self._filter_roi(all_detections, width, height)
        trajectories = self._trajectory.update(detections, frame_index=self._frame_index, timestamp=timestamp)
        frequency_bin = max(0, int(timestamp // 10))
        self._frequency_bins.setdefault(frequency_bin, set()).update(int(d["track_id"]) for d in detections if d.get("track_id") is not None)
        if self._frame_index % max(1, int(self._read_fps or 10)) == 0:
            with self._lock:
                self._runtime["frequency_bins"] = [{"start_seconds": start, "vehicle_count": len(track_ids)} for start, track_ids in sorted(self._frequency_bins.items())]
        suspicion = self._suspect.analyze(detections, width, height, self._frame_index, timestamp)
        self._latest_suspicion = suspicion
        eligible_suspicion = self._advance_pair_candidates(detections, trajectories, width, height, timestamp,
                                                             self._frame_index)
        self._event_cooldowns = {key: deadline for key, deadline in self._event_cooldowns.items()
                                 if deadline >= timestamp}
        for active_event in self._active_events.values():
            active_event["last_seen_timestamp"] = timestamp
        for event_id, clip_path, clip_error in self._evidence.add(timestamp, frame):
            event = self.storage.get_event(event_id)
            if event:
                event["evidence"]["video"] = (clip_path.relative_to(self.storage.root).as_posix()
                                               if clip_path else None)
                if clip_error:
                    event.setdefault("evidence_issues", []).append(clip_error)
                self.storage.save_event(event)
        if eligible_suspicion:
            suspicion = eligible_suspicion
            self._last_suspect_tracks = suspicion["track_ids"]
            with self._lock:
                self._runtime["last_suspicion"] = suspicion
            for trigger in suspicion.get("concurrent", [suspicion]):
                related_ids = sorted({int(value) for value in trigger["track_ids"]})
                event_key = tuple(related_ids)
                if timestamp < self._event_cooldowns.get(event_key, -1):
                    continue
                if event_key in self._active_event_keys:
                    continue
                event_trajectory = {str(track_id): trajectories.get(track_id, [])[-16:] for track_id in related_ids}
                event = self.storage.create_event(source=self._runtime["source"], source_upload_id=self._source_upload_id,
                                                  status="SUSPECTED", started_at=datetime.now(timezone.utc).isoformat(),
                                                  related_track_ids=related_ids, reasons=trigger["reasons"],
                                                  suspicion_score=trigger["score"], frame_index=self._frame_index,
                                                  source_timestamp=timestamp, start_timestamp=timestamp, source_time_origin="video_seconds" if self._runtime.get("source_type") == "video" else "camera_monotonic_seconds",
                                                  last_seen_timestamp=timestamp, quality="AUTO_RULE_CANDIDATE",
                                                  evidence_summary={"vehicle_tracks": len(detections), "signals": trigger.get("signals", {})},
                                                  decision_reason="Dấu hiệu cần người duyệt; hệ thống không tự xác nhận tai nạn.",
                                                  accident_detections=[], observation_quality="partial",
                                                  manual_review_status=None, trajectory=event_trajectory,
                                                  status_history=[{"status": "SUSPECTED", "timestamp": timestamp,
                                                                   "reason": "; ".join(trigger["reasons"])}],
                                                  verification_samples=[], evidence_issues=[])
                event["evidence"]["image"] = self.storage.save_image(event["event_id"], frame)
                self.storage.save_event(event)
                event_id = event["event_id"]
                self._active_events[event_id] = event
                self._active_event_keys[event_key] = event_id
                self._event_keys[event_id] = event_key
                verifier_rules = {**self.rules, "candidate_history": trigger.get("signals", {}).get("candidate_history", [])}
                self._event_verifiers[event_id] = EventVerifier(verifier_rules)
                self._last_event_verify_timestamp[event_id] = -10**9
                self._evidence.trigger(event_id, timestamp, self.storage.videos_dir / f"{event_id}.mp4")
                self._emit({"type": "event", "event": event})
            self._active_event = next(iter(self._active_events.values()), None)
        verify_interval = float(values.get("verification_interval_seconds", 0.5))
        due_event_ids = [event_id for event_id in self._active_events
                         if event_id not in self._verification_pending and
                         timestamp - self._last_event_verify_timestamp.get(event_id, -10**9) >= verify_interval]
        if due_event_ids:
            self._verification_pending.update(due_event_ids)
            context = {event_id: {"related_track_ids": self._active_events[event_id].get("related_track_ids", []),
                                  "trajectory": {str(track_id): trajectories.get(track_id, [])[-96:]
                                                 for track_id in self._active_events[event_id].get("related_track_ids", [])},
                                  "suspicion": (suspicion if suspicion and set(suspicion.get("track_ids", [])) ==
                                                set(self._active_events[event_id].get("related_track_ids", [])) else None)}
                       for event_id in due_event_ids}
            accepted, dropped = self._worker.submit((self._generation, due_event_ids, timestamp, self._frame_index,
                                                     frame.copy(), detections, context))
            if dropped:
                self._record_dropped_sample(dropped, "queue_full_oldest")
                self._verification_pending.difference_update(dropped[1])
            if accepted:
                for event_id in due_event_ids:
                    self._last_event_verify_timestamp[event_id] = timestamp
            else:
                for event_id in due_event_ids:
                    self._record_sample_issue(event_id, timestamp, self._frame_index, "queue_full_rejected")
                self._verification_pending.difference_update(due_event_ids)
        output = frame.copy()
        with self._lock:
            accident_boxes = [dict(d) for d in self._runtime.get("accident_detections", [])]
        self._draw(output, detections, self._roi, trajectories, self._visualization, self._trajectory)
        jpeg_ok, jpeg_encoded = cv2.imencode(".jpg", output, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if jpeg_ok:
            with self._lock:
                self._current_frame = output
                self._jpeg_frame = jpeg_encoded.tobytes()
                self._jpeg_sequence = self._frame_index
        latency = (time.perf_counter() - started) * 1000
        processing_fps = self._read_fps or round(1 / max(time.perf_counter() - started, 1e-9), 2)
        with self._lock:
            self._runtime.update({"tracked_vehicles": detections, "accident_detections": self._runtime.get("accident_detections", []), "frame_index": self._frame_index,
                                  "output_fps": processing_fps,
                                  "output_latency_ms": round(latency, 2), "processed": self._runtime["processed"] + 1,
                                  "queue_size": self._worker.tasks.qsize()})
        if self._diagnostics_enabled:
            updated_tracks = sum(d.get("track_id") is not None for d in detections)
            history_observed = sum(bool(history and history[-1].get("observed_status") == "observed")
                                   for history in self._trajectory.snapshot().values())
            log.info("frame=%d detections=%d observed_tracks=%d predicted_tracks=0 lost_tracks=%d vehicle_conf=%.3f inference_ms=%.1f processing_fps=%.2f",
                     self._frame_index, len(all_detections), updated_tracks, max(0, history_observed - updated_tracks),
                     float(values["vehicle_confidence"]),
                     self.models.vehicle_inference_ms, self._read_fps)
        self._emit({"type": "metrics", "sequence": self._frame_index, "frame_index": self._frame_index,
                    "timestamp": timestamp, "source_fps": fps_value(self._runtime.get("source_fps")),
                    "processing_fps": round(self._read_fps, 2), "output_latency_ms": round(latency, 2),
                    "vehicles": detections, "frequency_bins": self._runtime.get("frequency_bins", []), "suspicion": suspicion, "dropped_verifications": self._worker.dropped})

    def _advance_pair_candidates(self, detections: list[dict[str, Any]], trajectories: dict[int, list[dict[str, Any]]],
                                 width: int, height: int, timestamp: float, frame_index: int) -> dict[str, Any] | None:
        """Require repeated observed pair evidence over time before opening an event or invoking accident YOLO."""
        from backend.analysis.suspicion import _iou

        cfg = self.rules
        minimum_iou = float(cfg["suspicion_iou_threshold"])
        max_distance = float(cfg["suspicion_distance_ratio"])
        max_gap = float(cfg.get("candidate_max_track_gap_seconds", 0.75))
        min_observations = int(cfg.get("candidate_min_observations", 3))
        min_duration = float(cfg.get("candidate_observation_seconds", 0.6))
        max_age = float(cfg.get("candidate_max_age_seconds", 2.0))
        observed = {int(d["track_id"]): d for d in detections if d.get("track_id") is not None}
        pair_seen: set[tuple[int, int]] = set()
        triggered: list[dict[str, Any]] = []
        for index, (first_id, first) in enumerate(observed.items()):
            for second_id, second in list(observed.items())[index + 1:]:
                if first_id == second_id:
                    continue
                key = tuple(sorted((first_id, second_id)))
                a, b = first["bbox"], second["bbox"]
                distance = math.hypot(((a[0] + a[2]) - (b[0] + b[2])) / 2 / max(width, 1),
                                      ((a[1] + a[3]) - (b[1] + b[3])) / 2 / max(height, 1))
                overlap = _iou(a, b)
                if overlap < minimum_iou and distance > max_distance:
                    continue
                pair_seen.add(key)
                candidate = self._pair_candidates.setdefault(key, {"first_timestamp": timestamp,
                    "last_timestamp": timestamp, "first_frame": frame_index, "observations": 0,
                    "max_iou": 0.0, "min_distance": distance, "history": [], "last_trigger": None,
                    "motion_signal": None})
                if timestamp - candidate["last_timestamp"] > max_gap:
                    log.info("Collision candidate expired after track gap pair=%s gap=%.3fs", key,
                             timestamp - candidate["last_timestamp"])
                    candidate.update({"first_timestamp": timestamp, "first_frame": frame_index,
                                      "observations": 0, "history": [], "last_trigger": None})
                candidate["last_timestamp"] = timestamp
                candidate["observations"] += 1
                candidate["max_iou"] = max(candidate["max_iou"], overlap)
                candidate["min_distance"] = min(candidate["min_distance"], distance)
                candidate["history"].append({"timestamp": timestamp, "frame_index": frame_index,
                    "iou": round(overlap, 4), "distance_ratio": round(distance, 4),
                    "track_ids": list(key), "observation": "OBSERVED",
                    "confidence": [first.get("confidence"), second.get("confidence")]})
                candidate["history"] = candidate["history"][-20:]
                current_motion = self._suspect_signal_for_pair(key)
                if current_motion:
                    candidate["motion_signal"] = current_motion
                closing = len(candidate["history"]) >= 2 and candidate["history"][-1]["distance_ratio"] < candidate["history"][-2]["distance_ratio"] - 0.001
                histories = [trajectories.get(track_id, []) for track_id in key]
                sufficiently_observed = all(sum(p.get("observed_status") == "observed" for p in h) >= min_observations
                                            for h in histories)
                latest = [max((p["timestamp"] for p in h if p.get("observed_status") == "observed"), default=-1)
                          for h in histories]
                fresh = all(0 <= timestamp - seen_at <= max_gap for seen_at in latest)
                elapsed = timestamp - candidate["first_timestamp"]
                suspicion_signal = candidate.get("motion_signal")
                has_motion_signal = bool(suspicion_signal) or closing
                ready = (sufficiently_observed and fresh and candidate["observations"] >= min_observations
                         and elapsed >= min_duration and (has_motion_signal or candidate["max_iou"] >= minimum_iou * 2))
                if ready and candidate["last_trigger"] is None:
                    candidate["last_trigger"] = timestamp
                    log.info("Accident model activation gate passed pair=%s observations=%d elapsed=%.3fs max_iou=%.3f min_distance=%.3f",
                                key, candidate["observations"], elapsed, candidate["max_iou"], candidate["min_distance"])
                    triggered.append({"frame_index": frame_index, "timestamp": timestamp, "track_ids": list(key),
                        "reasons": ["tương tác cặp xe được quan sát ổn định qua thời gian; chuyển sang xác minh accident"],
                        "score": round(max(candidate["max_iou"], 1 - candidate["min_distance"]), 3),
                        "signals": {"iou": round(overlap, 4), "distance_ratio": round(distance, 4),
                                    "observed_pair_frames": candidate["observations"], "observed_duration_seconds": round(elapsed, 3),
                                    "candidate_history": candidate["history"], "tracking_quality": "good",
                                    "motion_signal": suspicion_signal, "relative_motion": "closing" if closing else "stable"}})
                elif self._diagnostics_enabled and candidate["observations"] == 1:
                    log.info("Collision candidate created pair=%s iou=%.3f distance=%.3f; waiting for temporal evidence",
                             key, overlap, distance)
        for key, candidate in list(self._pair_candidates.items()):
            if timestamp - candidate["last_timestamp"] > max_age:
                self._pair_candidates.pop(key, None)
                if self._diagnostics_enabled:
                    log.info("Collision candidate expired pair=%s age=%.3fs", key,
                             timestamp - candidate["last_timestamp"])
        if not triggered:
            for key in list(self._pair_candidates):
                if key not in pair_seen and timestamp - self._pair_candidates[key]["last_timestamp"] > max_gap:
                    if self._diagnostics_enabled:
                        log.info("Collision candidate track pair lost pair=%s", key)
            return None
        return {**max(triggered, key=lambda item: item["score"]), "concurrent": triggered}

    def _suspect_signal_for_pair(self, key: tuple[int, int]) -> dict[str, Any] | None:
        latest = getattr(self, "_latest_suspicion", None)
        if not latest:
            return None
        for item in latest.get("concurrent", [latest]):
            if tuple(sorted(item.get("track_ids", []))) == key:
                return item.get("signals", {})
        return None

    @staticmethod
    def _draw(frame: np.ndarray, detections: list[dict[str, Any]], roi: dict[str, Any] | None = None,
              trajectories: dict[int, list[dict[str, Any]]] | None = None,
              visualization: dict[str, Any] | None = None,
              trajectory_tracker: TrajectoryTracker | None = None) -> None:
        roi = roi or {"enabled": False, "points": []}
        visualization = visualization or {}
        trajectories = trajectories or {}
        if visualization.get("trajectory_enabled", True):
            highlighted = visualization.get("selected_track_id")
            for track_id, history in trajectories.items():
                color_seed = (int(track_id) * 47) % 180
                color = (80 + color_seed // 2, 100 + color_seed // 3, 180 + color_seed // 4)
                if highlighted is not None and int(highlighted) != int(track_id):
                    color = (75, 80, 85)
                segment: list[tuple[int, int]] = []
                for point in history:
                    if point.get("observed_status") != "observed":
                        if len(segment) > 1:
                            cv2.polylines(frame, [np.asarray(segment, dtype=np.int32)], False, color, 2, cv2.LINE_AA)
                        segment = []
                    else:
                        segment.append((int(point["center_x"]), int(point["center_y"])))
                if len(segment) > 1:
                    cv2.polylines(frame, [np.asarray(segment, dtype=np.int32)], False, color, 2, cv2.LINE_AA)
                if visualization.get("show_direction") and segment and trajectory_tracker:
                    direction = trajectory_tracker.direction(track_id)
                    if direction:
                        x, y = segment[-1]
                        end = (int(x + direction[0] * 36), int(y + direction[1] * 36))
                        cv2.arrowedLine(frame, (x, y), end, color, 2, cv2.LINE_AA, tipLength=0.35)
        points = roi.get("points", [])
        if len(points) >= 3:
            height, width = frame.shape[:2]
            polygon = np.array([[round(x * width), round(y * height)] for x, y in points], dtype=np.int32)
            cv2.polylines(frame, [polygon], True, (65, 205, 190) if roi.get("enabled") else (120, 145, 150), 2)
            if roi.get("enabled"):
                overlay = frame.copy()
                cv2.fillPoly(overlay, [polygon], (45, 120, 105))
                cv2.addWeighted(overlay, 0.13, frame, 0.87, 0, frame)
        for d in detections:
            x1, y1, x2, y2 = map(int, d["bbox"])
            color = (64, 210, 140) if d["track_id"] is not None else (235, 175, 75)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label = f"{d['class_name']} {d['confidence']:.2f}"
            if visualization.get("show_track_ids", True) and d["track_id"] is not None:
                label += f" ID:{d['track_id']}"
            cv2.putText(frame, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    def _filter_roi(self, detections: list[dict[str, Any]], width: int, height: int) -> list[dict[str, Any]]:
        if not self._roi.get("enabled") or len(self._roi.get("points", [])) < 3:
            return detections
        return [d for d in detections if contains(self._roi, d['bbox'], width, height)]

    def _run_verification(self, item) -> None:
        generation, event_ids = item[0], item[1]
        try:
            generation, event_ids, timestamp, frame_index, frame, detections, contexts = item
            if generation != self._generation:
                return
            values = self.settings.values
            predictions = []
            inference_error = None
            for event_id in event_ids:
                event = self.storage.get_event(event_id)
                if not event:
                    continue
                context = contexts[event_id]
                crop, crop_box = self._verification_crop(mask_full(frame, self._roi), detections, context["related_track_ids"])
                try:
                    event_predictions = self.models.accident_predict(crop, conf=float(values["accident_confidence"]), imgsz=int(values["accident_imgsz"]))
                    predictions.extend([{**prediction, "bbox": [prediction["bbox"][0] + crop_box[0], prediction["bbox"][1] + crop_box[1],
                                                                  prediction["bbox"][2] + crop_box[0], prediction["bbox"][3] + crop_box[1]],
                                        "crop_bbox": crop_box} for prediction in event_predictions])
                except Exception as exc:
                    inference_error = f"accident_inference_error: {exc}"
                    self._record_sample_issue(event_id, timestamp, frame_index, inference_error)
            if generation != self._generation:
                return
            for event_id in event_ids:
                event = self.storage.get_event(event_id)
                verifier = self._event_verifiers.get(event_id)
                if not event or verifier is None:
                    continue
                context = contexts[event_id]
                related_ids = set(context["related_track_ids"])
                event_vehicles = [vehicle for vehicle in detections if vehicle.get("track_id") in related_ids]
                verifier.rules["event_track_ids"] = list(related_ids)
                result = verifier.add(timestamp, [p for p in predictions if not p.get("crop_bbox") or
                                                   self._prediction_intersects_tracks(p, event_vehicles)], occluded=not event_vehicles,
                                                              vehicle_tracks=event_vehicles,
                                                              trajectory_change=context["suspicion"],
                                                              frame_index=frame_index)
                with self._lock:
                    self._runtime["accident_detections"] = [dict(d) for d in predictions if d.get("class_name", "").casefold() == "accident"]
                self._emit({"type": "verification", "event_id": event_id, "timestamp": timestamp,
                            "frame_index": frame_index, "result": result, "detections": predictions})
                manual_review = event.get("manual_review") or {}
                if manual_review.get("status") in {"CONFIRMED", "REJECTED", "UNCERTAIN"}:
                    event["status"] = manual_review["status"]
                    event["manual_review_status"] = event["status"]
                else:
                    event["status"] = "SUSPECTED" if result["status"] == "READY_FOR_REVIEW" else result["status"]
                event["ended_at"] = time.time() if event["status"] == "UNCERTAIN" else None
                event["last_seen_timestamp"] = timestamp
                event["max_confidence"] = max(float(event.get("max_confidence", 0)), float(result["max_confidence"]))
                event["verification"] = result
                event["technical_status"] = result["status"]
                event["processing_status"] = "COLLECTING" if result["status"] in {"SUSPECTED", "READY_FOR_REVIEW"} else "COMPLETE"
                event["decision_reason"] = result["reason"]
                event["observation_quality"] = result["observation_quality"]
                event["related_track_ids"] = sorted(set(event.get("related_track_ids", [])) | set(result["related_track_ids"]))
                event["accident_detections"].extend({"timestamp": timestamp, "frame_index": frame_index, **prediction}
                                                    for prediction in predictions
                                                    if prediction.get("class_name", "").casefold() == "accident")
                event["trajectory"].update(context["trajectory"])
                event["evidence_summary"] = {"sampled_observations": result["window_frames"],
                                             "positive_observations": result["positive_observations"],
                                             "max_accident_confidence": result["max_confidence"],
                                             "temporal_consistency": result["temporal_consistency"],
                                             "candidate_pair_history": verifier.rules.get("candidate_history", [])}
                prior_statuses = {entry.get("status") for entry in event.get("status_history", [])}
                event.setdefault("status_history", []).extend(entry for entry in verifier.transitions
                                                               if entry.get("status") not in prior_statuses)
                event.setdefault("verification_samples", []).append({"event_id": event_id, "timestamp": timestamp,
                    "frame_index": frame_index, "detections": [p for p in predictions if not p.get("crop_bbox") or
                    self._prediction_intersects_tracks(p, event_vehicles)], "crop_bbox": self._verification_crop(frame, detections, list(related_ids))[1],
                    "observation_quality": result["observation_quality"], "inference_error": inference_error})
                if result["status"] == "READY_FOR_REVIEW":
                    event["review_status"] = "PENDING"
                    event["processing_status"] = "READY_FOR_REVIEW"
                    event.setdefault("status_history", []).append({"status": "READY_FOR_REVIEW", "timestamp": timestamp,
                                                                      "reason": result["reason"]})
                    self._close_active_event(event_id, timestamp)
                self.storage.save_event(event)
                with self._lock:
                    self._runtime["last_verification"] = {"event_id": event_id, **result}
                if result["status"] == "UNCERTAIN":
                    self._close_active_event(event_id, timestamp, cooldown=float(self.rules.get("accident_verification_timeout_seconds", 3.0)))
                self._emit({"type": "event_update", "event": event})
                if event["status"] in {"UNCERTAIN", "CONFIRMED", "REJECTED"}:
                    self._event_verifiers.pop(event_id, None)
                    self._last_event_verify_timestamp.pop(event_id, None)
        finally:
            with self._lock:
                self._verification_pending.difference_update(event_ids)

    @staticmethod
    def _verification_crop(frame: np.ndarray, detections: list[dict[str, Any]], related_ids: list[int]):
        height, width = frame.shape[:2]
        vehicles = [d for d in detections if d.get("track_id") in set(related_ids)]
        if not vehicles:
            return frame, [0, 0, width, height]
        boxes = [d["bbox"] for d in vehicles]
        x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        pad_x, pad_y = max(24, (x2 - x1) // 2), max(24, (y2 - y1) // 2)
        x1, y1 = max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y))
        x2, y2 = min(width, int(x2 + pad_x)), min(height, int(y2 + pad_y))
        if x2 <= x1 or y2 <= y1:
            return frame, [0, 0, width, height]
        return frame[y1:y2, x1:x2].copy(), [x1, y1, x2, y2]

    @staticmethod
    def _prediction_intersects_tracks(prediction: dict[str, Any], vehicles: list[dict[str, Any]]) -> bool:
        a = prediction.get("bbox", [0, 0, 0, 0])
        for vehicle in vehicles:
            b = vehicle.get("bbox", [0, 0, 0, 0])
            intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
            if intersection > 0:
                return True
        return False

    def _record_sample_issue(self, event_id: str, timestamp: float, frame_index: int, reason: str) -> None:
        event = self.storage.get_event(event_id)
        if not event:
            return
        event.setdefault("evidence_issues", []).append({"timestamp": timestamp, "frame_index": frame_index,
                                                         "reason": reason})
        if "inference_error" in reason:
            event["processing_status"] = "ERROR"
        self.storage.save_event(event)

    def _record_dropped_sample(self, item: Any, reason: str) -> None:
        _, event_ids, timestamp, frame_index = item[:4]
        for event_id in event_ids:
            self._record_sample_issue(event_id, timestamp, frame_index, reason)

    def _close_active_event(self, event_id: str, timestamp: float, *, cooldown: float = 0.0) -> None:
        self._active_events.pop(event_id, None)
        event_key = self._event_keys.pop(event_id, None)
        if event_key:
            self._active_event_keys.pop(event_key, None)
            self._event_cooldowns[event_key] = timestamp + cooldown
        self._active_event = next(iter(self._active_events.values()), None)

    def event_reviewed(self, event: dict[str, Any]) -> None:
        if event.get("status") in {"CONFIRMED", "REJECTED", "UNCERTAIN"}:
            timestamp = float(event.get("last_seen_timestamp") or 0)
            event_id = event["event_id"]
            self._close_active_event(event_id, timestamp, cooldown=1.0)
            if event_id not in self._verification_pending:
                self._event_verifiers.pop(event_id, None)
                self._last_event_verify_timestamp.pop(event_id, None)

    def pause(self) -> None:
        with self._lock:
            if self._runtime["state"] == "RUNNING":
                self._runtime["state"] = "PAUSED"
            else:
                raise RuntimeError("Pipeline không ở trạng thái RUNNING")
        self._emit({"type": "state", "state": "PAUSED"})

    def resume(self) -> None:
        with self._lock:
            if self._runtime["state"] == "PAUSED":
                self._runtime["state"] = "RUNNING"
            else:
                raise RuntimeError("Pipeline không ở trạng thái PAUSED")
        self._emit({"type": "state", "state": "RUNNING"})

    def stop(self) -> None:
        with self._lock:
            self._runtime["state"] = "STOPPED"
            self._runtime["tracked_vehicles"] = []
            reader = self._reader_thread
        if reader and reader is not threading.current_thread():
            reader.join(timeout=10)
        self._worker.stop()
        self._emit({"type": "state", "state": "STOPPED"})

    def set_speed(self, speed: float) -> None:
        # Kept for API compatibility; uploaded videos are processed as fast as possible.
        if float(speed) <= 0:
            raise ValueError("Tốc độ phải lớn hơn 0")

    def set_visualization(self, options: dict[str, Any]) -> dict[str, Any]:
        allowed = {"trajectory_enabled", "show_track_ids", "show_direction", "history_seconds", "selected_track_id"}
        if set(options) - allowed:
            raise ValueError("Tùy chọn hiển thị không hợp lệ")
        updated = {**self._visualization, **options}
        for key in ("trajectory_enabled", "show_track_ids", "show_direction"):
            if not isinstance(updated[key], bool):
                raise ValueError(f"{key} phải là boolean")
        updated["history_seconds"] = float(updated["history_seconds"])
        if not 1 <= updated["history_seconds"] <= 30:
            raise ValueError("history_seconds phải thuộc [1, 30]")
        selected = updated["selected_track_id"]
        updated["selected_track_id"] = int(selected) if selected not in (None, "", "all") else None
        with self._lock:
            self._visualization = updated
            self._trajectory.history_seconds = updated["history_seconds"]
        return dict(updated)

    def clear_trajectories(self) -> None:
        self._trajectory.reset()
        self._emit({"type": "trajectory_clear"})

    def apply_config(self) -> None:
        with self._lock:
            if self._runtime["state"] in {"RUNNING", "PAUSED"}:
                raise RuntimeError("Dừng pipeline trước khi áp dụng cấu hình")
            self.rules = self.settings.rules
            self._diagnostics_enabled = bool(self.rules.get("diagnostics_enabled", False))
            self._suspect = SuspicionAnalyzer(self.rules)
            self._verifier = EventVerifier(self.rules)
            self._evidence = EvidenceBuffer(int(self.rules["evidence_pre_seconds"]), int(self.rules["evidence_post_seconds"]))
            values = self.settings.values
            self._visualization.update({"trajectory_enabled": bool(values.get("trajectory_enabled", True)),
                                        "show_track_ids": bool(values.get("show_track_ids", True)),
                                        "show_direction": bool(values.get("show_direction", True)),
                                        "history_seconds": float(values.get("trajectory_history_seconds", 6))})
            self._trajectory = TrajectoryTracker(history_seconds=float(values.get("trajectory_history_seconds", 6)),
                max_gap_seconds=float(values.get("trajectory_max_gap_seconds", 0.75)),
                max_points=int(values.get("trajectory_max_points", 96)),
                min_direction_distance=float(values.get("trajectory_min_direction_pixels", 8)))
            self._worker.tasks.maxsize = int(self.settings.values["verification_queue_size"])

    def _fail(self, message: str) -> None:
        log.error(message)
        with self._lock:
            self._last_error = message
            self._runtime["state"] = "ERROR"
        self._emit({"type": "error", "message": message})

    def frame_packet(self) -> tuple[int, bytes] | None:
        with self._lock:
            if self._jpeg_frame is None:
                return None
            return self._jpeg_sequence, self._jpeg_frame

    def frame_jpeg(self) -> bytes | None:
        packet = self.frame_packet()
        return packet[1] if packet else None


def fps_value(value: Any) -> float:
    return round(float(value or 0), 2)
