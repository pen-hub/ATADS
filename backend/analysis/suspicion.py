from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any


def _iou(a: list[float], b: list[float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


class SuspicionAnalyzer:
    """Raises review triggers from track interactions and image-plane motion only."""

    def __init__(self, rules: dict[str, Any]):
        self.rules = rules
        self._counts: dict[str, int] = defaultdict(int)
        self._centers: dict[int, deque[tuple[float, float, float]]] = defaultdict(lambda: deque(maxlen=8))
        self._pair_distances: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=4))
        self._last_seen: dict[int, float] = {}

    def analyze(self, detections: list[dict[str, Any]], width: int, height: int, frame_index: int,
                timestamp: float | None = None) -> dict[str, Any] | None:
        timestamp = float(frame_index if timestamp is None else timestamp)
        vehicles = [d for d in detections if d.get("track_id") is not None]
        for detection in vehicles:
            x1, _, x2, y2 = detection["bbox"]
            self._centers[int(detection["track_id"])].append((timestamp,
                (x1 + x2) / 2 / max(width, 1), y2 / max(height, 1)))
            self._last_seen[int(detection["track_id"])] = timestamp
        for track_id, last_seen in list(self._last_seen.items()):
            if timestamp - last_seen > 10:
                self._last_seen.pop(track_id, None)
                self._centers.pop(track_id, None)
        active_ids = set(self._last_seen)
        for key in list(self._counts):
            track_ids = {int(value) for value in key.split(",")}
            if any(track_id not in active_ids for track_id in track_ids):
                self._counts.pop(key, None)
                self._pair_distances.pop(key, None)

        candidates: list[tuple[float, list[int], list[str], dict[str, Any]]] = []
        for i, first in enumerate(vehicles):
            for second in vehicles[i + 1:]:
                first_id, second_id = int(first["track_id"]), int(second["track_id"])
                key = ",".join(map(str, sorted((first_id, second_id))))
                a = self._centers[first_id][-1]
                b = self._centers[second_id][-1]
                distance = math.hypot(a[1] - b[1], a[2] - b[2])
                iou = _iou(first["bbox"], second["bbox"])
                distances = self._pair_distances[key]
                distances.append(distance)
                closing = len(distances) >= 2 and distances[-1] < distances[-2] - 0.001
                overlap = iou >= float(self.rules["suspicion_iou_threshold"])
                near_and_closing = distance <= float(self.rules["suspicion_distance_ratio"]) and closing
                # Bbox overlap alone is common from detector jitter and perspective.
                # Treat it only as supporting evidence when tracks are also close and approaching.
                if near_and_closing:
                    reason = f"hai track tiến gần nhau trong ảnh (tỷ lệ={distance:.2f})"
                    if overlap:
                        reason += f"; bbox đang giao nhau (IoU={iou:.2f})"
                    candidates.append((max(iou, 1 - distance), [first_id, second_id], [reason],
                                       {"distance_ratio": round(distance, 4), "iou": round(iou, 4),
                                        "bbox_overlap": overlap, "relative_motion": "closing"}))

        min_displacement = float(self.rules.get("trajectory_min_displacement_ratio", 0.025))
        for detection in vehicles:
            track_id = int(detection["track_id"])
            points = list(self._centers[track_id])
            if len(points) < 3:
                continue
            before = (points[-2][1] - points[-3][1], points[-2][2] - points[-3][2])
            after = (points[-1][1] - points[-2][1], points[-1][2] - points[-2][2])
            before_len, after_len = math.hypot(*before), math.hypot(*after)
            if min(before_len, after_len) < min_displacement:
                continue
            cosine = max(-1.0, min(1.0, (before[0] * after[0] + before[1] * after[1]) /
                                    (before_len * after_len)))
            angle = math.degrees(math.acos(cosine))
            if angle >= float(self.rules.get("trajectory_turn_threshold_degrees", 75)):
                candidates.append((angle / 180, [track_id], [f"hướng quỹ đạo ảnh đổi khoảng {round(angle)}°"],
                                   {"trajectory_turn_degrees": round(angle, 1)}))

        if not candidates:
            for key in list(self._counts):
                self._counts[key] = max(0, self._counts[key] - 1)
            return None
        triggered = []
        for score, track_ids, reasons, signals in candidates:
            key = ",".join(map(str, sorted(track_ids)))
            self._counts[key] += 1
            if self._counts[key] >= int(self.rules["suspicion_consecutive_frames"]):
                self._counts[key] = 0
                triggered.append({"frame_index": frame_index, "timestamp": timestamp, "track_ids": track_ids,
                                  "reasons": reasons, "score": round(score, 3), "signals": signals})
        if not triggered:
            return None
        primary = max(triggered, key=lambda item: item["score"])
        return {**primary, "concurrent": triggered}
