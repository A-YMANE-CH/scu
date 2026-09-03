from __future__ import annotations

import argparse
import csv
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse, urlsplit, urlunsplit

import cv2
import numpy as np
import psutil

from entrance_people_detector import (
    DEFAULT_GEOMETRIES,
    EntranceGeometry,
    TrackHistory,
    box_overlap_fraction,
    denorm_box,
    denorm_line,
    parse_camera_video_sources,
    point_inside_box,
    resolve_project_path,
)
from entrance_web_ui import HTML
from person_101_reid import load_cameras, open_capture, parse_source, sane_fps
from retail_dashboard_core import apply_rtsp_channel, draw_label, encode_jpeg


CONFIG_MODE = "cam501_center_v1"
YOLOX_MODEL_SIZE = 416
YOLOX_PERSON_CLASS = 0


@dataclass
class CameraState:
    camera_id: str
    geometry: EntranceGeometry
    calibrated: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    latest_jpeg: bytes | None = None
    latest_clean_jpeg: bytes | None = None
    latest_shape: tuple[int, int] | None = None
    running: bool = False
    error: str = ""
    frame_index: int = 0
    fps: float = 0.0
    entry_count: int = 0
    exit_count: int = 0
    tracks: dict[int, TrackHistory] = field(default_factory=dict)
    recent_people: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EntranceAppState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    stop: bool = False
    cameras: dict[str, CameraState] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    foot_source: str = "center"
    confidence: float = 0.42
    device: str = "0"
    quality: str = "main"
    model_size: str = "n"
    source_revision: int = 0
    model_revision: int = 0
    sales_count: int = 0
    selected_store_id: str = "store_1"
    stores: list[dict[str, Any]] = field(default_factory=list)
    config_path: Path = Path("outputs/config/entrance_geometry.json")


def geometry_to_payload(geometry: EntranceGeometry) -> dict[str, Any]:
    return {
        "camera_id": geometry.camera_id,
        "roi": list(geometry.roi),
        "line": list(geometry.line),
        "direction_axis": geometry.direction_axis,
        "enter_direction": geometry.enter_direction,
        "min_box_height_ratio": geometry.min_box_height_ratio,
        "min_box_area_ratio": geometry.min_box_area_ratio,
        "reflection_zone": None if geometry.reflection_zone is None else list(geometry.reflection_zone),
    }


def geometry_from_payload(camera_id: str, payload: dict[str, Any], fallback: EntranceGeometry) -> EntranceGeometry:
    return EntranceGeometry(
        camera_id=camera_id,
        roi=tuple(float(v) for v in payload.get("roi", fallback.roi)),
        line=tuple(float(v) for v in payload.get("line", fallback.line)),
        direction_axis=str(payload.get("direction_axis", fallback.direction_axis)),
        enter_direction=int(payload.get("enter_direction", fallback.enter_direction)),
        min_box_height_ratio=float(payload.get("min_box_height_ratio", fallback.min_box_height_ratio)),
        min_box_area_ratio=float(payload.get("min_box_area_ratio", fallback.min_box_area_ratio)),
        reflection_zone=(
            tuple(float(v) for v in payload["reflection_zone"])
            if payload.get("reflection_zone") is not None
            else None
        ),
    )


def load_config(
    path: Path,
    camera_ids: list[str],
    default_foot_source: str,
    default_confidence: float,
    default_quality: str,
    default_model_size: str,
) -> tuple[dict[str, EntranceGeometry], set[str], str, float, str, str, list[dict[str, Any]], str, int]:
    geometries = {camera_id: DEFAULT_GEOMETRIES[camera_id] for camera_id in camera_ids if camera_id in DEFAULT_GEOMETRIES}
    calibrated: set[str] = set()
    foot_source = default_foot_source
    confidence = default_confidence
    quality = default_quality
    model_size = default_model_size
    stores = [
        {
            "store_id": "store_1",
            "name": "Main Store",
            "location": "",
            "manager": "",
            "camera_id": "cam_501",
        }
    ]
    selected_store_id = "store_1"
    sales_count = 0
    if not path.exists():
        return geometries, calibrated, foot_source, confidence, quality, model_size, stores, selected_store_id, sales_count
    payload = json.loads(path.read_text(encoding="utf-8"))
    foot_source = str(payload.get("foot_source", foot_source))
    if payload.get("mode") != CONFIG_MODE and camera_ids == ["cam_501"] and default_foot_source == "center":
        foot_source = "center"
    confidence = float(payload.get("confidence", confidence))
    quality = str(payload.get("quality", quality))
    model_size = str(payload.get("model_size", model_size))
    if model_size not in {"n", "s", "ov", "x"}:
        model_size = default_model_size
    stores = list(payload.get("stores") or stores)
    selected_store_id = str(payload.get("selected_store_id", selected_store_id))
    sales_count = int(payload.get("sales_count", sales_count) or 0)
    saved = payload.get("geometries", {})
    for camera_id in camera_ids:
        fallback = geometries.get(camera_id)
        if fallback is None:
            continue
        if camera_id in saved:
            geometries[camera_id] = geometry_from_payload(camera_id, saved[camera_id], fallback)
            calibrated.add(camera_id)
    return geometries, calibrated, foot_source, confidence, quality, model_size, stores, selected_store_id, sales_count


def save_config(state: EntranceAppState) -> None:
    payload = {
        "mode": CONFIG_MODE,
        "foot_source": state.foot_source,
        "confidence": state.confidence,
        "quality": state.quality,
        "model_size": state.model_size,
        "sales_count": state.sales_count,
        "selected_store_id": state.selected_store_id,
        "stores": state.stores,
        "geometries": {
            camera_id: geometry_to_payload(camera_state.geometry)
            for camera_id, camera_state in sorted(state.cameras.items())
            if camera_state.calibrated
        },
    }
    state.config_path.parent.mkdir(parents=True, exist_ok=True)
    state.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def selected_store(state: EntranceAppState, camera_id: str) -> dict[str, Any]:
    stores = state.stores or []
    for store in stores:
        if str(store.get("store_id", "")) == state.selected_store_id:
            return store
    for store in stores:
        if str(store.get("camera_id", "")) == camera_id:
            return store
    return {
        "store_id": state.selected_store_id or "store_1",
        "name": state.selected_store_id or "Store",
        "camera_id": camera_id,
    }


