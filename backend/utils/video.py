from pathlib import Path
from typing import Any
import cv2

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}


def inspect_video(path: Path) -> dict[str, Any]:
    if path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES or not path.is_file():
        raise ValueError("Đường dẫn hoặc định dạng video không hợp lệ")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError("OpenCV không mở được video; file hỏng hoặc thiếu codec")
    result = {"width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
              "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
              "fps": float(capture.get(cv2.CAP_PROP_FPS)),
              "frames": int(capture.get(cv2.CAP_PROP_FRAME_COUNT))}
    capture.release()
    return result
