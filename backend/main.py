import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import psutil
import torch
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.core.config import ConfigurationError, DEFAULT_RULES, DEFAULT_SETTINGS, ROOT, Settings
from backend.core.pipeline import Pipeline
from backend.detection.models import ModelLoadError, ModelManager
from backend.storage.local_storage import LocalStorageService


class LocalTimeFormatter(logging.Formatter):
    converter = time.localtime


def configure_logging(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    formatter = LocalTimeFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(directory / "atads.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        root.addHandler(file_handler)
        root.addHandler(console)


class EventUpdate(BaseModel):
    status: str = ""
    notes: str = Field(default="", max_length=4000)
    severity: str | None = Field(default=None, pattern="^(UNASSESSED|LOW|MODERATE|HIGH|CRITICAL)$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
class ConfigUpdate(BaseModel):
    settings: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    paths = settings.values
    data_dir = (ROOT / paths["data_dir"]).resolve()
    if ROOT not in data_dir.parents:
        raise RuntimeError("data_dir phải nằm trong thư mục dự án")
    storage = LocalStorageService(data_dir)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    configure_logging(storage.logs_dir)
    try:
        models = ModelManager(paths)
    except ModelLoadError:
        logging.getLogger("atads.startup").exception("Không khởi tạo được AI")
        raise
    app.state.settings, app.state.storage, app.state.models = settings, storage, models
    app.state.pipeline = Pipeline(models, storage, settings, settings.rules)
    yield
    app.state.pipeline.stop()


app = FastAPI(title="ATADS", version="1.0.0", description="Hệ thống phát hiện tai nạn giao thông tự động từ camera", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=ROOT / "frontend" / "assets", check_dir=False), name="assets")
app.mount("/css", StaticFiles(directory=ROOT / "frontend" / "css"), name="css")
app.mount("/js", StaticFiles(directory=ROOT / "frontend" / "js"), name="js")


def services(request: Request):
    return request.app.state.settings, request.app.state.storage, request.app.state.models, request.app.state.pipeline


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/status")
def status(request: Request):
    settings, storage, models, pipeline = services(request)
    try:
        cpu_percent, memory_percent = psutil.cpu_percent(interval=None), psutil.virtual_memory().percent
    except Exception:
        cpu_percent = memory_percent = None
    gpu = {"available": torch.cuda.is_available(), "name": None, "vram_total_mb": None,
           "vram_used_mb": None, "utilization_percent": None}
    if gpu["available"]:
        try:
            index = int(settings.values["device"])
            props = torch.cuda.get_device_properties(index)
            gpu.update({"name": props.name, "vram_total_mb": round(props.total_memory / 1048576),
                        "vram_used_mb": round(torch.cuda.memory_allocated(index) / 1048576)})
        except (ValueError, RuntimeError):
            pass
    events, count = storage.list_events(limit=10000)
    states = {name: sum(1 for event in events if event.get("status") == name)
              for name in ("SUSPECTED", "CONFIRMED", "UNCERTAIN", "REJECTED")}
    runtime = pipeline.status()
    return {"backend": "online", "models": models.info(), "gpu": gpu,
            "system": {"cpu_percent": cpu_percent, "ram_percent": memory_percent,
                       "upload_free_gb": round(shutil.disk_usage(storage.root).free / 1e9, 2)},
            "pipeline": runtime, "events": {"total": count, "by_status": states},
            "verification_queue": runtime["queue_size"], "dropped_verifications": runtime["dropped_frames"]}


@app.post("/api/videos/upload")
async def upload_video(request: Request, file: UploadFile = File(...)):
    settings, storage, _, _ = services(request)
    allowed = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(415, "Định dạng hỗ trợ: MP4, AVI, MOV, MKV, M4V")
    limit = int(settings.rules["upload_max_mb"]) * 1024 * 1024
    destination = storage.root / "uploads" / f"UP-{uuid.uuid4().hex}{suffix}"
    size = 0
    fingerprint = hashlib.sha256()
    try:
        with destination.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Video vượt giới hạn {settings.rules['upload_max_mb']} MB")
                out.write(chunk)
                fingerprint.update(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "File tải lên rỗng")
    import cv2
    capture = cv2.VideoCapture(str(destination))
    if not capture.isOpened():
        destination.unlink(missing_ok=True)
        raise HTTPException(415, "OpenCV không giải mã được video; kiểm tra codec hoặc file bị lỗi")
    metadata = {"width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": capture.get(cv2.CAP_PROP_FPS), "frames": int(capture.get(cv2.CAP_PROP_FRAME_COUNT))}
    capture.release()
    return {"upload_id": destination.name, "roi_key": fingerprint.hexdigest(), "filename": filename, "size_bytes": size,
            "metadata": metadata, "stored": destination.name}


def resolve_upload(storage: LocalStorageService, upload_id: str) -> Path:
    if not re.fullmatch(r"UP-[a-f0-9]{32}\.(mp4|avi|mov|mkv|m4v)", upload_id, re.IGNORECASE):
        raise HTTPException(404, "Không tìm thấy video tải lên")
    path = (storage.root / "uploads" / upload_id).resolve()
    if path.parent != (storage.root / "uploads").resolve() or not path.is_file():
        raise HTTPException(404, "Không tìm thấy video tải lên")
    return path


@app.get("/api/videos/{upload_id}/preview")
def video_preview(request: Request, upload_id: str):
    import cv2
    path = resolve_upload(services(request)[1], upload_id)
    capture = cv2.VideoCapture(str(path))
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise HTTPException(422, "Không đọc được frame đầu video")
    encoded, image = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not encoded:
        raise HTTPException(500, "Không thể tạo ảnh xem trước")
    from fastapi.responses import Response
    return Response(image.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/roi/{source_key}")
def get_roi(request: Request, source_key: str):
    if not re.fullmatch(r"[a-f0-9]{64}", source_key):
        raise HTTPException(422, "Mã nguồn ROI không hợp lệ")
    settings = services(request)[0]
    return {"source_key": source_key, **settings.get_roi(source_key)}


@app.put("/api/roi/{source_key}")
def put_roi(request: Request, source_key: str, body: dict):
    settings, storage, _, pipeline = services(request)
    if not re.fullmatch(r"[a-f0-9]{64}", source_key):
        raise HTTPException(422, "Mã nguồn ROI không hợp lệ")
    if pipeline.status()["state"] in {"RUNNING", "PAUSED"}:
        raise HTTPException(409, "Dừng video trước khi thay đổi ROI")
    try:
        value = settings.set_roi(source_key, body)
    except (ConfigurationError, OSError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"source_key": source_key, **value}


@app.post("/api/pipeline/start")
def start_pipeline(request: Request, body: dict[str, str]):
    settings, storage, _, pipeline = services(request)
    try:
        source_type = body.get("source_type", "video")
        if source_type == "video":
            source = body.get("upload_id", "")
            resolve_upload(storage, source)
            roi_key = body.get("roi_key", "")
            if not re.fullmatch(r"[a-f0-9]{64}", roi_key):
                raise ValueError("Thiếu mã ROI nguồn; hãy tải lại video để tạo preview.")
            roi = settings.get_roi(roi_key)
        elif source_type == "camera":
            source = body.get("camera_source", "").strip()
            if not source or len(source) > 2048:
                raise ValueError("Thiếu nguồn camera hoặc URL camera quá dài")
            roi_key = hashlib.sha256(source.encode("utf-8")).hexdigest()
            roi = settings.get_roi(roi_key)
        else:
            raise ValueError("source_type chỉ nhận video hoặc camera")
        pipeline.start(source, source_type, roi)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return pipeline.status()


@app.post("/api/pipeline/{action}")
def pipeline_action(request: Request, action: str):
    _, _, _, pipeline = services(request)
    handlers = {"pause": pipeline.pause, "resume": pipeline.resume, "stop": pipeline.stop}
    if action not in handlers:
        raise HTTPException(404, "Lệnh pipeline không hợp lệ")
    try:
        handlers[action]()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return pipeline.status()


@app.put("/api/pipeline/speed")
def pipeline_speed(request: Request, body: dict):
    try:
        services(request)[3].set_speed(float(body.get("speed", 1)))
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"speed": "unlimited"}


@app.put("/api/pipeline/visualization")
def pipeline_visualization(request: Request, body: dict):
    settings, _, _, pipeline = services(request)
    options = {key: value for key, value in body.items() if key in {
        "trajectory_enabled", "show_track_ids", "show_direction", "history_seconds", "selected_track_id"}}
    try:
        visualization = pipeline.set_visualization(options)
        persistent = {"trajectory_enabled": visualization["trajectory_enabled"],
                      "show_track_ids": visualization["show_track_ids"],
                      "show_direction": visualization["show_direction"],
                      "trajectory_history_seconds": visualization["history_seconds"]}
        settings.update(persistent)
    except (ValueError, ConfigurationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"visualization": visualization}


@app.post("/api/pipeline/trajectories/clear")
def clear_pipeline_trajectories(request: Request):
    pipeline = services(request)[3]
    pipeline.clear_trajectories()
    return {"cleared": True}


@app.get("/api/pipeline/status")
def pipeline_status(request: Request):
    return services(request)[3].status()


@app.get("/api/pipeline/frame")
def pipeline_frame(request: Request):
    frame = services(request)[3].frame_jpeg()
    if frame is None:
        raise HTTPException(404, "Chưa có khung hình")
    from fastapi.responses import Response
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/pipeline/stream")
async def pipeline_stream(request: Request):
    pipeline = services(request)[3]

    async def frames():
        last_sequence = -1
        while not await request.is_disconnected():
            packet = pipeline.frame_packet()
            if packet and packet[0] != last_sequence:
                last_sequence, jpeg = packet
                yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-store\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(1 / 30)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"})


@app.websocket("/api/ws")
async def websocket_updates(websocket: WebSocket):
    await websocket.accept()
    pipeline = websocket.app.state.pipeline
    cursor = 0
    try:
        while True:
            updates = pipeline.poll(cursor)
            for item in updates:
                cursor = max(cursor, int(item.get("sequence", cursor)))
                await websocket.send_json(item)
            if not updates:
                await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return


@app.get("/api/events")
def list_events(request: Request, status_filter: str | None = Query(default=None, alias="status"),
                source: str | None = None, q: str | None = None, offset: int = 0, limit: int = 50,
                start_date: str | None = None, end_date: str | None = None):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Phân trang không hợp lệ")
    _, storage, _, _ = services(request)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "start_date phải trước end_date")
    events, _ = storage.list_events(status=status_filter, source=source, query=q, offset=0, limit=10**9)
    if start_date:
        events = [event for event in events if event.get("created_at", "")[:10] >= start_date]
    if end_date:
        events = [event for event in events if event.get("created_at", "")[:10] <= end_date]
    return {"items": events[offset:offset + limit], "total": len(events), "offset": offset, "limit": limit}


@app.get("/api/events/{event_id}")
def event_detail(request: Request, event_id: str):
    event = services(request)[1].get_event(event_id)
    if not event:
        raise HTTPException(404, "Không tìm thấy sự kiện")
    return event


@app.patch("/api/events/{event_id}")
def update_event(request: Request, event_id: str, body: EventUpdate):
    allowed = {"SUSPECTED", "CONFIRMED", "UNCERTAIN", "REJECTED"}
    if body.status and body.status not in allowed:
        raise HTTPException(422, "Trạng thái không hợp lệ")
    _, storage, _, pipeline = services(request)
    event = storage.update_event(event_id, status=body.status or None,
                                 notes=body.notes if "notes" in body.model_fields_set else None,
                                 severity=body.severity if "severity" in body.model_fields_set else None,
                                 latitude=body.latitude if "latitude" in body.model_fields_set else None,
                                 longitude=body.longitude if "longitude" in body.model_fields_set else None)
    if not event:
        raise HTTPException(404, "Không tìm thấy sự kiện")
    pipeline.event_reviewed(event)
    return event


@app.get("/api/events/{event_id}/evidence/{kind}")
def evidence_file(request: Request, event_id: str, kind: str):
    if kind not in {"image", "video"}:
        raise HTTPException(404, "Loại bằng chứng không hợp lệ")
    _, storage, _, _ = services(request)
    event = storage.get_event(event_id)
    relative = (event or {}).get("evidence", {}).get(kind)
    if not relative:
        raise HTTPException(404, "Bằng chứng chưa được ghi")
    base = storage.root.resolve()
    path = (base / relative).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404, "Không tìm thấy file bằng chứng")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