def ensure_csv_header(path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as file:
            csv.DictWriter(file, fieldnames=fieldnames).writeheader()


def append_central_entry(path: Path, row: dict[str, Any]) -> None:
    fieldnames = ["store_id", "store_name", "date", "time", "number"]
    ensure_csv_header(path, fieldnames)
    with path.open("a", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=fieldnames).writerow(row)


def upsert_daily_entry(path: Path, row: dict[str, Any]) -> None:
    fieldnames = ["store_id", "store_name", "date", "number"]
    ensure_csv_header(path, fieldnames)
    rows: list[dict[str, Any]] = []
    with path.open("r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    key = (str(row["store_id"]), str(row["date"]))
    updated = False
    for existing in rows:
        if (str(existing.get("store_id", "")), str(existing.get("date", ""))) == key:
            existing.update(row)
            updated = True
            break
    if not updated:
        rows.append(row)
    rows.sort(key=lambda item: (str(item.get("store_id", "")), str(item.get("date", ""))))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


HEALTH_FIELDNAMES = [
    "row_type",
    "store_id",
    "store_name",
    "pc_name",
    "date",
    "time",
    "reported_at",
    "status",
    "message",
    "app_running",
    "cameras_total",
    "cameras_running",
    "camera_errors",
    "avg_fps",
    "min_fps",
    "cpu_percent",
    "ram_percent",
    "app_ram_mb",
    "entries_total",
    "exits_total",
    "events_seen",
    "entries_csv_modified",
    "samples",
    "healthy_samples",
    "warning_samples",
    "critical_samples",
    "worst_status",
    "max_cpu_percent",
    "min_observed_fps",
    "last_message",
]


def _health_now() -> tuple[datetime, str, str, str]:
    now = datetime.now()
    return now, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), now.isoformat(timespec="seconds")


def _parse_report_time(row: dict[str, str]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(row.get("reported_at", "")))
    except ValueError:
        return None


def _status_rank(status: str) -> int:
    return {"healthy": 0, "starting": 0, "warning": 1, "critical": 2}.get(status, 1)


def build_health_row(state: EntranceAppState, args: argparse.Namespace, proc: psutil.Process) -> dict[str, str]:
    now, date_text, time_text, reported_at = _health_now()
    with state.lock:
        cameras = list(state.cameras.values())
        store = selected_store(state, cameras[0].camera_id if cameras else "")
        events_seen = len(state.events)
    camera_rows = []
    for camera in cameras:
        with camera.lock:
            camera_rows.append(
                {
                    "camera_id": camera.camera_id,
                    "running": bool(camera.running),
                    "error": str(camera.error or ""),
                    "fps": float(camera.fps or 0.0),
                    "entries": int(camera.entry_count),
                    "exits": int(camera.exit_count),
                }
            )
    fps_values = [row["fps"] for row in camera_rows if row["fps"] > 0]
    avg_fps = sum(fps_values) / len(fps_values) if fps_values else 0.0
    min_fps = min(fps_values) if fps_values else 0.0
    cameras_total = len(camera_rows)
    cameras_running = sum(1 for row in camera_rows if row["running"] and not row["error"])
    camera_errors = [f"{row['camera_id']}:{row['error'] or 'not_running'}" for row in camera_rows if row["error"] or not row["running"]]
    cpu_percent = psutil.cpu_percent(None)
    ram_percent = psutil.virtual_memory().percent
    app_ram_mb = proc.memory_info().rss / (1024 * 1024)
    status = "healthy"
    messages: list[str] = []
    if cameras_total == 0 or cameras_running < cameras_total:
        status = "critical"
        messages.append("camera offline/error")
    if cameras_total and min_fps < float(args.health_min_fps):
        status = "critical" if min_fps <= 0 else max(status, "warning", key=_status_rank)
        messages.append(f"low fps {min_fps:.1f}")
    if cpu_percent >= float(args.health_cpu_critical_percent):
        status = "critical"
        messages.append(f"cpu {cpu_percent:.0f}%")
    elif cpu_percent >= float(args.health_cpu_warning_percent):
        status = max(status, "warning", key=_status_rank)
        messages.append(f"cpu {cpu_percent:.0f}%")
    entries_csv_path = resolve_project_path(args.central_entries_csv)
    csv_mtime = ""
    if entries_csv_path.exists():
        csv_mtime = datetime.fromtimestamp(entries_csv_path.stat().st_mtime).isoformat(timespec="seconds")
    return {
        "row_type": "recent",
        "store_id": str(store.get("store_id") or "store_1"),
        "store_name": str(store.get("name") or store.get("store_id") or "Store"),
        "pc_name": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "",
        "date": date_text,
        "time": time_text,
        "reported_at": reported_at,
        "status": status,
        "message": "; ".join(messages) if messages else "ok",
        "app_running": "1",
        "cameras_total": str(cameras_total),
        "cameras_running": str(cameras_running),
        "camera_errors": " | ".join(camera_errors),
        "avg_fps": f"{avg_fps:.2f}",
        "min_fps": f"{min_fps:.2f}",
        "cpu_percent": f"{cpu_percent:.1f}",
        "ram_percent": f"{ram_percent:.1f}",
        "app_ram_mb": f"{app_ram_mb:.0f}",
        "entries_total": str(sum(row["entries"] for row in camera_rows)),
        "exits_total": str(sum(row["exits"] for row in camera_rows)),
        "events_seen": str(events_seen),
        "entries_csv_modified": csv_mtime,
        "samples": "",
        "healthy_samples": "",
        "warning_samples": "",
        "critical_samples": "",
        "worst_status": "",
        "max_cpu_percent": "",
        "min_observed_fps": "",
        "last_message": "",
    }


def update_daily_health(existing: dict[str, str] | None, current: dict[str, str]) -> dict[str, str]:
    samples = int((existing or {}).get("samples") or 0) + 1
    healthy = int((existing or {}).get("healthy_samples") or 0) + (1 if current["status"] == "healthy" else 0)
    warning = int((existing or {}).get("warning_samples") or 0) + (1 if current["status"] == "warning" else 0)
    critical = int((existing or {}).get("critical_samples") or 0) + (1 if current["status"] == "critical" else 0)
    previous_worst = (existing or {}).get("worst_status") or "healthy"
    worst = max(previous_worst, current["status"], key=_status_rank)
    max_cpu = max(float((existing or {}).get("max_cpu_percent") or 0.0), float(current["cpu_percent"] or 0.0))
    old_min_fps = float((existing or {}).get("min_observed_fps") or current["min_fps"] or 0.0)
    min_fps = min(old_min_fps, float(current["min_fps"] or 0.0))
    row = {name: "" for name in HEALTH_FIELDNAMES}
    row.update(
        {
            "row_type": "daily",
            "store_id": current["store_id"],
            "store_name": current["store_name"],
            "pc_name": current["pc_name"],
            "date": current["date"],
            "time": current["time"],
            "reported_at": current["reported_at"],
            "status": "healthy" if critical == 0 and warning == 0 else ("critical" if critical else "warning"),
            "message": f"{healthy}/{samples} healthy reports",
            "samples": str(samples),
            "healthy_samples": str(healthy),
            "warning_samples": str(warning),
            "critical_samples": str(critical),
            "worst_status": worst,
            "max_cpu_percent": f"{max_cpu:.1f}",
            "min_observed_fps": f"{min_fps:.2f}",
            "last_message": current["message"],
        }
    )
    return row


def write_health_report(state: EntranceAppState, args: argparse.Namespace, proc: psutil.Process, current: dict[str, str] | None = None) -> None:
    path = resolve_project_path(args.health_csv)
    ensure_csv_header(path, HEALTH_FIELDNAMES)
    current = current or build_health_row(state, args, proc)
    now = datetime.now()
    healthy_cutoff = now - timedelta(minutes=float(args.health_keep_healthy_minutes))
    issue_cutoff = now - timedelta(days=float(args.health_keep_issue_days))
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            row = {name: str(row.get(name, "")) for name in HEALTH_FIELDNAMES}
            row_time = _parse_report_time(row)
            if row["row_type"] == "recent":
                if row_time is not None and row_time >= healthy_cutoff:
                    rows.append(row)
            elif row["row_type"] == "issue":
                if row_time is None or row_time >= issue_cutoff:
                    rows.append(row)
            elif row["row_type"] == "daily":
                if not (row["store_id"] == current["store_id"] and row["date"] == current["date"]):
                    rows.append(row)
    rows.append(current)
    if current["status"] not in {"healthy", "starting"}:
        issue = dict(current)
        issue["row_type"] = "issue"
        rows.append(issue)
    existing_daily = None
    for row in rows:
        if row["row_type"] == "daily" and row["store_id"] == current["store_id"] and row["date"] == current["date"]:
            existing_daily = row
            break
    rows = [row for row in rows if not (row["row_type"] == "daily" and row["store_id"] == current["store_id"] and row["date"] == current["date"])]
    rows.append(update_daily_health(existing_daily, current))
    rows.sort(key=lambda row: (row.get("store_id", ""), row.get("date", ""), row.get("row_type", ""), row.get("reported_at", "")))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=HEALTH_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def health_monitor_worker(state: EntranceAppState, args: argparse.Namespace, csv_lock: threading.Lock) -> None:
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(None)
    startup_time = time.monotonic()
    unhealthy_since: float | None = None
    while not state.stop:
        current = build_health_row(state, args, proc)
        now = time.monotonic()
        if current["status"] == "healthy":
            unhealthy_since = None
        else:
            if unhealthy_since is None:
                unhealthy_since = now
            in_startup_grace = now - startup_time < float(args.health_startup_grace_seconds)
            below_issue_delay = now - unhealthy_since < float(args.health_issue_delay_seconds)
            if in_startup_grace or below_issue_delay:
                current["status"] = "starting"
                current["message"] = f"startup grace: {current['message']}"
        with csv_lock:
            write_health_report(state, args, proc, current)
        time.sleep(max(5.0, float(args.health_interval_seconds)))


def write_store_entry_exports(state: EntranceAppState, camera_id: str, entry_count: int, args: argparse.Namespace) -> None:
    now = time.localtime()
    with state.lock:
        store = selected_store(state, camera_id)
    store_id = str(store.get("store_id") or "store_1")
    store_name = str(store.get("name") or store_id)
    central_row = {
        "store_id": store_id,
        "store_name": store_name,
        "date": time.strftime("%Y-%m-%d", now),
        "time": time.strftime("%H:%M:%S", now),
        "number": 1,
    }
    append_central_entry(resolve_project_path(args.central_entries_csv), central_row)
    upsert_daily_entry(
        resolve_project_path(args.daily_entries_csv),
        {
            "store_id": store_id,
            "store_name": store_name,
            "date": central_row["date"],
            "number": int(entry_count),
        },
    )


def record_crossing_event(
    state: EntranceAppState,
    camera: CameraState,
    direction: str,
    tracker_id: int,
    history: TrackHistory,
    foot_source: str,
    elapsed: float,
    csv_lock: threading.Lock,
    events_writer: csv.DictWriter,
    events_file: Any,
    args: argparse.Namespace,
) -> None:
    with state.lock:
        if direction == "entry":
            history.counted = True
            camera.entry_count += 1
        else:
            if camera.exit_count >= camera.entry_count:
                history.exit_counted = True
                return
            history.exit_counted = True
            camera.exit_count += 1
        count = camera.entry_count if direction == "entry" else camera.exit_count
        event = {
            "event_id": f"{camera.camera_id}-{direction}-{count:06d}",
            "direction": direction,
            "time_seconds": round(elapsed, 3),
            "camera_id": camera.camera_id,
            "tracker_id": int(tracker_id),
            "confidence": round(history.max_confidence, 4),
            "first_frame": history.first_frame,
            "last_frame": history.last_frame,
            "foot_source": foot_source,
            "entry_count_camera": camera.entry_count,
            "exit_count_camera": camera.exit_count,
        }
        state.events.append(event)
        del state.events[:-200]
    with csv_lock:
        events_writer.writerow(event)
        events_file.flush()
    if direction == "entry":
        with csv_lock:
            write_store_entry_exports(state, camera.camera_id, camera.entry_count, args)
    if args.print_events:
        label = direction.upper()
        print(
            f"[{label}] camera={camera.camera_id} entries={camera.entry_count} exits={camera.exit_count} track={tracker_id}",
            flush=True,
        )


def side_of_segment(point: tuple[float, float], geometry: EntranceGeometry, frame_shape: tuple[int, int], deadzone_px: float = 12.0) -> int:
    x1, y1, x2, y2 = denorm_line(geometry.line, frame_shape)
    px, py = point
    value = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    if abs(value) <= max(0.0, float(deadzone_px)):
        return 0
    return 1 if value > 0 else -1


def point_near_segment(point: tuple[float, float], geometry: EntranceGeometry, frame_shape: tuple[int, int], margin_px: float) -> bool:
    x1, y1, x2, y2 = denorm_line(geometry.line, frame_shape)
    px, py = point
    min_x, max_x = sorted((x1, x2))
    min_y, max_y = sorted((y1, y2))
    margin = max(0.0, float(margin_px))
    return min_x - margin <= px <= max_x + margin and min_y - margin <= py <= max_y + margin


def detection_usable(
    box: list[float],
    foot: tuple[float, float],
    confidence: float,
    frame_shape: tuple[int, int],
    geometry: EntranceGeometry,
    args: argparse.Namespace,
) -> bool:
    h, w = frame_shape
    width = max(1.0, box[2] - box[0])
    height = max(1.0, box[3] - box[1])
    if confidence < args.conf:
        return False
    if height < h * geometry.min_box_height_ratio:
        return False
    if width * height < w * h * geometry.min_box_area_ratio:
        return False
    if not point_inside_box(foot, denorm_box(geometry.roi, frame_shape)):
        return False
    if not point_near_segment(foot, geometry, frame_shape, args.line_margin_px):
        return False
    if geometry.reflection_zone is not None:
        reflection_box = denorm_box(geometry.reflection_zone, frame_shape)
        if box_overlap_fraction(box, reflection_box) >= args.reflection_overlap_reject:
            return False
    return True


def track_travel_px(history: TrackHistory) -> float:
    if history.first_point is None or history.last_point is None:
        return 0.0
    dx = float(history.last_point[0]) - float(history.first_point[0])
    dy = float(history.last_point[1]) - float(history.first_point[1])
    return float((dx * dx + dy * dy) ** 0.5)


def track_has_enough_motion(history: TrackHistory, args: argparse.Namespace) -> bool:
    if history.last_time - history.first_time < float(args.min_track_seconds):
        return False
    if track_travel_px(history) < float(args.min_crossing_travel_px):
        return False
    return True


def crossed_entering(history: TrackHistory, geometry: EntranceGeometry, args: argparse.Namespace) -> bool:
    if history.counted or history.frames_seen < args.min_track_frames:
        return False
    if history.outside_hits < args.min_outside_frames or history.inside_hits < args.min_inside_frames:
        return False
    if history.first_side is None or history.last_side is None:
        return False
    if not track_has_enough_motion(history, args):
        return False
    return history.transition_from_side == -geometry.enter_direction and history.transition_to_side == geometry.enter_direction


def crossed_exiting(history: TrackHistory, geometry: EntranceGeometry, args: argparse.Namespace) -> bool:
    if history.exit_counted or history.frames_seen < args.min_track_frames:
        return False
    if history.outside_hits < args.min_outside_frames or history.inside_hits < args.min_inside_frames:
        return False
    if history.first_side is None or history.last_side is None:
        return False
    if not track_has_enough_motion(history, args):
        return False
    return history.transition_from_side == geometry.enter_direction and history.transition_to_side == -geometry.enter_direction


def update_track(
    camera: CameraState,
    tracker_id: int,
    box: list[float],
    foot: tuple[float, float],
    confidence: float,
    elapsed: float,
    args: argparse.Namespace,
) -> TrackHistory:
    frame_shape = camera.latest_shape or (1, 1)
    side = side_of_segment(foot, camera.geometry, frame_shape, args.line_deadzone_px)
    history = camera.tracks.get(tracker_id)
    if history is None:
        history = TrackHistory(
            tracker_id=tracker_id,
            first_frame=camera.frame_index,
            last_frame=camera.frame_index,
            first_time=elapsed,
            last_time=elapsed,
        )
        camera.tracks[tracker_id] = history
    history.frames_seen += 1
    history.last_frame = camera.frame_index
    history.last_time = elapsed
    history.last_point = foot
    history.last_box = box
    history.max_confidence = max(history.max_confidence, confidence)
    if history.first_point is None:
        history.first_point = foot
    if side != 0:
        if history.first_side is None:
            history.first_side = side
        if history.last_side is not None and side != history.last_side:
            history.previous_side = history.last_side
            history.transition_from_side = history.last_side
            history.transition_to_side = side
        history.last_side = side
        if side == camera.geometry.enter_direction:
            history.inside_hits += 1
        else:
            history.outside_hits += 1
    return history


def prune_tracks(camera: CameraState, max_missing_frames: int) -> None:
    cutoff = camera.frame_index - max_missing_frames
    for tracker_id in list(camera.tracks):
        if camera.tracks[tracker_id].last_frame < cutoff:
            del camera.tracks[tracker_id]


def foot_from_pose(box: list[float], keypoints_xy: Any | None, keypoints_conf: Any | None, foot_source: str, min_conf: float) -> tuple[tuple[float, float], str]:
    if foot_source == "center":
        return ((box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5), "center"
    if foot_source == "pose" and keypoints_xy is not None:
        feet: list[tuple[float, float]] = []
        for idx in (15, 16):
            if idx >= len(keypoints_xy):
                continue
            conf = float(keypoints_conf[idx]) if keypoints_conf is not None else 1.0
            if conf >= min_conf:
                feet.append((float(keypoints_xy[idx][0]), float(keypoints_xy[idx][1])))
        if feet:
            return (sum(p[0] for p in feet) / len(feet), sum(p[1] for p in feet) / len(feet)), "pose"
    return ((box[0] + box[2]) * 0.5, box[3]), "box"


def box_iou(a: list[float], b: list[float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def nms_boxes(detections: list[dict[str, Any]], iou_threshold: float, limit: int) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for det in sorted(detections, key=lambda item: float(item["confidence"]), reverse=True):
        if all(box_iou(det["box"], existing["box"]) < iou_threshold for existing in kept):
            kept.append(det)
            if len(kept) >= limit:
                break
    return kept


def sigmoid_if_logits(values: np.ndarray) -> np.ndarray:
    if values.size and (float(np.nanmin(values)) < 0.0 or float(np.nanmax(values)) > 1.0):
        return 1.0 / (1.0 + np.exp(-values))
    return values


class YOLOXOpenVINODetector:
    def __init__(self, model_path: Path, device: str, input_size: int = YOLOX_MODEL_SIZE) -> None:
        from openvino import Core

        xml_path = model_path / "yolox_tiny.xml" if model_path.is_dir() else model_path
        if not xml_path.exists():
            raise FileNotFoundError(
                f"YOLOX-Tiny OpenVINO model not found at {xml_path}. "
                "Run DOWNLOAD_YOLOX_TINY_OPENVINO.bat first."
            )
        self.input_size = input_size
        self.core = Core()
        self.compiled = self.core.compile_model(str(xml_path), device)
        self.input_name = self.compiled.inputs[0]
        self.output_names = list(self.compiled.outputs)
        self.backend_name = "OpenVINO decoded outputs"
        self.next_track_id = 1
        self.tracks: dict[int, dict[str, Any]] = {}
        self.grid, self.strides = self._make_decode_grid(input_size)

    @staticmethod
    def _make_decode_grid(input_size: int) -> tuple[np.ndarray, np.ndarray]:
        grids: list[np.ndarray] = []
        strides: list[np.ndarray] = []
        for stride in (8, 16, 32):
            grid_size = input_size // stride
            gy, gx = np.mgrid[:grid_size, :grid_size]
            grids.append(np.stack((gx, gy), axis=-1).reshape(-1, 2))
            strides.append(np.full((grid_size * grid_size, 1), stride, dtype=np.float32))
        return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)

    def _preprocess(self, frame: Any) -> tuple[np.ndarray, float]:
        h, w = frame.shape[:2]
        ratio = min(self.input_size / float(h), self.input_size / float(w))
        resized = cv2.resize(frame, (int(w * ratio), int(h * ratio)), interpolation=cv2.INTER_LINEAR)
        padded = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        blob = padded.astype(np.float32) / 255.0
        blob -= np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
        blob /= np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
        blob = blob.transpose(2, 0, 1)[None]
        return blob, ratio

    def _assign_tracks(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        matched_tracks: set[int] = set()
        for det in detections:
            best_id = 0
            best_iou = 0.0
            for track_id, track in self.tracks.items():
                if track_id in matched_tracks:
                    continue
                iou = box_iou(det["box"], track["box"])
                if iou > best_iou:
                    best_iou = iou
                    best_id = track_id
            if best_id and best_iou >= 0.30:
                det["tracker_id"] = best_id
                matched_tracks.add(best_id)
            else:
                det["tracker_id"] = self.next_track_id
                self.next_track_id += 1
        next_tracks: dict[int, dict[str, Any]] = {}
        for det in detections:
            next_tracks[int(det["tracker_id"])] = {"box": det["box"], "missed": 0}
        for track_id, track in self.tracks.items():
            if track_id not in matched_tracks:
                missed = int(track.get("missed", 0)) + 1
                if missed <= 20:
                    next_tracks.setdefault(track_id, {"box": track["box"], "missed": missed})
        self.tracks = next_tracks
        return detections

    def track_people(self, frame: Any, conf: float, iou: float, max_det: int) -> list[dict[str, Any]]:
        blob, ratio = self._preprocess(frame)
        outputs = self.compiled({self.input_name: blob})
        predictions: np.ndarray | None = None
        labels: np.ndarray | None = None
        for output_name in self.output_names:
            output = np.asarray(outputs[output_name])
            if output.ndim == 3 and output.shape[-1] >= 5:
                predictions = output[0]
            elif output.ndim == 2:
                labels = output[0]
        if predictions is None:
            raise RuntimeError("YOLOX model did not return a detection tensor.")

        h, w = frame.shape[:2]
        detections: list[dict[str, Any]] = []
        if predictions.shape[1] == 5 and labels is not None:
            scores = predictions[:, 4]
            candidates = np.where((labels.astype(np.int64) == YOLOX_PERSON_CLASS) & (scores >= conf))[0]
            for idx in candidates:
                x1, y1, x2, y2 = [float(v) / ratio for v in predictions[idx, :4]]
                x1 = max(0.0, min(float(w - 1), x1))
                y1 = max(0.0, min(float(h - 1), y1))
                x2 = max(0.0, min(float(w - 1), x2))
                y2 = max(0.0, min(float(h - 1), y2))
                if x2 <= x1 or y2 <= y1:
                    continue
                detections.append({"box": [x1, y1, x2, y2], "confidence": float(scores[idx])})
            return self._assign_tracks(nms_boxes(detections, iou, max_det))

        if predictions.shape[0] != self.grid.shape[0]:
            raise RuntimeError(f"Unexpected YOLOX output shape {predictions.shape}; expected {self.grid.shape[0]} anchors.")
        if predictions.shape[1] < 6:
            raise RuntimeError(f"Unsupported YOLOX output shape {predictions.shape}.")
        raw_boxes = predictions[:, :4]
        centers = (raw_boxes[:, :2] + self.grid) * self.strides
        sizes = np.exp(np.clip(raw_boxes[:, 2:4], -16.0, 16.0)) * self.strides
        objectness = sigmoid_if_logits(predictions[:, 4])
        class_scores = sigmoid_if_logits(predictions[:, 5:])
        if class_scores.shape[1] <= YOLOX_PERSON_CLASS:
            return []
        scores = objectness * class_scores[:, YOLOX_PERSON_CLASS]
        candidates = np.where(scores >= conf)[0]
        for idx in candidates:
            cx, cy = [float(v) for v in centers[idx]]
            bw, bh = [float(v) for v in sizes[idx]]
            x1 = max(0.0, (cx - bw * 0.5) / ratio)
            y1 = max(0.0, (cy - bh * 0.5) / ratio)
            x2 = min(float(w - 1), (cx + bw * 0.5) / ratio)
            y2 = min(float(h - 1), (cy + bh * 0.5) / ratio)
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append({"box": [x1, y1, x2, y2], "confidence": float(scores[idx])})
        return self._assign_tracks(nms_boxes(detections, iou, max_det))


def draw_overlay(frame: Any, camera: CameraState, people: list[dict[str, Any]], display_fps: float, foot_source: str) -> None:
    if camera.calibrated:
        roi = denorm_box(camera.geometry.roi, frame.shape[:2])
        line = denorm_line(camera.geometry.line, frame.shape[:2])
        cv2.rectangle(frame, roi[:2], roi[2:], (255, 170, 70), 2, cv2.LINE_AA)
        cv2.line(frame, line[:2], line[2:], (0, 220, 210), 3, cv2.LINE_AA)
        if camera.geometry.reflection_zone is not None:
            glass = denorm_box(camera.geometry.reflection_zone, frame.shape[:2])
            cv2.rectangle(frame, glass[:2], glass[2:], (80, 80, 230), 1, cv2.LINE_AA)
    for person in people:
        box = [int(round(v)) for v in person["box"]]
        color = (55, 220, 120) if person["usable"] else (90, 90, 100)
        cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), color, 2 if person["usable"] else 1, cv2.LINE_AA)
        foot = person["foot"]
        cv2.circle(frame, (int(foot[0]), int(foot[1])), 5, (0, 220, 210), -1, cv2.LINE_AA)
        draw_label(frame, f"id:{person['tracker_id']} {person['confidence']:.2f}", (box[0], max(18, box[1] - 7)), color)
    draw_label(
        frame,
        f"{camera.camera_id} in:{camera.entry_count} out:{camera.exit_count} {foot_source} fps:{display_fps:.1f}" if camera.calibrated else f"{camera.camera_id} uncalibrated fps:{display_fps:.1f}",
        (12, 28),
        (238, 242, 248),
    )


class LatestFrameCapture:
    def __init__(self, source: Any, args: argparse.Namespace) -> None:
        self.source = source
        self.args = args
        self.lock = threading.Lock()
        self.latest_frame: Any | None = None
        self.latest_seq = 0
        self.fps = 25.0
        self.error = ""
        self.running = False
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.running = True
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2.0)

    def read_latest(self, last_seq: int) -> tuple[int, Any | None, float, str]:
        with self.lock:
            if self.latest_seq == last_seq or self.latest_frame is None:
                return last_seq, None, self.fps, self.error
            return self.latest_seq, self.latest_frame.copy(), self.fps, self.error

    def _run(self) -> None:
        cap: cv2.VideoCapture | None = None
        failures = 0
        open_failures = 0
        redacted_source = redact_url_credentials(str(self.source))
        try:
            while not self.stop_event.is_set():
                if cap is None:
                    print(f"[RTSP] opening source={redacted_source}", flush=True)
                    cap = open_capture(
                        self.source,
                        rtsp_transport=self.args.rtsp_transport,
                        rtsp_max_delay_ms=self.args.rtsp_max_delay_ms,
                        rtsp_read_timeout_ms=self.args.rtsp_read_timeout_ms,
                        rtsp_open_timeout_ms=self.args.rtsp_open_timeout_ms,
                        capture_buffer_size=self.args.capture_buffer_size,
                    )
                    if not cap.isOpened():
                        open_failures += 1
                        wait_seconds = min(
                            float(self.args.rtsp_retry_max_seconds),
                            float(self.args.rtsp_retry_base_seconds) * (2 ** min(open_failures - 1, 4)),
                        )
                        with self.lock:
                            self.error = f"Could not open source; retrying in {wait_seconds:.0f}s"
                        print(
                            f"[RTSP] open failed source={redacted_source} "
                            f"attempt={open_failures} retry_in={wait_seconds:.0f}s",
                            flush=True,
                        )
                        cap.release()
                        cap = None
                        self.stop_event.wait(wait_seconds)
                        continue
                    with self.lock:
                        self.fps = sane_fps(cap.get(cv2.CAP_PROP_FPS))
                        self.error = ""
                    if open_failures:
                        print(f"[RTSP] opened source={redacted_source}", flush=True)
                    open_failures = 0
                    failures = 0
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if self.args.loop_video:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    if failures >= self.args.max_read_failures:
                        with self.lock:
                            self.error = "RTSP read failures; reconnecting"
                        print(f"[RTSP] read failures; reconnecting source={redacted_source}", flush=True)
                        cap.release()
                        cap = None
                        failures = 0
                        self.stop_event.wait(float(self.args.rtsp_retry_base_seconds))
                    else:
                        time.sleep(0.005)
                    continue
                failures = 0
                with self.lock:
                    self.latest_frame = frame
                    self.latest_seq += 1
                    self.error = ""
        finally:
            if cap is not None:
                cap.release()
            self.running = False


def redact_url_credentials(value: str) -> str:
    if "://" not in value:
        return value
    scheme, rest = value.split("://", 1)
    if "@" not in rest:
        return value
    return f"{scheme}://***:***@{rest.rsplit('@', 1)[1]}"


def apply_camera_credentials(source: Any, camera: dict[str, Any] | None) -> Any:
    if isinstance(source, int) or not camera:
        return source
    username = camera.get("username", camera.get("rtsp_username", ""))
    password = camera.get("password", camera.get("rtsp_password", ""))
    if username == "" and password == "":
        return source
    text = str(source)
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc or parts.hostname is None:
        return source
    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    auth = quote(str(username), safe="")
    if password != "":
        auth = f"{auth}:{quote(str(password), safe='')}"
    return urlunsplit((parts.scheme, f"{auth}@{host}{port}", parts.path, parts.query, parts.fragment))


def camera_worker(
    camera: CameraState,
    source_for_quality: Any,
    state: EntranceAppState,
    args: argparse.Namespace,
    events_writer: csv.DictWriter,
    events_file: Any,
    tracks_writer: csv.DictWriter,
    tracks_file: Any,
    csv_lock: threading.Lock,
) -> None:
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(None)
    profile_totals = {
        "read": 0.0,
        "resize": 0.0,
        "infer": 0.0,
        "post": 0.0,
        "encode": 0.0,
    }
    profile_frames = 0
    last_profile = time.monotonic()
    active_model_source = ""
    model: Any | None = None
    active_revision = -1
    active_quality = ""
    grabber: LatestFrameCapture | None = None
    last_grabber_seq = 0
    last_tick = time.monotonic()
    last_frame = 0
    last_terminal = 0.0
    display_fps = 0.0
    start = time.monotonic()
    with camera.lock:
        camera.running = True
    try:
        while not state.stop:
            with state.lock:
                desired_quality = state.quality
                desired_revision = state.source_revision
                desired_foot_source = state.foot_source
                desired_model_size = state.model_size
                desired_model_revision = state.model_revision
            model_source = f"{desired_foot_source}:{desired_model_size}:{desired_model_revision}"
            if model is None or model_source != active_model_source:
                if desired_foot_source == "pose":
                    from ultralytics import YOLO

                    model_path = resolve_project_path(args.pose_model)
                    model = YOLO(str(model_path))
                elif desired_model_size == "x":
                    model_path = resolve_project_path(args.person_model_yolox_openvino)
                    model = YOLOXOpenVINODetector(model_path, args.yolox_openvino_device)
                    print(f"Loaded YOLOX-Tiny using {model.backend_name}: {model_path}", flush=True)
                elif desired_model_size == "ov":
                    from ultralytics import YOLO

                    model_path = resolve_project_path(args.person_model_openvino)
                    model = YOLO(str(model_path))
                elif desired_model_size == "s":
                    from ultralytics import YOLO

                    model_path = resolve_project_path(args.person_model_small)
                    model = YOLO(str(model_path))
                else:
                    from ultralytics import YOLO

                    model_path = resolve_project_path(args.person_model)
                    model = YOLO(str(model_path))
                active_model_source = model_source
            if grabber is None or desired_revision != active_revision or desired_quality != active_quality:
                if grabber is not None:
                    grabber.stop()
                source = source_for_quality(camera.camera_id, desired_quality)
                grabber = LatestFrameCapture(source, args)
                grabber.start()
                with camera.lock:
                    camera.running = True
                    camera.error = "Waiting for first RTSP frame"
                active_quality = desired_quality
                active_revision = desired_revision
                last_grabber_seq = 0
            t_read = time.perf_counter()
            assert grabber is not None
            seq, frame, fps, capture_error = grabber.read_latest(last_grabber_seq)
            read_ms = (time.perf_counter() - t_read) * 1000.0
            if frame is None:
                with camera.lock:
                    camera.fps = fps
                    camera.error = capture_error
                    camera.running = not bool(capture_error)
                time.sleep(0.005)
                continue
            last_grabber_seq = seq
            t_resize = time.perf_counter()
            if args.frame_width > 0 and frame.shape[1] > args.frame_width:
                scale = args.frame_width / float(frame.shape[1])
                frame = cv2.resize(
                    frame,
                    (args.frame_width, max(1, int(round(frame.shape[0] * scale)))),
                    interpolation=cv2.INTER_AREA,
                )
            resize_ms = (time.perf_counter() - t_resize) * 1000.0
            elapsed = time.monotonic() - start
            with camera.lock:
                camera.frame_index += 1
                camera.latest_shape = frame.shape[:2]
                camera.geometry = state.cameras[camera.camera_id].geometry
                calibrated = state.cameras[camera.camera_id].calibrated
                camera.entry_count = state.cameras[camera.camera_id].entry_count
                camera.exit_count = state.cameras[camera.camera_id].exit_count
                frame_index = camera.frame_index
                geometry = camera.geometry
                confidence = state.confidence
                foot_source = desired_foot_source
            if args.process_every_n > 1 and frame_index % args.process_every_n != 0:
                continue
            args.conf = confidence
            t_infer = time.perf_counter()
            use_yolox = desired_foot_source != "pose" and desired_model_size == "x" and isinstance(model, YOLOXOpenVINODetector)
            if use_yolox:
                yolox_detections = model.track_people(frame, confidence, args.iou, args.max_det)
                result_list = []
            else:
                yolox_detections = []
                result_list = model.track(
                    frame,
                    persist=True,
                    tracker=args.tracker,
                    classes=[0] if foot_source != "pose" else None,
                    conf=confidence,
                    iou=args.iou,
                    imgsz=args.imgsz,
                    device=args.device,
                    half=args.half and args.device != "cpu",
                    max_det=args.max_det,
                    verbose=False,
                )
            infer_ms = (time.perf_counter() - t_infer) * 1000.0
            t_post = time.perf_counter()
            people: list[dict[str, Any]] = []
            if use_yolox:
                for det in yolox_detections:
                    box = [float(v) for v in det["box"]]
                    tracker_id = int(det["tracker_id"])
                    conf = float(det["confidence"])
                    foot, source_name = foot_from_pose(box, None, None, foot_source, args.ankle_conf)
                    usable = calibrated and detection_usable(box, foot, conf, frame.shape[:2], geometry, args)
                    person = {
                        "tracker_id": tracker_id,
                        "confidence": conf,
                        "box": box,
                        "foot": foot,
                        "foot_source": source_name,
                        "usable": usable,
                    }
                    people.append(person)
                    with csv_lock:
                        tracks_writer.writerow(
                            {
                                "time_seconds": f"{elapsed:.3f}",
                                "camera_id": camera.camera_id,
                                "frame_index": frame_index,
                                "tracker_id": tracker_id,
                                "confidence": f"{conf:.4f}",
                                "usable": int(usable),
                                "foot_source": source_name,
                                "x1": f"{box[0]:.1f}",
                                "y1": f"{box[1]:.1f}",
                                "x2": f"{box[2]:.1f}",
                                "y2": f"{box[3]:.1f}",
                                "foot_x": f"{foot[0]:.1f}",
                                "foot_y": f"{foot[1]:.1f}",
                            }
                        )
                    if not usable:
                        continue
                    history = update_track(camera, tracker_id, box, foot, conf, elapsed, args)
                    if crossed_entering(history, geometry, args):
                        record_crossing_event(state, camera, "entry", tracker_id, history, source_name, elapsed, csv_lock, events_writer, events_file, args)
                    elif crossed_exiting(history, geometry, args):
                        record_crossing_event(state, camera, "exit", tracker_id, history, source_name, elapsed, csv_lock, events_writer, events_file, args)
            else:
                result = result_list[0] if result_list else None
                if result is not None and result.boxes is not None and result.boxes.id is not None:
                    boxes = result.boxes.xyxy.cpu().numpy()
                    ids = result.boxes.id.cpu().numpy().astype(int)
                    confs = result.boxes.conf.cpu().numpy()
                    keypoints_xy = result.keypoints.xy.cpu().numpy() if getattr(result, "keypoints", None) is not None else None
                    keypoints_conf = result.keypoints.conf.cpu().numpy() if getattr(result, "keypoints", None) is not None and result.keypoints.conf is not None else None
                    for idx, (box_arr, tracker_id, conf) in enumerate(zip(boxes, ids, confs)):
                        box = [float(v) for v in box_arr.tolist()]
                        kp_xy = keypoints_xy[idx] if keypoints_xy is not None and idx < len(keypoints_xy) else None
                        kp_conf = keypoints_conf[idx] if keypoints_conf is not None and idx < len(keypoints_conf) else None
                        foot, source_name = foot_from_pose(box, kp_xy, kp_conf, foot_source, args.ankle_conf)
                        usable = calibrated and detection_usable(box, foot, float(conf), frame.shape[:2], geometry, args)
                        person = {
                            "tracker_id": int(tracker_id),
                            "confidence": float(conf),
                            "box": box,
                            "foot": foot,
                            "foot_source": source_name,
                            "usable": usable,
                        }
                        people.append(person)
                        with csv_lock:
                            tracks_writer.writerow(
                                {
                                    "time_seconds": f"{elapsed:.3f}",
                                    "camera_id": camera.camera_id,
                                    "frame_index": frame_index,
                                    "tracker_id": int(tracker_id),
                                    "confidence": f"{float(conf):.4f}",
                                    "usable": int(usable),
                                    "foot_source": source_name,
                                    "x1": f"{box[0]:.1f}",
                                    "y1": f"{box[1]:.1f}",
                                    "x2": f"{box[2]:.1f}",
                                    "y2": f"{box[3]:.1f}",
                                    "foot_x": f"{foot[0]:.1f}",
                                    "foot_y": f"{foot[1]:.1f}",
                                }
                            )
                        if not usable:
                            continue
                        history = update_track(camera, int(tracker_id), box, foot, float(conf), elapsed, args)
                        if crossed_entering(history, geometry, args):
                            record_crossing_event(state, camera, "entry", int(tracker_id), history, source_name, elapsed, csv_lock, events_writer, events_file, args)
                        elif crossed_exiting(history, geometry, args):
                            record_crossing_event(state, camera, "exit", int(tracker_id), history, source_name, elapsed, csv_lock, events_writer, events_file, args)
            prune_tracks(camera, args.max_missing_frames)
            post_ms = (time.perf_counter() - t_post) * 1000.0
            now = time.monotonic()
            if now - last_tick >= 1.0:
                display_fps = (frame_index - last_frame) / max(1e-6, now - last_tick)
                last_frame = frame_index
                last_tick = now
                with csv_lock:
                    tracks_file.flush()
            t_encode = time.perf_counter()
            if args.no_web:
                clean_jpeg = None
                jpeg = None
            else:
                clean_jpeg = encode_jpeg(frame, args.jpeg_quality)
                draw_overlay(frame, camera, people, display_fps, foot_source)
                jpeg = encode_jpeg(frame, args.jpeg_quality)
            encode_ms = (time.perf_counter() - t_encode) * 1000.0
            with camera.lock:
                camera.latest_jpeg = jpeg
                camera.latest_clean_jpeg = clean_jpeg
                camera.recent_people = people
                camera.fps = display_fps
                camera.running = True
                camera.error = ""
            if args.profile_resources:
                profile_totals["read"] += read_ms
                profile_totals["resize"] += resize_ms
                profile_totals["infer"] += infer_ms
                profile_totals["post"] += post_ms
                profile_totals["encode"] += encode_ms
                profile_frames += 1
                if now - last_profile >= args.profile_interval and profile_frames > 0:
                    total_ms = sum(profile_totals.values())
                    if total_ms <= 0:
                        total_ms = 1e-6
                    avg = {key: value / profile_frames for key, value in profile_totals.items()}
                    pct = {key: (value / total_ms) * 100.0 for key, value in profile_totals.items()}
                    mem_mb = proc.memory_info().rss / (1024 * 1024)
                    cpu_pct = proc.cpu_percent(None)
                    print(
                        "[PROFILE] "
                        f"frames={profile_frames} fps={display_fps:.1f} cpu={cpu_pct:.0f}% ram={mem_mb:.0f}MB "
                        f"read={avg['read']:.1f}ms/{pct['read']:.0f}% "
                        f"resize={avg['resize']:.1f}ms/{pct['resize']:.0f}% "
                        f"model={avg['infer']:.1f}ms/{pct['infer']:.0f}% "
                        f"counting={avg['post']:.1f}ms/{pct['post']:.0f}% "
                        f"ui_jpeg={avg['encode']:.1f}ms/{pct['encode']:.0f}% "
                        f"detections={len(people)} usable={sum(1 for person in people if person.get('usable'))}",
                        flush=True,
                    )
                    profile_totals = {key: 0.0 for key in profile_totals}
                    profile_frames = 0
                    last_profile = now
            if args.no_web and args.terminal_interval > 0 and now - last_terminal >= args.terminal_interval:
                last_terminal = now
                usable_count = sum(1 for person in people if person.get("usable"))
                print(
                    f"[STATUS] camera={camera.camera_id} entries={camera.entry_count} exits={camera.exit_count} "
                    f"net={max(0, camera.entry_count - camera.exit_count)} detections={len(people)} "
                    f"usable={usable_count} fps={display_fps:.1f}",
                    flush=True,
                )
    except Exception as exc:
        with camera.lock:
            camera.error = str(exc)
            camera.running = False
    finally:
        if grabber is not None:
            grabber.stop()
        with camera.lock:
            camera.running = False


def write_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(state: EntranceAppState) -> type[BaseHTTPRequestHandler]:
    class EntranceHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                body = HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK.value)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/state":
                payload = {
                    "cameras": {},
                    "events": [],
                    "config": {"geometries": {}},
                    "foot_source": state.foot_source,
                    "confidence": state.confidence,
                    "device": state.device,
                    "quality": state.quality,
                    "model_size": state.model_size,
                    "sales_count": state.sales_count,
                    "selected_store_id": state.selected_store_id,
                    "stores": state.stores,
                }
                with state.lock:
                    payload["events"] = list(state.events)
                    payload["foot_source"] = state.foot_source
                    payload["confidence"] = state.confidence
                    payload["quality"] = state.quality
                    payload["model_size"] = state.model_size
                    payload["sales_count"] = state.sales_count
                    payload["selected_store_id"] = state.selected_store_id
                    payload["stores"] = list(state.stores)
                for camera_id, camera in state.cameras.items():
                    with camera.lock:
                        payload["cameras"][camera_id] = {
                            "running": camera.running,
                            "calibrated": camera.calibrated,
                            "error": camera.error,
                            "frame_index": camera.frame_index,
                            "fps": camera.fps,
                            "entry_count": camera.entry_count,
                            "exit_count": camera.exit_count,
                            "shape": list(camera.latest_shape) if camera.latest_shape else None,
                            "people": camera.recent_people,
                        }
                        if camera.calibrated:
                            payload["config"]["geometries"][camera_id] = geometry_to_payload(camera.geometry)
                write_json(self, payload)
                return
            if path == "/video.mjpg":
                query = parse_qs(urlparse(self.path).query)
                camera_id = str((query.get("camera_id") or [""])[0])
                overlay = str((query.get("overlay") or ["1"])[0]).lower() not in {"0", "false", "clean"}
                camera = state.cameras.get(camera_id)
                if camera is None:
                    self.send_error(HTTPStatus.NOT_FOUND.value)
                    return
                self.send_response(HTTPStatus.OK.value)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while not state.stop:
                    with camera.lock:
                        jpeg = camera.latest_jpeg if overlay else camera.latest_clean_jpeg
                        error = camera.error
                    if jpeg is None:
                        if error:
                            placeholder = f"--frame\r\nContent-Type: text/plain\r\n\r\n{error}\r\n".encode("utf-8")
                            self.wfile.write(placeholder)
                            self.wfile.flush()
                        time.sleep(0.05)
                        continue
                    try:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ")
                        self.wfile.write(str(len(jpeg)).encode("ascii"))
                        self.wfile.write(b"\r\n\r\n")
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        break
                    time.sleep(0.03)
                return
            self.send_error(HTTPStatus.NOT_FOUND.value)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b"{}"
            if path == "/api/reset":
                with state.lock:
                    state.events.clear()
                for camera in state.cameras.values():
                    with camera.lock:
                        camera.entry_count = 0
                        camera.exit_count = 0
                        for track in camera.tracks.values():
                            track.counted = False
                            track.exit_counted = False
                write_json(self, {"ok": True})
                return
            if path == "/api/counts":
                try:
                    payload = json.loads(body.decode("utf-8"))
                    updates = payload.get("cameras", {})
                    if not isinstance(updates, dict):
                        raise ValueError("Expected cameras object")
                    for camera_id, values in updates.items():
                        camera = state.cameras.get(str(camera_id))
                        if camera is None or not isinstance(values, dict):
                            continue
                        with camera.lock:
                            current_entries = int(camera.entry_count)
                            current_exits = int(camera.exit_count)
                            entries = current_entries
                            exits = current_exits
                            if "entry_count" in values:
                                entries = max(0, int(values.get("entry_count") or 0))
                            if "exit_count" in values:
                                exits = max(0, int(values.get("exit_count") or 0))
                            if "net_inside" in values:
                                net_inside = max(0, int(values.get("net_inside") or 0))
                                entries = max(entries, net_inside)
                                exits = entries - net_inside
                            camera.entry_count = max(0, entries)
                            camera.exit_count = min(max(0, exits), camera.entry_count)
                    with state.lock:
                        state.events.append(
                            {
                                "event_id": len(state.events) + 1,
                                "direction": "manual_adjustment",
                                "time_seconds": time.monotonic(),
                                "camera_id": "all",
                                "tracker_id": "-",
                                "confidence": 0.0,
                                "entry_count_camera": sum(cam.entry_count for cam in state.cameras.values()),
                                "exit_count_camera": sum(cam.exit_count for cam in state.cameras.values()),
                            }
                        )
                        state.events = state.events[-200:]
                except Exception as exc:
                    write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                write_json(self, {"ok": True})
                return
            if path == "/api/geometry":
                try:
                    payload = json.loads(body.decode("utf-8"))
                    geometries = payload.get("geometries", {})
                    with state.lock:
                        state.foot_source = str(payload.get("foot_source", state.foot_source))
                        state.confidence = float(payload.get("confidence", state.confidence))
                        new_quality = str(payload.get("quality", state.quality))
                        if new_quality != state.quality:
                            state.quality = new_quality
                            state.source_revision += 1
                        new_model_size = str(payload.get("model_size", state.model_size))
                        if new_model_size in {"n", "s", "ov", "x"} and new_model_size != state.model_size:
                            state.model_size = new_model_size
                            state.model_revision += 1
                    for camera_id, geometry_payload in geometries.items():
                        camera = state.cameras.get(camera_id)
                        fallback = DEFAULT_GEOMETRIES.get(camera_id)
                        if camera is None or fallback is None:
                            continue
                        next_geometry = geometry_from_payload(camera_id, geometry_payload, fallback)
                        with camera.lock:
                            camera.geometry = next_geometry
                            camera.calibrated = True
                    save_config(state)
                except Exception as exc:
                    write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                write_json(self, {"ok": True})
                return
            if path == "/api/settings":
                try:
                    payload = json.loads(body.decode("utf-8"))
                    with state.lock:
                        if "foot_source" in payload:
                            state.foot_source = str(payload["foot_source"])
                        if "confidence" in payload:
                            state.confidence = float(payload["confidence"])
                        if "quality" in payload:
                            new_quality = str(payload["quality"])
                            if new_quality != state.quality:
                                state.quality = new_quality
                                state.source_revision += 1
                        if "model_size" in payload:
                            new_model_size = str(payload["model_size"])
                            if new_model_size in {"n", "s", "ov", "x"} and new_model_size != state.model_size:
                                state.model_size = new_model_size
                                state.model_revision += 1
                        if "sales_count" in payload:
                            state.sales_count = max(0, int(payload["sales_count"] or 0))
                        if "selected_store_id" in payload:
                            state.selected_store_id = str(payload["selected_store_id"])
                        if "stores" in payload and isinstance(payload["stores"], list):
                            state.stores = payload["stores"]
                    save_config(state)
                except Exception as exc:
                    write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                write_json(self, {"ok": True})
                return
            self.send_error(HTTPStatus.NOT_FOUND.value)

    return EntranceHandler


