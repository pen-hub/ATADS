from __future__ import annotations

import csv
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LocalStorageService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.events_dir = self.root / "events"
        self.images_dir = self.root / "evidence" / "images"
        self.videos_dir = self.root / "evidence" / "videos"
        self.exports_dir = self.root / "exports"
        self.logs_dir = self.root / "logs"
        for directory in (self.events_dir, self.images_dir, self.videos_dir, self.exports_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _event_id() -> str:
        return f"AT-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8].upper()}"

    def create_event(self, **fields: Any) -> dict[str, Any]:
        event = {
            "event_id": self._event_id(), "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": fields.pop("started_at", datetime.now(timezone.utc).isoformat()),
            "ended_at": None, "source": "", "status": "SUSPECTED", "detections": [],
            "related_track_ids": [], "reasons": [], "manual_review": None,
            "evidence": {"image": None, "video": None}, "notes": "",
            "start_timestamp": None, "last_seen_timestamp": None, "evidence_summary": {},
            "decision_reason": "", "accident_detections": [], "observation_quality": "unknown",
            "manual_review_status": None, "technical_status": "SUSPECTED", "review_status": "PENDING",
            "processing_status": "COLLECTING", "status_history": [], "verification_samples": [],
            "evidence_issues": [], "trajectory": {}, **fields,
        }
        self.save_event(event)
        return event

    def save_event(self, event: dict[str, Any]) -> None:
        event_id = event.get("event_id", "")
        if not isinstance(event_id, str) or not event_id.startswith("AT-") or any(c in event_id for c in "/\\"):
            raise ValueError("event_id không hợp lệ")
        with self._lock:
            self._atomic_json(self.events_dir / f"{event_id}.json", event)

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def list_events(self, *, status: str | None = None, source: str | None = None, query: str | None = None,
                    offset: int = 0, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
        results = []
        with self._lock:
            for path in self.events_dir.glob("AT-*.json"):
                try:
                    event = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if status and event.get("status") != status:
                    continue
                if source and event.get("source") != source:
                    continue
                if query and query.casefold() not in json.dumps(event, ensure_ascii=False).casefold():
                    continue
                results.append(event)
        results.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return results[offset:offset + limit], len(results)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        path = self.events_dir / f"{event_id}.json"
        if path.parent.resolve() != self.events_dir.resolve() or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def update_event(self, event_id: str, *, status: str | None = None, notes: str | None = None,
                     severity: str | None = None, latitude: float | None = None,
                     longitude: float | None = None) -> dict[str, Any] | None:
        with self._lock:
            event = self.get_event(event_id)
            if not event:
                return None
            if status:
                event["status"] = status
                if status in {"CONFIRMED", "REJECTED", "UNCERTAIN"}:
                    event["manual_review"] = {"status": status, "at": datetime.now(timezone.utc).isoformat()}
                    event["manual_review_status"] = status
                    event["review_status"] = status
                    event.setdefault("status_history", []).append({"status": status, "timestamp": datetime.now(timezone.utc).isoformat(),
                                                                     "reason": "Quyết định người duyệt"})
            if notes is not None:
                event["notes"] = notes[:4000]
            if severity is not None:
                event["severity"] = severity
            if latitude is not None or longitude is not None:
                event["location"] = {"latitude": latitude, "longitude": longitude, "coordinate_system": "WGS84"}
            self.save_event(event)
            return event
    def save_image(self, event_id: str, frame: Any) -> str | None:
        import cv2
        path = self.images_dir / f"{event_id}.jpg"
        if not cv2.imwrite(str(path), frame):
            return None
        return path.relative_to(self.root).as_posix()

    def export_events(self, events: list[dict[str, Any]], kind: str) -> Path:
        destination = self.exports_dir / f"events-{datetime.now():%Y%m%d-%H%M%S}.{kind}"
        if kind == "json":
            destination.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        elif kind == "csv":
            columns = ["event_id", "created_at", "started_at", "ended_at", "source", "status", "max_confidence", "related_track_ids", "reasons", "notes"]
            with destination.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for event in events:
                    row = dict(event)
                    for key in ("related_track_ids", "reasons"):
                        row[key] = json.dumps(row.get(key, []), ensure_ascii=False)
                    writer.writerow({key: row.get(key, "") for key in columns})
        else:
            raise ValueError("Định dạng xuất không hỗ trợ")
        return destination