@app.get("/api/export/{kind}")
def export_events(request: Request, kind: str, status_filter: str | None = Query(default=None, alias="status")):
    if kind not in {"csv", "json"}:
        raise HTTPException(404, "Hỗ trợ xuất CSV hoặc JSON")
    _, storage, _, _ = services(request)
    events, _ = storage.list_events(status=status_filter, limit=10**9)
    path = storage.export_events(events, kind)
    return FileResponse(path, filename=path.name)


@app.get("/api/config")
def get_config(request: Request):
    settings, _, _, _ = services(request)
    return {"settings": settings.values, "rules": settings.rules}


@app.get("/api/config/defaults")
def default_config():
    return {"settings": DEFAULT_SETTINGS, "rules": DEFAULT_RULES}

@app.put("/api/config")
def update_config(request: Request, body: ConfigUpdate):
    settings, _, _, pipeline = services(request)
    if pipeline.status()["state"] in {"RUNNING", "PAUSED"}:
        raise HTTPException(409, "Dừng video trước khi lưu và áp dụng cấu hình")
    try:
        values = settings.update(body.settings, body.rules)
        pipeline.apply_config()
    except (ConfigurationError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    values["restart_required"] = bool({"vehicle_model", "accident_model", "device"} & body.settings.keys())
    return values


@app.get("/api/logs")
def read_logs(request: Request, q: str | None = None, limit: int = 300):
    _, storage, _, _ = services(request)
    path = storage.logs_dir / "atads.log"
    if not path.is_file():
        return {"items": []}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(limit, 2000)):]
    if q:
        lines = [line for line in lines if q.casefold() in line.casefold()]
    return {"items": lines}


@app.get("/api/reports")
def reports(request: Request):
    _, storage, models, pipeline = services(request)
    events, _ = storage.list_events(limit=10**9)
    by_day: dict[str, dict[str, int]] = {}
    for event in events:
        day = event.get("created_at", "")[:10]
        if not day:
            continue
        by_day.setdefault(day, {})[event.get("status", "UNKNOWN")] = by_day.setdefault(day, {}).get(event.get("status", "UNKNOWN"), 0) + 1
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "events_by_day": by_day,
            "total_events": len(events), "model_status": models.info(), "pipeline": pipeline.status(),
            "disclaimer": "Đây là thống kê sự kiện đã ghi nhận, không phải độ chính xác mô hình; chưa đối chiếu ground truth."}
