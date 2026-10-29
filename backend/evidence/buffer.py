from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class EvidenceBuffer:
    def __init__(self, pre_seconds: int = 5, post_seconds: int = 5, max_fps: float = 12):
        self.pre_seconds, self.post_seconds, self.max_fps = pre_seconds, post_seconds, max_fps
        self.frames: deque[tuple[float, np.ndarray]] = deque(maxlen=int(pre_seconds * max_fps) + 2)
        self.pending: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def add(self, timestamp: float, frame: np.ndarray) -> list[tuple[str, Path | None, str | None]]:
        results = []
        with self.lock:
            if not self.frames or timestamp - self.frames[-1][0] >= 1 / self.max_fps:
                self.frames.append((timestamp, frame.copy()))
            for event_id, capture in list(self.pending.items()):
                if timestamp > capture["deadline"]:
                    results.append(self._finalize(event_id, capture, post_complete=True))
                elif timestamp > capture["start"] and timestamp - capture["frames"][-1][0] >= 1 / self.max_fps:
                    capture["frames"].append((timestamp, frame.copy()))
        return results

    def trigger(self, event_id: str, timestamp: float, destination: Path) -> tuple[Path | None, str | None]:
        with self.lock:
            if event_id in self.pending:
                return None, "duplicate_event"
            before = [(t, f.copy()) for t, f in self.frames if timestamp - t <= self.pre_seconds]
            if not before:
                before = [(timestamp, np.zeros((1, 1, 3), dtype=np.uint8))]
            self.pending[event_id] = {"start": timestamp, "deadline": timestamp + self.post_seconds,
                                      "frames": before, "destination": destination}
            return None, "collecting_post_event_frames"

    def finish_pending(self) -> list[tuple[str, Path | None, str | None]]:
        """Persist partial clips at source end and disclose their incomplete post window."""
        results = []
        with self.lock:
            for event_id, capture in list(self.pending.items()):
                results.append(self._finalize(event_id, capture, post_complete=False))
        return results

    def _finalize(self, event_id: str, capture: dict[str, Any], post_complete: bool) -> tuple[str, Path | None, str | None]:
        self.pending.pop(event_id, None)
        frames = capture["frames"]
        if len(frames) < 2 or frames[0][1].shape[0] < 16:
            return event_id, None, "insufficient_frames"
        height, width = frames[0][1].shape[:2]
        destination: Path = capture["destination"]
        writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"mp4v"), self.max_fps, (width, height))
        if not writer.isOpened():
            return event_id, None, "codec_unavailable"
        try:
            for _, frame in frames:
                if frame.shape[:2] != (height, width):
                    continue
                writer.write(frame)
        finally:
            writer.release()
        return event_id, destination if destination.is_file() else None, None if post_complete else "post_event_window_incomplete"