def camera_source(camera_id: str, cameras: dict[str, Any], videos: dict[str, str], args: argparse.Namespace, quality: str) -> Any:
    if camera_id in videos:
        return str(resolve_project_path(videos[camera_id]))
    camera = cameras.get(camera_id)
    source = parse_source(args.source, camera)
    source = apply_camera_credentials(source, camera)
    if args.rtsp_channel:
        source = apply_rtsp_channel(source, args.rtsp_channel)
    elif quality in {"sub", "low"}:
        base = cameras.get(camera_id, {}).get("source", source)
        text = str(base)
        if "/channels/" in text:
            channel = text.rpartition("/")[2]
            if channel.isdigit() and len(channel) >= 2:
                source = apply_rtsp_channel(source, f"{channel[:-1]}{'3' if quality == 'low' else '2'}")
    return source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Web entrance counter for camera 501.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--camera-ids", nargs="+", default=["cam_501"])
    parser.add_argument("--cameras-file", default="camera_config/cameras.json")
    parser.add_argument("--source", default=None)
    parser.add_argument("--camera-video", nargs="*", default=[])
    parser.add_argument("--rtsp-channel", default=None)
    parser.add_argument("--config", default="outputs/config/entrance_geometry.json")
    parser.add_argument("--person-model", default="model weights/yolov8n.pt")
    parser.add_argument("--person-model-small", default="model weights/yolov8s.pt")
    parser.add_argument("--person-model-openvino", default="model weights/yolov8n_openvino_model")
    parser.add_argument("--person-model-yolox-openvino", default="model weights/yolox_tiny_openvino_model")
    parser.add_argument("--pose-model", default="model weights/yolov8n-pose.pt")
    parser.add_argument("--model-size", choices=["n", "s", "ov", "x"], default="x", help="Person detector backend: x=YOLOX-Tiny OpenVINO, n=YOLOv8n PyTorch, s=YOLOv8s PyTorch, ov=YOLOv8n OpenVINO.")
    parser.add_argument("--force-model-size", action="store_true", help="Use --model-size even if a saved UI config contains another model choice.")
    parser.add_argument("--yolox-openvino-device", default="CPU", help="OpenVINO device for YOLOX-Tiny, usually CPU on Optiplex.")
    parser.add_argument(
        "--foot-source",
        choices=["center", "pose", "box"],
        default="center",
        help="Crossing point: center is recommended for the overhead 501 view; pose uses ankles; box uses bottom-center.",
    )
    parser.add_argument("--quality", choices=["main", "sub", "low"], default="sub", help="Use main RTSP stream, substream such as 502, or lower third stream such as 503 when available.")
    parser.add_argument("--tracker", default="botsort.yaml")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.42)
    parser.add_argument("--iou", type=float, default=0.50)
    parser.add_argument("--device", default="0")
    parser.add_argument("--half", action="store_true", default=True)
    parser.add_argument("--no-half", action="store_false", dest="half")
    parser.add_argument("--max-det", type=int, default=24)
    parser.add_argument("--ankle-conf", type=float, default=0.20)
    parser.add_argument("--min-track-frames", type=int, default=3)
    parser.add_argument("--min-track-seconds", type=float, default=0.35)
    parser.add_argument("--min-crossing-travel-px", type=float, default=35.0)
    parser.add_argument("--min-outside-frames", type=int, default=1)
    parser.add_argument("--min-inside-frames", type=int, default=1)
    parser.add_argument("--line-margin-px", type=float, default=100.0, help="Accepted pixel margin around the entrance line. Increase if detections show but crossings are missed.")
    parser.add_argument("--line-deadzone-px", type=float, default=8.0, help="Pixel side deadzone around the line. Lower values count side changes closer to the line.")
    parser.add_argument("--max-missing-frames", type=int, default=45)
    parser.add_argument("--reflection-overlap-reject", type=float, default=0.65)
    parser.add_argument("--rtsp-max-delay-ms", type=int, default=500)
    parser.add_argument("--rtsp-read-timeout-ms", type=int, default=3000)
    parser.add_argument("--rtsp-open-timeout-ms", type=int, default=5000)
    parser.add_argument("--rtsp-transport", choices=["tcp", "udp"], default="tcp")
    parser.add_argument("--rtsp-retry-base-seconds", type=float, default=5.0)
    parser.add_argument("--rtsp-retry-max-seconds", type=float, default=60.0)
    parser.add_argument("--capture-buffer-size", type=int, default=1)
    parser.add_argument("--frame-width", type=int, default=0, help="Optional resize width before inference/display. Use 960 or 1280 to reduce load without changing RTSP URL.")
    parser.add_argument("--max-read-failures", type=int, default=15, help="Reconnect RTSP after this many consecutive failed reads.")
    parser.add_argument("--process-every-n", type=int, default=1, help="Run inference once every N captured frames. Use 2 on weak CPUs before lowering image size.")
    parser.add_argument("--loop-video", action="store_true", default=True)
    parser.add_argument("--no-loop-video", action="store_false", dest="loop_video")
    parser.add_argument("--jpeg-quality", type=int, default=82)
    parser.add_argument("--no-web", action="store_true", help="Disable the web interface and MJPEG encoding; print counts in the terminal.")
    parser.add_argument("--require-calibration", action="store_true", help="Exit at startup if any requested camera has no saved calibration.")
    parser.add_argument("--print-events", action="store_true", default=True)
    parser.add_argument("--no-print-events", action="store_false", dest="print_events")
    parser.add_argument("--terminal-interval", type=float, default=5.0, help="Seconds between terminal status lines in --no-web mode.")
    parser.add_argument("--profile-resources", action="store_true", help="Print periodic resource breakdown: RTSP read, resize, model, counting, JPEG/UI, CPU, RAM.")
    parser.add_argument("--profile-interval", type=float, default=5.0, help="Seconds between --profile-resources lines.")
    parser.add_argument("--events-csv", default="outputs/metrics/entrance_web_entries.csv")
    parser.add_argument("--tracks-csv", default="outputs/metrics/entrance_web_tracks.csv")
    parser.add_argument("--central-entries-csv", default="outputs/exports/central_entries.csv")
    parser.add_argument("--daily-entries-csv", default="outputs/exports/daily_entries_by_store.csv")
    parser.add_argument("--health-csv", default="outputs/exports/store_health.csv")
    parser.add_argument("--health-interval-seconds", type=float, default=60.0)
    parser.add_argument("--health-keep-healthy-minutes", type=float, default=30.0)
    parser.add_argument("--health-keep-issue-days", type=float, default=14.0)
    parser.add_argument("--health-min-fps", type=float, default=3.0)
    parser.add_argument("--health-startup-grace-seconds", type=float, default=180.0)
    parser.add_argument("--health-issue-delay-seconds", type=float, default=120.0)
    parser.add_argument("--health-cpu-warning-percent", type=float, default=90.0)
    parser.add_argument("--health-cpu-critical-percent", type=float, default=98.0)
    return parser.parse_args()


