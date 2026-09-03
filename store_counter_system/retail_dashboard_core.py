from __future__ import annotations

import argparse
import json
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import numpy as np

from person_101_reid import Detection, bottom_center, draw_label
QUALITY_WIDTHS = {
    "hd": 1280,
    "fhd": 1920,
    "2k": 2560,
    "4k": 3840,
}
DEFAULT_QUALITY_RTSP_CHANNELS = {
    "hd": "102",
    "fhd": "101",
    "2k": "101",
    "4k": "101",
}


@dataclass
class Zone:
    zone_id: str
    box: tuple[int, int, int, int]
    marker_count: int = 0
    colors: list[str] = field(default_factory=list)
    auto: bool = True


@dataclass
class MarkerState:
    color: str
    zone_id: str = ""
    was_inside_zone: bool = False
    inside_frames: int = 0
    outside_frames: int = 0
    missing_frames: int = 0
    cooldown: int = 0
    pickup_count: int = 0
    last_xy: tuple[float, float] | None = None
    last_inside_xy: tuple[float, float] | None = None
    last_confidence: float = 0.0
    pickup_times: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MarkerTrack:
    track_id: int
    color: str
    box: list[float]
    cx: float
    cy: float
    confidence: float
    home_zone_id: str = ""
    armed: bool = False
    inside_frames: int = 0
    outside_frames: int = 0
    missing_frames: int = 0
    cooldown: int = 0
    pickup_count: int = 0
    last_seen_frame: int = 0
    last_seen_time: float = 0.0


@dataclass
class PersonBoxTrack:
    tracker_id: int
    box: list[float]
    last_seen_frame: int = 0


@dataclass
class AppState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    latest_jpeg: bytes | None = None
    latest_raw_shape: tuple[int, int] | None = None
    running: bool = False
    stop: bool = False
    status: str = "detecting zones"
    session_id: str | None = None
    session_video_path: str = ""
    camera_id: str = "cam_101"
    camera_options: list[str] = field(default_factory=list)
    camera_revision: int = 0
    fps: float = 0.0
    frame_index: int = 0
    quality: str = "4k"
    quality_revision: int = 0
    system_revision: int = 0
    heavy_separate_person: bool = False
    heavy_reid: bool = False
    heavy_pose: bool = False
    save_session_video: bool = False
    zone: Zone | None = None
    zones: list[Zone] = field(default_factory=list)
    people: list[dict[str, Any]] = field(default_factory=list)
    marker_detections: list[dict[str, Any]] = field(default_factory=list)
    marker_counts: dict[str, int] = field(default_factory=dict)
    pickups: list[dict[str, Any]] = field(default_factory=list)
    articles: dict[str, dict[str, Any]] = field(default_factory=dict)
    marker_classes: list[str] = field(default_factory=list)
    multi_camera_sources: dict[str, str] = field(default_factory=dict)


@dataclass
class PoseSample:
    frame_index: int
    time_seconds: float
    person_id: str
    tracker_id: int
    wrists: list[tuple[float, float, float]]


@dataclass
class MarkerSample:
    frame_index: int
    time_seconds: float
    color: str
    xy: tuple[float, float]
    confidence: float
    inside_zone: bool


@dataclass
class FrameSnapshot:
    frame_index: int
    time_seconds: float
    frame: np.ndarray
    people: list[dict[str, Any]]


@dataclass
class PoseJob:
    event_id: str
    marker_color: str
    marker_xy: tuple[float, float]
    pickup_time: float
    window_start: float
    window_end: float


def normalize_box(box: tuple[int, int, int, int], frame: np.ndarray | None = None) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    if frame is not None:
        h, w = frame.shape[:2]
        left = max(0, min(w - 1, left))
        right = max(0, min(w - 1, right))
        top = max(0, min(h - 1, top))
        bottom = max(0, min(h - 1, bottom))
    return left, top, right, bottom


def resize_for_quality(frame: np.ndarray, quality: str) -> np.ndarray:
    target_width = QUALITY_WIDTHS.get(str(quality).lower(), QUALITY_WIDTHS["4k"])
    h, w = frame.shape[:2]
    if w <= target_width:
        return frame
    scale = target_width / float(w)
    target_height = max(1, int(round(h * scale)))
    return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)


