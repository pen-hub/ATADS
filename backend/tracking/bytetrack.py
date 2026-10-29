from pathlib import Path
import ultralytics


def tracker_config() -> Path:
    path = Path(ultralytics.__file__).resolve().parent / "cfg" / "trackers" / "bytetrack.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy bytetrack.yaml: {path}")
    return path