def run(args: argparse.Namespace) -> None:
    args.process_every_n = max(1, int(args.process_every_n))
    cameras_config = load_cameras(resolve_project_path(args.cameras_file))
    videos = parse_camera_video_sources(args.camera_video)
    config_path = resolve_project_path(args.config)
    (
        geometries,
        calibrated_ids,
        saved_foot_source,
        saved_conf,
        saved_quality,
        saved_model_size,
        saved_stores,
        saved_selected_store_id,
        saved_sales_count,
    ) = load_config(
        config_path,
        args.camera_ids,
        args.foot_source,
        args.conf,
        args.quality,
        args.model_size,
    )
    state = EntranceAppState(
        foot_source=saved_foot_source or args.foot_source,
        confidence=saved_conf or args.conf,
        device=args.device,
        quality=saved_quality or args.quality,
        model_size=args.model_size if args.force_model_size else (saved_model_size or args.model_size),
        stores=saved_stores,
        selected_store_id=saved_selected_store_id,
        sales_count=saved_sales_count,
        config_path=config_path,
    )
    for camera_id in args.camera_ids:
        if camera_id not in geometries:
            raise SystemExit(f"No default geometry for {camera_id}")
        state.cameras[camera_id] = CameraState(camera_id=camera_id, geometry=geometries[camera_id], calibrated=camera_id in calibrated_ids)
    if args.require_calibration:
        missing = [camera_id for camera_id in args.camera_ids if camera_id not in calibrated_ids]
        if missing:
            missing_text = ", ".join(missing)
            raise SystemExit(
                f"Missing saved calibration for: {missing_text}. "
                f"Run START_WITH_WEB_UI.bat once to draw/save the line and ROI, "
                f"or create {config_path} before starting terminal mode."
            )

    events_path = resolve_project_path(args.events_csv)
    tracks_path = resolve_project_path(args.tracks_csv)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    tracks_path.parent.mkdir(parents=True, exist_ok=True)
    event_fieldnames = ["event_id", "direction", "time_seconds", "camera_id", "tracker_id", "confidence", "first_frame", "last_frame", "foot_source", "entry_count_camera", "exit_count_camera"]
    track_fieldnames = ["time_seconds", "camera_id", "frame_index", "tracker_id", "confidence", "usable", "foot_source", "x1", "y1", "x2", "y2", "foot_x", "foot_y"]
    ensure_csv_header(events_path, event_fieldnames)
    ensure_csv_header(tracks_path, track_fieldnames)
    events_file = events_path.open("a", newline="", encoding="utf-8", buffering=1)
    tracks_file = tracks_path.open("a", newline="", encoding="utf-8", buffering=1)
    events_writer = csv.DictWriter(
        events_file,
        fieldnames=event_fieldnames,
    )
    tracks_writer = csv.DictWriter(
        tracks_file,
        fieldnames=track_fieldnames,
    )
    events_file.flush()
    tracks_file.flush()
    print(f"Entry events CSV: {events_path}", flush=True)
    print(f"Track diagnostics CSV: {tracks_path}", flush=True)

    threads: list[threading.Thread] = []
    csv_lock = threading.Lock()
    for camera_id, camera in state.cameras.items():
        def source_for_quality(target_camera_id: str, quality: str, cameras_config: dict[str, Any] = cameras_config, videos: dict[str, str] = videos, args: argparse.Namespace = args) -> Any:
            return camera_source(target_camera_id, cameras_config, videos, args, quality)
        thread = threading.Thread(
            target=camera_worker,
            args=(camera, source_for_quality, state, args, events_writer, events_file, tracks_writer, tracks_file, csv_lock),
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    health_thread = threading.Thread(target=health_monitor_worker, args=(state, args, csv_lock), daemon=True)
    health_thread.start()
    threads.append(health_thread)
    print(f"Health monitoring CSV: {resolve_project_path(args.health_csv)}", flush=True)

    print(
        f"Using device={args.device} foot_source={state.foot_source} quality={state.quality} "
        f"model={'yolox-tiny' if state.model_size == 'x' else f'yolov8{state.model_size}'} "
        f"process_every_n={args.process_every_n}",
        flush=True,
    )
    if args.no_web:
        print("Running in terminal mode. Press Ctrl+C to stop.", flush=True)
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            state.stop = True
            for thread in threads:
                thread.join(timeout=2.0)
            events_file.close()
            tracks_file.close()
        return

    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(f"Entrance web app: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        state.stop = True
        server.server_close()
        for thread in threads:
            thread.join(timeout=2.0)
        events_file.close()
        tracks_file.close()
        for thread in threads:
            thread.join(timeout=2.0)
        events_file.close()
        tracks_file.close()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