def apply_rtsp_channel(source: Any, channel: str | None) -> Any:
    if channel is None or isinstance(source, int):
        return source
    text = str(source)
    if "/channels/" not in text:
        return source
    prefix, _sep, _old = text.rpartition("/")
    return f"{prefix}/{channel}"


def rtsp_channel_from_source(source: Any) -> str | None:
    if isinstance(source, int):
        return None
    text = str(source)
    if "/channels/" not in text:
        return None
    return text.rpartition("/")[2].strip() or None


def quality_rtsp_channel(source: Any, quality: str, overrides: dict[str, str]) -> str | None:
    if quality in overrides:
        return overrides[quality]
    base_channel = rtsp_channel_from_source(source)
    if not base_channel or len(base_channel) < 2 or not base_channel.isdigit():
        return DEFAULT_QUALITY_RTSP_CHANNELS.get(quality)
    prefix = base_channel[:-1]
    if quality == "hd":
        return f"{prefix}2"
    return f"{prefix}1"


def parse_quality_rtsp_channels(values: list[str]) -> dict[str, str]:
    channels: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --quality-rtsp-channel value {value!r}; expected quality=channel")
        quality, channel = [part.strip().lower() for part in value.split("=", 1)]
        if quality not in QUALITY_WIDTHS:
            raise SystemExit(f"Unknown quality {quality!r}; expected hd, fhd, 2k, or 4k")
        if not channel:
            raise SystemExit(f"Empty RTSP channel for quality {quality!r}")
        channels[quality] = channel
    return channels


