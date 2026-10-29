from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from ultralytics import YOLO
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.engine.results import Boxes
from types import SimpleNamespace
from backend.core.roi import crop_mask, contains


class ModelLoadError(RuntimeError):
    pass


class ModelManager:
    def __init__(self, settings: dict[str, Any]):
        self._vehicle_lock = threading.RLock()
        self._accident_lock = threading.RLock()
        self.device = str(settings["device"])
        self.vehicle_path = Path(settings["vehicle_model"])
        self.accident_path = Path(settings["accident_model"])
        self.vehicle: YOLO | None = None
        self.accident: YOLO | None = None
        self.vehicle_names: dict[int, str] = {}
        self.accident_names: dict[int, str] = {}
        self.vehicle_inference_ms = 0.0
        self.accident_inference_ms = 0.0
        self._load(settings)

    def _load(self, settings: dict[str, Any]) -> None:
        for name, path in (("vehicle", self.vehicle_path), ("accident", self.accident_path)):
            if not path.is_file():
                raise ModelLoadError(f"Không tìm thấy trọng số {name}: {path}")
        if self.device.lower() != "cpu":
            if not torch.cuda.is_available():
                raise ModelLoadError("CUDA không khả dụng. Kiểm tra driver NVIDIA và bản PyTorch CUDA. Để chủ động chẩn đoán bằng CPU, đặt device=cpu trong config/settings.json.")
            try:
                index = int(self.device)
                properties = torch.cuda.get_device_properties(index)
            except (ValueError, RuntimeError, AssertionError) as exc:
                raise ModelLoadError(f"CUDA device không hợp lệ '{self.device}': {exc}") from exc
            capability = (properties.major, properties.minor)
            compiled = torch.cuda.get_arch_list()
            if capability >= (10, 0) and not any(f"sm_{capability[0]}{capability[1]}" == arch for arch in compiled):
                raise ModelLoadError(
                    f"PyTorch {torch.__version__} không có kernel cho GPU {properties.name} (sm_{capability[0]}{capability[1]}). "
                    f"Architectures được hỗ trợ: {', '.join(compiled)}. Cài bản PyTorch CUDA có hỗ trợ GPU này; "
                    "hoặc chủ động đặt device=cpu để chẩn đoán. ATADS không tự chuyển thiết bị."
                )
        try:
            self.vehicle = YOLO(str(self.vehicle_path))
            self.accident = YOLO(str(self.accident_path))
        except Exception as exc:
            raise ModelLoadError(f"Không thể nạp checkpoint: {exc}") from exc
        self.vehicle_names = {int(k): str(v) for k, v in self.vehicle.names.items()}
        self.accident_names = {int(k): str(v) for k, v in self.accident.names.items()}
        if not self.vehicle_names:
            raise ModelLoadError("Mô hình phương tiện không có danh sách class")
        if "accident" not in {v.casefold() for v in self.accident_names.values()}:
            raise ModelLoadError(f"Mô hình tai nạn không có class 'accident': {self.accident_names}")
        # Fail at startup on an incompatible selected accelerator rather than silently falling back.
        if self.device.lower() != "cpu":
            try:
                with torch.inference_mode():
                    self.vehicle.predict(np.zeros((64, 64, 3), dtype=np.uint8), device=self.device, verbose=False, imgsz=64)
                    self.accident.predict(np.zeros((64, 64, 3), dtype=np.uint8), device=self.device, verbose=False, imgsz=64)
            except Exception as exc:
                raise ModelLoadError(f"Không thể chạy inference trên device={self.device}: {exc}") from exc

    def vehicle_track(self, frame: np.ndarray, *, conf: float, imgsz: int, roi=None) -> list[dict[str, Any]]:
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            raise ValueError("Khung hình đầu vào trống hoặc không hợp lệ")
        with self._vehicle_lock, torch.inference_mode():
            started = time.perf_counter()
            crop, (ox, oy) = crop_mask(frame, roi)
            result = self.vehicle.predict(crop, conf=conf, imgsz=imgsz, device=self.device, verbose=False)[0]
            detections = self._detections(result, self.vehicle_names)
            rows = []
            h, w = frame.shape[:2]
            for d in detections:
                x1,y1,x2,y2 = d['bbox']
                box = [x1+ox,y1+oy,x2+ox,y2+oy]
                if contains(roi, box, w, h):
                    rows.append([*box, d['confidence'], d['class_id']])
            if getattr(self, '_roi_tracker', None) is None:
                self._roi_tracker = BYTETracker(SimpleNamespace(track_high_thresh=.25, track_low_thresh=.1,
                    new_track_thresh=.25, track_buffer=30, match_thresh=.8, fuse_score=True))
            # Update even on empty frames so lost tracks age out. No outside detections enter tracking.
            tracks = self._roi_tracker.update(Boxes(np.asarray(rows, dtype=np.float32).reshape(-1,6), (h,w)))
            output = []
            for t in tracks:
                if not contains(roi, t[:4], w, h): continue
                output.append({'bbox': t[:4].tolist(), 'track_id': int(t[4]), 'confidence': float(t[5]),
                               'class_id': int(t[6]), 'class_name': self.vehicle_names.get(int(t[6]), str(int(t[6])))})
            self.vehicle_inference_ms = (time.perf_counter()-started)*1000
            return output

    def accident_predict(self, frame: np.ndarray, *, conf: float, imgsz: int) -> list[dict[str, Any]]:
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            raise ValueError("Khung hình đầu vào trống hoặc không hợp lệ")
        with self._accident_lock, torch.inference_mode():
            started = time.perf_counter()
            results = self.accident.predict(frame, conf=conf, imgsz=imgsz, device=self.device, verbose=False)
            self.accident_inference_ms = (time.perf_counter() - started) * 1000
        return self._detections(results[0], self.accident_names)

    def reset_tracking(self) -> None:
        with self._vehicle_lock:
            if getattr(self, "_roi_tracker", None) is not None:
                self._roi_tracker.reset()
            predictor = getattr(self.vehicle, "predictor", None)
            for tracker in getattr(predictor, "trackers", []) or []:
                tracker.reset()

    @staticmethod
    def _detections(result: Any, names: dict[int, str]) -> list[dict[str, Any]]:
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []
        coords = boxes.xyxy.cpu().tolist()
        classes = boxes.cls.int().cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(coords)
        return [{"bbox": [round(float(v), 2) for v in box], "class_id": int(class_id),
                 "class_name": names.get(int(class_id), f"class_{class_id}"),
                 "confidence": round(float(conf), 5), "track_id": int(track_id) if track_id is not None else None}
                for box, class_id, conf, track_id in zip(coords, classes, confidences, ids)]

    def info(self) -> dict[str, Any]:
        return {"vehicle": {"loaded": self.vehicle is not None, "path": str(self.vehicle_path), "classes": self.vehicle_names,
                             "inference_ms": round(self.vehicle_inference_ms, 2)},
                "accident": {"loaded": self.accident is not None, "path": str(self.accident_path), "classes": self.accident_names,
                             "inference_ms": round(self.accident_inference_ms, 2)},
                "device": self.device, "cuda_available": torch.cuda.is_available(),
                "gpu": torch.cuda.get_device_name(int(self.device)) if self.device.isdigit() and torch.cuda.is_available() else None}
