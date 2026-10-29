from __future__ import annotations

from collections import deque
from typing import Any


class TrajectoryTracker:
    """Bounded, in-memory history of observed bottom-center positions per track."""

    def __init__(self, *, history_seconds: float = 6.0, max_gap_seconds: float = 0.75,
                 max_points: int = 96, max_tracks: int = 128, min_direction_distance: float = 8.0):
        self.history_seconds = max(0.5, float(history_seconds))
        self.max_gap_seconds = max(0.1, float(max_gap_seconds))
        self.max_points = max(2, int(max_points))
        self.max_tracks = max(1, int(max_tracks))
        self.min_direction_distance = max(0.0, float(min_direction_distance))
        self.tracks: dict[int, deque[dict[str, Any]]] = {}
        self.last_seen: dict[int, float] = {}

    def reset(self) -> None:
        self.tracks.clear()
        self.last_seen.clear()

    def update(self, detections: list[dict[str, Any]], *, frame_index: int, timestamp: float) -> dict[int, list[dict[str, Any]]]:
        seen: set[int] = set()
        for detection in detections:
            track_id = detection.get("track_id")
            if track_id is None:
                continue
            track_id = int(track_id)
            seen.add(track_id)
            history = self.tracks.setdefault(track_id, deque(maxlen=self.max_points))
            previous = self.last_seen.get(track_id)
            if previous is not None and timestamp - previous > self.max_gap_seconds:
                history.append({"track_id": track_id, "frame_index": frame_index, "timestamp": timestamp,
                                "center_x": None, "center_y": None, "bbox": None,
                                "class_name": detection.get("class_name", ""), "confidence": None,
                                "observed_status": "missing"})
            x1, y1, x2, y2 = map(float, detection["bbox"])
            history.append({"track_id": track_id, "frame_index": int(frame_index), "timestamp": float(timestamp),
                            "center_x": (x1 + x2) / 2, "center_y": y2,
                            "bbox": [x1, y1, x2, y2], "class_name": detection.get("class_name", ""),
                            "confidence": float(detection.get("confidence", 0)), "observed_status": "observed"})
            self.last_seen[track_id] = float(timestamp)

        cutoff = timestamp - self.history_seconds
        for track_id, history in list(self.tracks.items()):
            while history and history[0]["timestamp"] < cutoff:
                history.popleft()
            last_seen = self.last_seen.get(track_id, timestamp)
            if not history or (timestamp - last_seen > self.history_seconds and track_id not in seen):
                self.tracks.pop(track_id, None)
                self.last_seen.pop(track_id, None)
        while len(self.tracks) > self.max_tracks:
            oldest = min(self.last_seen, key=self.last_seen.get)
            self.tracks.pop(oldest, None)
            self.last_seen.pop(oldest, None)
        return self.snapshot()

    def snapshot(self) -> dict[int, list[dict[str, Any]]]:
        return {track_id: list(points) for track_id, points in self.tracks.items()}

    def direction(self, track_id: int) -> tuple[float, float] | None:
        history = self.tracks.get(int(track_id), ())
        observed = [p for p in history if p["observed_status"] == "observed"]
        if len(observed) < 3:
            return None
        recent = observed[-5:]
        if any(b["timestamp"] - a["timestamp"] > self.max_gap_seconds for a, b in zip(recent, recent[1:])):
            return None
        previous, current = recent[0], recent[-1]
        dx, dy = current["center_x"] - previous["center_x"], current["center_y"] - previous["center_y"]
        if (dx * dx + dy * dy) ** 0.5 < self.min_direction_distance:
            return None
        length = (dx * dx + dy * dy) ** 0.5
        return dx / length, dy / length