def parse_camera_video_sources(values: list[str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --camera-video value {value!r}; expected camera_id=path")
        camera_id, path = value.split("=", 1)
        camera_id = camera_id.strip()
        path = path.strip().strip('"')
        if not camera_id or not path:
            raise SystemExit(f"Invalid --camera-video value {value!r}; expected camera_id=path")
        sources[camera_id] = path
    return sources


def is_file_source(source: Any) -> bool:
    if isinstance(source, int):
        return False
    text = str(source)
    parsed = urlparse(text)
    if parsed.scheme.lower() in {"rtsp", "http", "https"}:
        return False
    return Path(text).exists()


def point_in_box(xy: tuple[float, float], box: tuple[int, int, int, int] | None) -> bool:
    if box is None:
        return False
    left, top, right, bottom = normalize_box(box)
    return left <= xy[0] <= right and top <= xy[1] <= bottom


def boxes_intersect(
    a: tuple[int, int, int, int] | list[float],
    b: tuple[int, int, int, int] | list[float],
    tolerance: float = 0.0,
) -> bool:
    ax1, ay1, ax2, ay2 = normalize_box(tuple(int(round(v)) for v in a))
    bx1, by1, bx2, by2 = normalize_box(tuple(int(round(v)) for v in b))
    return (
        ax1 <= bx2 + tolerance
        and ax2 >= bx1 - tolerance
        and ay1 <= by2 + tolerance
        and ay2 >= by1 - tolerance
    )


def marker_box_touches_zone_boundary(
    marker_box: list[float],
    zone_box: tuple[int, int, int, int],
    tolerance: float,
) -> bool:
    if len(marker_box) != 4:
        return False
    cx, cy = center_of_box([float(v) for v in marker_box])
    if point_in_box((cx, cy), zone_box):
        return False
    return boxes_intersect(marker_box, zone_box, tolerance)


def segment_leaves_box(
    start_xy: tuple[float, float] | None,
    end_xy: tuple[float, float],
    box: tuple[int, int, int, int],
) -> bool:
    if start_xy is None:
        return False
    if not point_in_box(start_xy, box) or point_in_box(end_xy, box):
        return False
    left, top, right, bottom = normalize_box(box)
    sx, sy = start_xy
    ex, ey = end_xy
    for boundary in (left, right):
        dx = ex - sx
        if abs(dx) < 1e-6:
            continue
        t = (boundary - sx) / dx
        if 0.0 <= t <= 1.0:
            y = sy + t * (ey - sy)
            if top <= y <= bottom:
                return True
    for boundary in (top, bottom):
        dy = ey - sy
        if abs(dy) < 1e-6:
            continue
        t = (boundary - sy) / dy
        if 0.0 <= t <= 1.0:
            x = sx + t * (ex - sx)
            if left <= x <= right:
                return True
    return False


def detection_size(det: dict[str, Any]) -> float:
    x1, y1, x2, y2 = [float(v) for v in det["box"]]
    return max(4.0, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)


def update_marker_tracks(
    tracks: dict[int, MarkerTrack],
    detections: list[dict[str, Any]],
    zones: list[Zone],
    frame_index: int,
    elapsed: float,
    args: argparse.Namespace,
    next_track_id: int,
) -> int:
    unmatched_tracks = set(tracks.keys())
    unmatched_detections = set(range(len(detections)))
    candidate_pairs: list[tuple[float, int, int]] = []
    for track_id, track in tracks.items():
        for det_idx, det in enumerate(detections):
            if det["color"] != track.color:
                continue
            distance = float(((float(det["cx"]) - track.cx) ** 2 + (float(det["cy"]) - track.cy) ** 2) ** 0.5)
            max_distance = max(args.marker_track_max_distance, detection_size(det) * args.marker_track_distance_factor)
            if distance <= max_distance:
                candidate_pairs.append((distance, track_id, det_idx))
    for _distance, track_id, det_idx in sorted(candidate_pairs, key=lambda item: item[0]):
        if track_id not in unmatched_tracks or det_idx not in unmatched_detections:
            continue
        det = detections[det_idx]
        track = tracks[track_id]
        track.box = [float(v) for v in det["box"]]
        track.cx = float(det["cx"])
        track.cy = float(det["cy"])
        track.confidence = float(det["confidence"])
        track.last_seen_frame = frame_index
        track.last_seen_time = elapsed
        track.missing_frames = 0
        unmatched_tracks.remove(track_id)
        unmatched_detections.remove(det_idx)

    for track_id in list(unmatched_tracks):
        track = tracks[track_id]
        track.missing_frames += 1
        if track.missing_frames >= args.marker_track_max_missing_frames:
            del tracks[track_id]

    for det_idx in sorted(unmatched_detections):
        det = detections[det_idx]
        home_zone = zone_for_point((float(det["cx"]), float(det["cy"])), zones)
        if home_zone is None:
            continue
        tracks[next_track_id] = MarkerTrack(
            track_id=next_track_id,
            color=str(det["color"]),
            box=[float(v) for v in det["box"]],
            cx=float(det["cx"]),
            cy=float(det["cy"]),
            confidence=float(det["confidence"]),
            home_zone_id=home_zone.zone_id,
            last_seen_frame=frame_index,
            last_seen_time=elapsed,
        )
        next_track_id += 1
    return next_track_id


def update_person_box_tracks(
    tracks: dict[int, PersonBoxTrack],
    detections: list[dict[str, Any]],
    frame_index: int,
    args: argparse.Namespace,
    next_track_id: int,
) -> tuple[list[Detection], int]:
    accepted: list[Detection] = []
    unmatched_tracks = set(tracks.keys())
    candidate_pairs: list[tuple[float, int, int]] = []
    for track_id, track in tracks.items():
        tx, ty = center_of_box(track.box)
        for det_idx, det in enumerate(detections):
            iou = box_iou(track.box, det["box"])
            dx, dy = center_of_box(det["box"])
            distance = float(((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5)
            if iou >= args.combined_person_track_min_iou or distance <= args.combined_person_track_max_distance:
                score = (1.0 - iou) + distance / max(1.0, args.combined_person_track_max_distance)
                candidate_pairs.append((score, track_id, det_idx))

    unmatched_detections = set(range(len(detections)))
    for _score, track_id, det_idx in sorted(candidate_pairs, key=lambda item: item[0]):
        if track_id not in unmatched_tracks or det_idx not in unmatched_detections:
            continue
        det = detections[det_idx]
        tracks[track_id].box = [float(v) for v in det["box"]]
        tracks[track_id].last_seen_frame = frame_index
        accepted.append(
            Detection(
                tracker_id=track_id,
                box=[float(v) for v in det["box"]],
                confidence=float(det["confidence"]),
                point=bottom_center(det["box"]),
            )
        )
        unmatched_tracks.remove(track_id)
        unmatched_detections.remove(det_idx)

    for det_idx in sorted(unmatched_detections):
        det = detections[det_idx]
        track_id = next_track_id
        next_track_id += 1
        tracks[track_id] = PersonBoxTrack(
            tracker_id=track_id,
            box=[float(v) for v in det["box"]],
            last_seen_frame=frame_index,
        )
        accepted.append(
            Detection(
                tracker_id=track_id,
                box=[float(v) for v in det["box"]],
                confidence=float(det["confidence"]),
                point=bottom_center(det["box"]),
            )
        )

    for track_id in list(tracks):
        if frame_index - tracks[track_id].last_seen_frame > args.combined_person_track_max_missing_frames:
            del tracks[track_id]

    return accepted, next_track_id


def marker_scale(det: dict[str, Any]) -> float:
    x1, y1, x2, y2 = [float(v) for v in det["box"]]
    return max(2.0, ((x2 - x1) * (y2 - y1)) ** 0.5)


def marker_sizes_compatible(a: dict[str, Any], b: dict[str, Any], tolerance: float) -> bool:
    scale_a = marker_scale(a)
    scale_b = marker_scale(b)
    ratio = max(scale_a, scale_b) / max(1.0, min(scale_a, scale_b))
    return ratio <= tolerance


def markers_on_same_rack_line(
    a: dict[str, Any],
    b: dict[str, Any],
    max_distance_markers: float,
    alignment_tolerance_markers: float,
    size_tolerance: float,
) -> bool:
    if not marker_sizes_compatible(a, b, size_tolerance):
        return False
    ax, ay = float(a["cx"]), float(a["cy"])
    bx, by = float(b["cx"]), float(b["cy"])
    dx = abs(ax - bx)
    dy = abs(ay - by)
    scale = (marker_scale(a) + marker_scale(b)) * 0.5
    distance = float((dx * dx + dy * dy) ** 0.5)
    if distance > scale * max_distance_markers:
        return False
    align_tol = scale * alignment_tolerance_markers
    horizontal = dy <= align_tol
    vertical = dx <= align_tol
    diagonal = abs(dx - dy) <= align_tol
    return horizontal or vertical or diagonal


def group_marker_box(
    detections: list[dict[str, Any]],
    frame_shape: tuple[int, int],
    width_factor: float,
    height_factor: float,
) -> tuple[int, int, int, int]:
    zones = [expanded_marker_zone(det["box"], frame_shape, width_factor, height_factor) for det in detections]
    box = zones[0]
    for candidate_zone in zones[1:]:
        box = union_box(box, candidate_zone)
    return box


def union_box(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    ax1, ay1, ax2, ay2 = normalize_box(a)
    bx1, by1, bx2, by2 = normalize_box(b)
    return min(ax1, bx1), min(ay1, by1), max(ax2, bx2), max(ay2, by2)


def expanded_marker_zone(
    box: list[float],
    frame_shape: tuple[int, int],
    width_factor: float,
    height_factor: float,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [float(v) for v in box]
    h, w = frame_shape[:2]
    bw = max(2.0, x2 - x1)
    bh = max(2.0, y2 - y1)
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    zone_w = bw * width_factor
    zone_h = bh * height_factor
    return normalize_box(
        (
            int(round(max(0.0, cx - zone_w * 0.5))),
            int(round(max(0.0, cy - zone_h * 0.5))),
            int(round(min(float(w - 1), cx + zone_w * 0.5))),
            int(round(min(float(h - 1), cy + zone_h * 0.5))),
        )
    )


def auto_rack_zones(
    detections: list[dict[str, Any]],
    frame_shape: tuple[int, int],
    width_factor: float,
    height_factor: float,
    max_distance_markers: float,
    alignment_tolerance_markers: float,
    size_tolerance: float,
) -> list[Zone]:
    groups: list[dict[str, Any]] = []
    for det in sorted(detections, key=lambda d: (float(d["cy"]), float(d["cx"]))):
        color = str(det["color"])
        merged = False
        for group in groups:
            if any(
                markers_on_same_rack_line(
                    det,
                    member,
                    max_distance_markers,
                    alignment_tolerance_markers,
                    size_tolerance,
                )
                for member in group["members"]
            ):
                group["members"].append(det)
                group["count"] += 1
                group["colors"].add(color)
                merged = True
                break
        if not merged:
            groups.append({"members": [det], "count": 1, "colors": {color}})

    changed = True
    while changed:
        changed = False
        merged_groups: list[dict[str, Any]] = []
        for group in groups:
            target = None
            for existing in merged_groups:
                if any(
                    markers_on_same_rack_line(
                        a,
                        b,
                        max_distance_markers,
                        alignment_tolerance_markers,
                        size_tolerance,
                    )
                    for a in existing["members"]
                    for b in group["members"]
                ):
                    target = existing
                    break
            if target is None:
                merged_groups.append(group)
            else:
                target["members"].extend(group["members"])
                target["count"] += group["count"]
                target["colors"].update(group["colors"])
                changed = True
        groups = merged_groups

    zones = [
        Zone(
            zone_id=f"zone_{idx}",
            box=normalize_box(group_marker_box(group["members"], frame_shape, width_factor, height_factor)),
            marker_count=int(group["count"]),
            colors=sorted(group["colors"]),
            auto=True,
        )
        for idx, group in enumerate(
            sorted(groups, key=lambda g: (min(float(member["cy"]) for member in g["members"]), min(float(member["cx"]) for member in g["members"]))),
            start=1,
        )
    ]
    return zones


def zone_for_point(xy: tuple[float, float], zones: list[Zone]) -> Zone | None:
    for candidate_zone in zones:
        if point_in_box(xy, candidate_zone.box):
            return candidate_zone
    return None


def article_key(zone_id: str, marker_color: str) -> str:
    return f"{zone_id}|{marker_color.lower()}"


def load_articles(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    articles: dict[str, dict[str, Any]] = {}
    for item in payload.get("articles", []):
        zone_id = str(item.get("zone_id", "")).strip()
        marker_color = str(item.get("marker_color", "")).strip().lower()
        article_id = str(item.get("article_id", "")).strip()
        if zone_id and marker_color and article_id:
            articles[article_key(zone_id, marker_color)] = {
                "article_id": article_id,
                "zone_id": zone_id,
                "marker_color": marker_color,
                "image_path": str(item.get("image_path", "")).strip(),
            }
    return articles


def save_articles(path: Path, articles: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"articles": sorted(articles.values(), key=lambda item: (item["zone_id"], item["marker_color"], item["article_id"]))}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def update_pickup_assignment(
    pickups: list[dict[str, Any]],
    event_id: str,
    person_id: str,
    assignment_method: str,
    assignment_score: float,
) -> bool:
    for event in pickups:
        if event.get("event_id") == event_id:
            event["person_id"] = person_id
            event["assignment_method"] = assignment_method
            event["assignment_score"] = round(float(assignment_score), 3)
            return True
    return False


def class_color(name: str) -> tuple[int, int, int]:
    lowered = name.lower()
    if "blue" in lowered or "cyan" in lowered:
        return (255, 170, 40)
    if "purple" in lowered:
        return (220, 80, 220)
    if "green" in lowered:
        return (0, 210, 0)
    if "pink" in lowered:
        return (220, 0, 220)
    if "yellow" in lowered:
        return (0, 220, 255)
    return (0, 165, 255)


def parse_class_thresholds(values: list[str], default_conf: float) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --marker-class-conf value {value!r}; expected name=value")
        name, raw_threshold = value.split("=", 1)
        try:
            thresholds[name.strip().lower()] = float(raw_threshold)
        except ValueError as exc:
            raise SystemExit(f"Invalid threshold in --marker-class-conf {value!r}") from exc
    thresholds.setdefault("_default", default_conf)
    return thresholds


def draw_zone(frame: np.ndarray, rack_zone: Zone | None) -> None:
    if rack_zone is None:
        return
    left, top, right, bottom = normalize_box(rack_zone.box, frame)
    color = (255, 190, 60)
    cv2.rectangle(frame, (left, top), (right, bottom), color, 1, cv2.LINE_AA)
    draw_label(frame, rack_zone.zone_id, (left, max(18, top - 8)), color)


def draw_zones(frame: np.ndarray, zones: list[Zone]) -> None:
    for rack_zone in zones:
        left, top, right, bottom = normalize_box(rack_zone.box, frame)
        color = (255, 190, 60)
        width = max(1, right - left)
        height = max(1, bottom - top)
        corner = max(10, min(34, int(min(width, height) * 0.22)))
        cv2.rectangle(frame, (left, top), (right, bottom), color, 1, cv2.LINE_AA)
        cv2.line(frame, (left, top), (left + corner, top), color, 3, cv2.LINE_AA)
        cv2.line(frame, (left, top), (left, top + corner), color, 3, cv2.LINE_AA)
        cv2.line(frame, (right, top), (right - corner, top), color, 3, cv2.LINE_AA)
        cv2.line(frame, (right, top), (right, top + corner), color, 3, cv2.LINE_AA)
        cv2.line(frame, (left, bottom), (left + corner, bottom), color, 3, cv2.LINE_AA)
        cv2.line(frame, (left, bottom), (left, bottom - corner), color, 3, cv2.LINE_AA)
        cv2.line(frame, (right, bottom), (right - corner, bottom), color, 3, cv2.LINE_AA)
        cv2.line(frame, (right, bottom), (right, bottom - corner), color, 3, cv2.LINE_AA)
        suffix = f" - {rack_zone.marker_count}" if rack_zone.marker_count else ""
        draw_label(frame, f"{rack_zone.zone_id}{suffix}", (left, max(18, top - 8)), color)


def center_of_box(box: list[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) * 0.5, (y1 + y2) * 0.5


def assign_person_to_pickup(marker_xy: tuple[float, float], people: list[dict[str, Any]], max_distance: float) -> str:
    best_id = ""
    best_distance = max_distance
    mx, my = marker_xy
    for person in people:
        box = person.get("box") or []
        if len(box) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in box]
        expanded = max(35.0, (x2 - x1) * 0.25)
        if x1 - expanded <= mx <= x2 + expanded and y1 - expanded <= my <= y2 + expanded:
            return str(person.get("person_id") or "")
        px = (x1 + x2) * 0.5
        py = y2
        distance = float(((mx - px) ** 2 + (my - py) ** 2) ** 0.5)
        if distance < best_distance:
            best_distance = distance
            best_id = str(person.get("person_id") or "")
    return best_id


def nearby_person_count(marker_xy: tuple[float, float], people: list[dict[str, Any]], max_distance: float) -> int:
    mx, my = marker_xy
    count = 0
    for person in people:
        box = person.get("box") or []
        if len(box) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in box]
        expanded = max(35.0, (x2 - x1) * 0.25)
        if x1 - expanded <= mx <= x2 + expanded and y1 - expanded <= my <= y2 + expanded:
            count += 1
            continue
        px = (x1 + x2) * 0.5
        py = y2
        distance = float(((mx - px) ** 2 + (my - py) ** 2) ** 0.5)
        if distance <= max_distance:
            count += 1
    return count


def assign_person_from_pose_samples(
    marker_xy: tuple[float, float],
    pose_samples: list[PoseSample],
    args: argparse.Namespace,
) -> tuple[str, str, float]:
    by_person: dict[str, list[float]] = {}
    mx, my = marker_xy
    for pose in pose_samples:
        if not pose.person_id:
            continue
        for wrist_x, wrist_y, wrist_conf in pose.wrists:
            if wrist_conf < args.wrist_conf:
                continue
            distance = float(((wrist_x - mx) ** 2 + (wrist_y - my) ** 2) ** 0.5)
            by_person.setdefault(pose.person_id, []).append(distance / max(wrist_conf, 0.15))
    candidates: list[tuple[str, float, int]] = []
    for person_id, distances in by_person.items():
        best_distances = sorted(distances)[: max(1, args.wrist_assign_top_k)]
        hits = sum(1 for distance in distances if distance <= args.wrist_assign_max_distance)
        if not best_distances:
            continue
        score = 1.0 / (1.0 + (sum(best_distances) / len(best_distances)) / max(1.0, args.wrist_assign_max_distance))
        candidates.append((person_id, score, hits))
    candidates.sort(key=lambda item: item[1], reverse=True)
    if not candidates:
        return "", "pose_unassigned", 0.0
    best_id, best_score, best_hits = candidates[0]
    if best_hits < args.wrist_assign_min_hits or best_score < args.wrist_assign_min_score:
        return "", "pose_unassigned", best_score
    if len(candidates) > 1 and candidates[1][1] >= best_score - args.wrist_assign_margin:
        return "", "pose_ambiguous", best_score
    return best_id, "deferred_wrist", best_score


def process_pose_job(
    pose_model: Any | None,
    job: PoseJob,
    frame_buffer: deque[FrameSnapshot],
    args: argparse.Namespace,
) -> tuple[str, str, float]:
    if pose_model is None:
        return "", "pose_disabled", 0.0
    snapshots = [
        snapshot
        for snapshot in frame_buffer
        if job.window_start <= snapshot.time_seconds <= job.window_end and snapshot.people
    ]
    if not snapshots:
        return "", "pose_no_frames", 0.0
    if len(snapshots) > args.pose_event_max_frames:
        target_times = np.linspace(job.window_start, job.window_end, args.pose_event_max_frames)
        selected: list[FrameSnapshot] = []
        for target_time in target_times:
            selected.append(min(snapshots, key=lambda snapshot: abs(snapshot.time_seconds - float(target_time))))
        snapshots = list({snapshot.frame_index: snapshot for snapshot in selected}.values())
    pose_samples: list[PoseSample] = []
    for snapshot in snapshots:
        people = [dict(person) for person in snapshot.people]
        update_pose_people(snapshot.frame, pose_model, people, args)
        for person in people:
            wrists = person.get("wrists") or []
            if not wrists:
                continue
            pose_samples.append(
                PoseSample(
                    frame_index=snapshot.frame_index,
                    time_seconds=snapshot.time_seconds,
                    person_id=str(person.get("person_id") or ""),
                    tracker_id=int(person.get("tracker_id") or -1),
                    wrists=[(float(x), float(y), float(conf)) for x, y, conf in wrists],
                )
            )
    return assign_person_from_pose_samples(job.marker_xy, pose_samples, args)


def box_iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 1e-6 else 0.0


def prune_history(items: list[Any], now_seconds: float, keep_seconds: float) -> None:
    cutoff = now_seconds - keep_seconds
    del items[: next((idx for idx, item in enumerate(items) if item.time_seconds >= cutoff), len(items))]


def update_pose_people(
    frame: np.ndarray,
    pose_model: Any | None,
    active_people: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    if pose_model is None or not active_people:
        return
    pose_result = pose_model.predict(
        frame,
        imgsz=args.pose_imgsz,
        conf=args.pose_conf,
        iou=args.pose_iou,
        device=args.device,
        half=args.half and args.device != "cpu",
        max_det=args.pose_max_det,
        verbose=False,
    )[0]
    if pose_result.boxes is None or pose_result.keypoints is None:
        return
    pose_boxes = pose_result.boxes.xyxy.cpu().numpy()
    keypoints_xy = pose_result.keypoints.xy.cpu().numpy()
    keypoints_conf = None
    if getattr(pose_result.keypoints, "conf", None) is not None:
        keypoints_conf = pose_result.keypoints.conf.cpu().numpy()
    claimed_people: set[int] = set()
    for pose_idx, pose_box_arr in enumerate(pose_boxes):
        pose_box = [float(v) for v in pose_box_arr.tolist()]
        best_person_idx = -1
        best_score = 0.0
        for person_idx, person in enumerate(active_people):
            if person_idx in claimed_people:
                continue
            iou = box_iou(pose_box, person["box"])
            if iou > best_score:
                best_score = iou
                best_person_idx = person_idx
        if best_person_idx < 0 or best_score < args.pose_person_min_iou:
            continue
        wrists: list[tuple[float, float, float]] = []
        for kp_idx in (9, 10):
            if kp_idx >= len(keypoints_xy[pose_idx]):
                continue
            x, y = keypoints_xy[pose_idx][kp_idx]
            conf = float(keypoints_conf[pose_idx][kp_idx]) if keypoints_conf is not None else 1.0
            if conf < args.wrist_conf:
                continue
            wrists.append((float(x), float(y), conf))
        if not wrists:
            continue
        active_people[best_person_idx]["wrists"] = wrists
        active_people[best_person_idx]["pose_iou"] = round(best_score, 3)
        claimed_people.add(best_person_idx)


def assign_person_to_pickup_with_pose(
    marker_color: str,
    marker_xy: tuple[float, float],
    active_people: list[dict[str, Any]],
    pose_history: list[PoseSample],
    marker_history: dict[str, list[MarkerSample]],
    now_seconds: float,
    args: argparse.Namespace,
) -> tuple[str, str, float]:
    samples = [
        sample
        for sample in marker_history.get(marker_color, [])
        if now_seconds - args.pickup_assignment_window_seconds <= sample.time_seconds <= now_seconds
    ]
    if not samples:
        samples = [MarkerSample(0, now_seconds, marker_color, marker_xy, 1.0, False)]
    marker_points = [sample.xy for sample in samples]
    pose_samples = [
        sample
        for sample in pose_history
        if sample.person_id and now_seconds - args.pickup_assignment_window_seconds <= sample.time_seconds <= now_seconds
    ]
    by_person: dict[str, list[float]] = {}
    for pose in pose_samples:
        for wrist_x, wrist_y, wrist_conf in pose.wrists:
            nearest_marker_distance = min(
                float(((wrist_x - mx) ** 2 + (wrist_y - my) ** 2) ** 0.5)
                for mx, my in marker_points
            )
            by_person.setdefault(pose.person_id, []).append(nearest_marker_distance / max(wrist_conf, 0.15))
    candidates: list[tuple[str, float, int]] = []
    for person_id, distances in by_person.items():
        if not distances:
            continue
        distances.sort()
        close_hits = sum(1 for distance in distances if distance <= args.wrist_assign_max_distance)
        trimmed = distances[: min(len(distances), max(1, args.wrist_assign_top_k))]
        mean_distance = sum(trimmed) / len(trimmed)
        score = max(0.0, 1.0 - mean_distance / max(1.0, args.wrist_assign_max_distance))
        score += min(0.25, close_hits * 0.04)
        candidates.append((person_id, score, close_hits))
    candidates.sort(key=lambda item: item[1], reverse=True)
    if candidates:
        best_id, best_score, close_hits = candidates[0]
        second_score = candidates[1][1] if len(candidates) > 1 else 0.0
        if (
            best_score >= args.wrist_assign_min_score
            and close_hits >= args.wrist_assign_min_hits
            and best_score - second_score >= args.wrist_assign_margin
        ):
            return best_id, "wrist", best_score
        if best_score >= args.wrist_ambiguous_min_score:
            return "", "ambiguous_wrist", best_score
    fallback_id = assign_person_to_pickup(marker_xy, active_people, args.person_assign_max_distance)
    return fallback_id, "box_fallback" if fallback_id else "unassigned", 0.0


def encode_jpeg(frame: np.ndarray, quality: int) -> bytes | None:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return encoded.tobytes() if ok else None


def open_writer(path: Path, codec: str, fps: float, size: tuple[int, int]) -> tuple[cv2.VideoWriter, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
    if writer.isOpened():
        return writer, path
    fallback = path.with_suffix(".avi")
    writer = cv2.VideoWriter(str(fallback), cv2.VideoWriter_fourcc(*"XVID"), fps, size)
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {path}")
    return writer, fallback
