from __future__ import annotations

import argparse
import csv
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass
class Detection:
    tracker_id: int
    box: list[float]
    confidence: float
    point: Point
    embedding: np.ndarray | None = None
    rejected_reason: str | None = None


@dataclass
class TrackState:
    tracker_id: int
    first_seen: float
    last_seen: float
    first_point: Point
    last_point: Point
    frames_seen: int = 0
    max_displacement: float = 0.0
    embedding: np.ndarray | None = None
    embedding_count: int = 0
    person_id: str | None = None
    created_person_at: float | None = None


@dataclass
class PersonIdentity:
    person_id: str
    created_at: float
    last_seen: float
    last_point: Point
    embedding: np.ndarray | None = None
    embedding_count: int = 0
    active_tracker_id: int | None = None


def load_cameras(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return {str(c["camera_id"]): c for c in payload.get("cameras", [])}


def parse_source(value: str | None, camera: dict[str, Any] | None) -> Any:
    if value is not None:
        try:
            return int(value)
        except ValueError:
            return value
    if camera is None:
        return 0
    return camera.get("source", 0)


def sane_fps(raw_fps: float, fallback: float = 25.0) -> float:
    if not raw_fps or raw_fps < 1.0 or raw_fps > 120.0:
        return fallback
    return raw_fps


def open_capture(
    source: int | str,
    *,
    rtsp_transport: str = "tcp",
    rtsp_max_delay_ms: int = 500,
    rtsp_read_timeout_ms: int = 3000,
    rtsp_open_timeout_ms: int = 5000,
    capture_buffer_size: int = 1,
) -> cv2.VideoCapture:
    timeout_params = [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
        int(rtsp_open_timeout_ms),
        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
        int(rtsp_read_timeout_ms),
    ]
    if isinstance(source, int):
        capture = cv2.VideoCapture(source)
    else:
        max_delay_us = max(0, int(rtsp_max_delay_ms)) * 1000
        read_timeout_us = max(1, int(rtsp_read_timeout_ms)) * 1000
        transport = str(rtsp_transport or "tcp").lower()
        if transport not in {"tcp", "udp"}:
            transport = "tcp"
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            f"rtsp_transport;{transport}|stimeout;{read_timeout_us}|max_delay;{max_delay_us}|reorder_queue_size;1024"
        )
        try:
            capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG, timeout_params)
        except Exception:
            capture = cv2.VideoCapture(source)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, max(1, int(capture_buffer_size)))
    return capture


def open_writer(path: Path, codec: str, fps: float, size: tuple[int, int]) -> tuple[cv2.VideoWriter, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
    if writer.isOpened():
        return writer, path
    fallback = path.with_suffix(".avi")
    writer = cv2.VideoWriter(str(fallback), cv2.VideoWriter_fourcc(*"XVID"), fps, size)
    if not writer.isOpened():
        raise SystemExit("Could not open output video writer.")
    return writer, fallback


def bottom_center(box: list[float]) -> Point:
    x1, y1, x2, y2 = box
    return Point((x1 + x2) * 0.5, y2)


def point_distance(a: Point, b: Point) -> float:
    return float(((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5)


def normalize_embedding(value: np.ndarray | None) -> np.ndarray | None:
    if value is None:
        return None
    arr = np.asarray(value, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if not np.isfinite(norm) or norm <= 1e-6:
        return None
    return arr / norm


def cosine_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 0.0
    return float(np.dot(a, b))


def update_embedding(old: np.ndarray | None, new: np.ndarray | None, count: int, alpha: float) -> tuple[np.ndarray | None, int]:
    if new is None:
        return old, count
    if old is None:
        return new, 1
    blended = normalize_embedding((1.0 - alpha) * old + alpha * new)
    return blended, count + 1


def crop_detection(frame: np.ndarray, box: list[float], padding: float) -> np.ndarray | None:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    pad_x = bw * padding
    pad_y = bh * padding
    left = max(0, int(x1 - pad_x))
    top = max(0, int(y1 - pad_y))
    right = min(w, int(x2 + pad_x))
    bottom = min(h, int(y2 + pad_y))
    if right <= left or bottom <= top:
        return None
    return frame[top:bottom, left:right]


def detection_reject_reason(box: list[float], conf: float, args: argparse.Namespace) -> str | None:
    x1, y1, x2, y2 = box
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    aspect = height / width
    area = width * height
    if conf < args.conf:
        return "low_conf"
    if width < args.min_box_width:
        return "thin"
    if height < args.min_box_height:
        return "short"
    if area < args.min_box_area:
        return "small"
    if aspect < args.min_aspect:
        return "wide"
    if aspect > args.max_aspect:
        return "too_tall"
    return None


class AppearanceBackend:
    def __init__(self, args: argparse.Namespace) -> None:
        self.backend = args.reid_backend.lower()
        self.device = args.reid_device
        self.weights = args.reid_weights
        self.crop_padding = args.reid_crop_padding
        self.min_crop_height = args.reid_min_crop_height
        self.min_crop_width = args.reid_min_crop_width
        self.lock = threading.Lock()
        self.model: Any | None = None
        if self.backend == "boxmot":
            try:
                self.model = self._load_boxmot()
            except Exception as exc:
                self.backend = "histogram"
                print(f"BoxMOT ReID unavailable ({exc}); using histogram ReID backend.", flush=True)
            else:
                print(f"Loaded ReID backend: boxmot ({self.weights})", flush=True)
        elif self.backend == "histogram":
            print("Loaded ReID backend: histogram", flush=True)
        else:
            raise ValueError("Use --reid-backend boxmot or histogram.")

    def _load_boxmot(self) -> Any:
        from boxmot.reid.core.reid import ReID

        return ReID(weights=Path(self.weights), device=self.device, half=False)

    def extract_many(self, frame: np.ndarray, boxes: list[list[float]]) -> list[np.ndarray | None]:
        if self.backend == "boxmot":
            return self._extract_boxmot_many(frame, boxes)
        return [self._extract_histogram(frame, box) for box in boxes]

    def _extract_boxmot_many(self, frame: np.ndarray, boxes: list[list[float]]) -> list[np.ndarray | None]:
        out: list[np.ndarray | None] = [None] * len(boxes)
        crops: list[np.ndarray] = []
        indexes: list[int] = []
        for idx, box in enumerate(boxes):
            crop = crop_detection(frame, box, self.crop_padding)
            if crop is None:
                continue
            if crop.shape[0] < self.min_crop_height or crop.shape[1] < self.min_crop_width:
                continue
            crops.append(crop)
            indexes.append(idx)
        if not crops:
            return out
        with self.lock:
            if hasattr(self.model, "get_features"):
                feats = self.model.get_features(np.asarray(crops, dtype=object))
            else:
                try:
                    import torch
                except ImportError:
                    torch = None
                if torch is None:
                    feats = self.model(crops)
                else:
                    with torch.no_grad():
                        feats = self.model(crops)
        for idx, feat in zip(indexes, feats):
            out[idx] = normalize_embedding(np.asarray(feat, dtype=np.float32))
        return out

    def _extract_histogram(self, frame: np.ndarray, box: list[float]) -> np.ndarray | None:
        crop = crop_detection(frame, box, self.crop_padding)
        if crop is None:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 24], [0, 180, 0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        return normalize_embedding(hist)


class IdentityMemory:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.next_id = 1
        self.identities: dict[str, PersonIdentity] = {}
        self.tracks: dict[int, TrackState] = {}

    def _new_person_id(self) -> str:
        person_id = f"101-P{self.next_id:04d}"
        self.next_id += 1
        return person_id

    def mark_missing_tracks(self, live_tracker_ids: set[int], now: float) -> None:
        for identity in self.identities.values():
            if identity.active_tracker_id is None:
                continue
            if identity.active_tracker_id not in live_tracker_ids:
                identity.active_tracker_id = None
        ttl = self.args.memory_seconds
        for person_id in list(self.identities):
            if now - self.identities[person_id].last_seen > ttl:
                del self.identities[person_id]

    def update_track(self, det: Detection, now: float) -> tuple[str | None, str | None, float | None]:
        state = self.tracks.get(det.tracker_id)
        if state is None:
            state = TrackState(
                tracker_id=det.tracker_id,
                first_seen=now,
                last_seen=now,
                first_point=det.point,
                last_point=det.point,
            )
            self.tracks[det.tracker_id] = state
        state.frames_seen += 1
        state.last_seen = now
        state.max_displacement = max(state.max_displacement, point_distance(state.first_point, det.point))
        state.last_point = det.point
        state.embedding, state.embedding_count = update_embedding(
            state.embedding,
            det.embedding,
            state.embedding_count,
            self.args.track_embedding_alpha,
        )

        if state.person_id is None and state.frames_seen < self.args.min_frames_for_id:
            return None, None, None

        event: str | None = None
        event_score: float | None = None
        if state.person_id is None:
            matched_id, score = self._best_inactive_match(state.embedding, det.point, now)
            if matched_id is not None:
                state.person_id = matched_id
                event = "reid"
                event_score = score
            else:
                state.person_id = self._new_person_id()
                state.created_person_at = now
                self.identities[state.person_id] = PersonIdentity(
                    person_id=state.person_id,
                    created_at=now,
                    last_seen=now,
                    last_point=det.point,
                    embedding=state.embedding,
                    embedding_count=state.embedding_count,
                    active_tracker_id=det.tracker_id,
                )
                event = "new"
        elif self._is_probe_track(state, now):
            matched_id, score = self._best_inactive_match(state.embedding, det.point, now, exclude_id=state.person_id)
            if matched_id is not None:
                self._merge_identity(source_id=state.person_id, target_id=matched_id)
                state.person_id = matched_id
                event = "merge_reid"
                event_score = score

        identity = self.identities.get(state.person_id)
        if identity is None:
            identity = PersonIdentity(
                person_id=state.person_id,
                created_at=now,
                last_seen=now,
                last_point=det.point,
            )
            self.identities[state.person_id] = identity
        identity.last_seen = now
        identity.last_point = det.point
        identity.active_tracker_id = det.tracker_id
        identity.embedding, identity.embedding_count = update_embedding(
            identity.embedding,
            state.embedding,
            identity.embedding_count,
            self.args.identity_embedding_alpha,
        )
        return state.person_id, event, event_score

    def _is_probe_track(self, state: TrackState, now: float) -> bool:
        if state.person_id is None or state.created_person_at is None:
            return False
        return state.frames_seen <= self.args.probe_frames or now - state.created_person_at <= self.args.probe_seconds

    def _best_inactive_match(
        self,
        embedding: np.ndarray | None,
        point: Point,
        now: float,
        exclude_id: str | None = None,
    ) -> tuple[str | None, float | None]:
        if embedding is None:
            return None, None
        candidates: list[tuple[str, float]] = []
        for person_id, identity in self.identities.items():
            if person_id == exclude_id:
                continue
            if identity.embedding is None:
                continue
            if identity.active_tracker_id is not None and now - identity.last_seen <= self.args.active_grace_seconds:
                continue
            age = now - identity.last_seen
            if age > self.args.memory_seconds:
                continue
            appearance = cosine_similarity(embedding, identity.embedding)
            if appearance < self.args.reid_threshold:
                continue
            distance = point_distance(point, identity.last_point)
            spatial_bonus = max(0.0, 1.0 - distance / max(1.0, self.args.spatial_bonus_radius))
            age_penalty = min(0.10, age / max(1.0, self.args.memory_seconds) * 0.10)
            score = appearance + spatial_bonus * self.args.spatial_bonus_weight - age_penalty
            candidates.append((person_id, score))
        if not candidates:
            return None, None
        candidates.sort(key=lambda item: item[1], reverse=True)
        best_id, best_score = candidates[0]
        second_score = candidates[1][1] if len(candidates) > 1 else -1.0
        if best_score - second_score < self.args.reid_margin:
            return None, None
        return best_id, best_score

    def _merge_identity(self, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            return
        source = self.identities.pop(source_id, None)
        target = self.identities.get(target_id)
        if source is None or target is None:
            return
        target.embedding, target.embedding_count = update_embedding(
            target.embedding,
            source.embedding,
            target.embedding_count,
            self.args.identity_embedding_alpha,
        )
        for state in self.tracks.values():
            if state.person_id == source_id:
                state.person_id = target_id


def draw_label(frame: np.ndarray, text: str, origin: tuple[int, int], color: tuple[int, int, int]) -> None:
    cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="101-only person detection, tracking, and per-camera ReID")
    p.add_argument("--camera-id", default="cam_101", help="This script is intended for cam_101.")
    p.add_argument("--cameras-file", default="camera_config/cameras.json")
    p.add_argument("--source", default=None, help="Override source: webcam index, video path, RTSP URL, etc.")
    p.add_argument("--model", default="model weights/yolov8s.pt", help="Person detector weights. Use a larger model if speed allows.")
    p.add_argument("--tracker", default="botsort.yaml")
    p.add_argument("--imgsz", type=int, default=768)
    p.add_argument("--conf", type=float, default=0.60)
    p.add_argument("--iou", type=float, default=0.50)
    p.add_argument("--device", default="0", help="Use 0 for GPU or cpu for CPU.")
    p.add_argument("--max-det", type=int, default=15)
    p.add_argument("--half", action="store_true", default=True)
    p.add_argument("--no-half", action="store_false", dest="half")
    p.add_argument("--min-box-height", type=float, default=95.0)
    p.add_argument("--min-box-width", type=float, default=30.0)
    p.add_argument("--min-box-area", type=float, default=4500.0)
    p.add_argument("--min-aspect", type=float, default=1.15, help="Minimum height/width ratio.")
    p.add_argument("--max-aspect", type=float, default=5.2, help="Maximum height/width ratio.")
    p.add_argument("--min-frames-for-id", type=int, default=4)
    p.add_argument("--embedding-interval", type=int, default=6)
    p.add_argument("--reid-backend", default="boxmot", choices=["boxmot", "histogram"])
    p.add_argument("--reid-weights", default="model weights/osnet_x0_25_msmt17.pt")
    p.add_argument("--reid-device", default="cuda:0")
    p.add_argument("--reid-threshold", type=float, default=0.72)
    p.add_argument("--reid-margin", type=float, default=0.06)
    p.add_argument("--reid-crop-padding", type=float, default=0.12)
    p.add_argument("--reid-min-crop-height", type=int, default=32)
    p.add_argument("--reid-min-crop-width", type=int, default=16)
    p.add_argument("--track-embedding-alpha", type=float, default=0.35)
    p.add_argument("--identity-embedding-alpha", type=float, default=0.20)
    p.add_argument("--memory-seconds", type=float, default=300.0)
    p.add_argument("--active-grace-seconds", type=float, default=1.0)
    p.add_argument("--probe-frames", type=int, default=45)
    p.add_argument("--probe-seconds", type=float, default=3.0)
    p.add_argument("--spatial-bonus-radius", type=float, default=180.0)
    p.add_argument("--spatial-bonus-weight", type=float, default=0.06)
    p.add_argument("--show-rejected", action="store_true")
    p.add_argument("--save-video", action="store_true", default=True)
    p.add_argument("--no-save-video", action="store_false", dest="save_video")
    p.add_argument("--output-video", default="outputs/person_reid/person_101_reid.mp4")
    p.add_argument("--tracks-csv", default="outputs/metrics/person_101_reid_tracks.csv")
    p.add_argument("--events-csv", default="outputs/metrics/person_101_reid_events.csv")
    p.add_argument("--codec", default="mp4v")
    p.add_argument("--no-show", action="store_true")
    return p.parse_args()


def run(args: argparse.Namespace) -> None:
    if args.camera_id != "cam_101":
        raise SystemExit("This script is intentionally 101-only. Use --camera-id cam_101.")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit('Missing dependency: pip install "ultralytics>=8.0.0"') from exc

    cameras = load_cameras(Path(args.cameras_file))
    camera = cameras.get(args.camera_id)
    source = parse_source(args.source, camera)
    cap = open_capture(source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source: {source}")

    model = YOLO(args.model)
    appearance = AppearanceBackend(args)
    memory = IdentityMemory(args)

    fps = sane_fps(cap.get(cv2.CAP_PROP_FPS))
    window_name = "Person 101 ReID"
    if not args.no_show:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    tracks_path = Path(args.tracks_csv)
    events_path = Path(args.events_csv)
    tracks_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    tracks_file = tracks_path.open("w", newline="", encoding="utf-8")
    events_file = events_path.open("w", newline="", encoding="utf-8")
    tracks_writer = csv.DictWriter(
        tracks_file,
        fieldnames=[
            "frame_index",
            "time_seconds",
            "camera_id",
            "person_id",
            "tracker_id",
            "confidence",
            "x1",
            "y1",
            "x2",
            "y2",
            "cx",
            "cy",
        ],
    )
    events_writer = csv.DictWriter(
        events_file,
        fieldnames=["frame_index", "time_seconds", "camera_id", "event", "person_id", "tracker_id", "score", "cx", "cy"],
    )
    tracks_writer.writeheader()
    events_writer.writeheader()

    writer: cv2.VideoWriter | None = None
    output_video = Path(args.output_video)
    frame_idx = 0
    last_tick = time.monotonic()
    last_tick_frame = 0
    display_fps = 0.0
    start_time = time.monotonic()

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                if (cv2.waitKey(250) & 0xFF) in (ord("q"), 27):
                    break
                continue

            frame_idx += 1
            now = time.monotonic()
            elapsed = now - start_time
            if args.save_video and writer is None:
                h, w = frame.shape[:2]
                writer, output_video = open_writer(output_video, args.codec, fps, (w, h))

            results = model.track(
                frame,
                persist=True,
                tracker=args.tracker,
                classes=[0],
                conf=args.conf,
                iou=args.iou,
                imgsz=args.imgsz,
                device=args.device,
                half=args.half and args.device != "cpu",
                max_det=args.max_det,
                verbose=False,
            )

            accepted: list[Detection] = []
            rejected: list[Detection] = []
            result = results[0] if results else None
            if result is not None and result.boxes is not None and result.boxes.id is not None:
                boxes = result.boxes.xyxy.cpu().numpy()
                ids = result.boxes.id.cpu().numpy().astype(int)
                confs = result.boxes.conf.cpu().numpy()
                for box_arr, tracker_id, conf in zip(boxes, ids, confs):
                    box = [float(v) for v in box_arr.tolist()]
                    point = bottom_center(box)
                    reason = detection_reject_reason(box, float(conf), args)
                    det = Detection(tracker_id=int(tracker_id), box=box, confidence=float(conf), point=point, rejected_reason=reason)
                    if reason is None:
                        accepted.append(det)
                    else:
                        rejected.append(det)

            embed_boxes: list[list[float]] = []
            embed_indexes: list[int] = []
            for idx, det in enumerate(accepted):
                state = memory.tracks.get(det.tracker_id)
                due = state is None or frame_idx % max(1, args.embedding_interval) == 0 or state.embedding is None
                if due:
                    embed_boxes.append(det.box)
                    embed_indexes.append(idx)
            embeddings = appearance.extract_many(frame, embed_boxes) if embed_boxes else []
            for det_idx, embedding in zip(embed_indexes, embeddings):
                accepted[det_idx].embedding = embedding

            live_ids = {det.tracker_id for det in accepted}
            memory.mark_missing_tracks(live_ids, now)

            for det in accepted:
                person_id, event, score = memory.update_track(det, now)
                x1, y1, x2, y2 = [int(round(v)) for v in det.box]
                color = (60, 220, 60) if person_id else (180, 180, 180)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
                label = f"{person_id or 'pending'} trk:{det.tracker_id} {det.confidence:.2f}"
                draw_label(frame, label, (x1, max(18, y1 - 8)), color)
                cv2.circle(frame, (int(det.point.x), int(det.point.y)), 4, color, -1, cv2.LINE_AA)
                tracks_writer.writerow(
                    {
                        "frame_index": frame_idx,
                        "time_seconds": f"{elapsed:.3f}",
                        "camera_id": args.camera_id,
                        "person_id": person_id or "",
                        "tracker_id": det.tracker_id,
                        "confidence": f"{det.confidence:.4f}",
                        "x1": f"{det.box[0]:.1f}",
                        "y1": f"{det.box[1]:.1f}",
                        "x2": f"{det.box[2]:.1f}",
                        "y2": f"{det.box[3]:.1f}",
                        "cx": f"{det.point.x:.1f}",
                        "cy": f"{det.point.y:.1f}",
                    }
                )
                if person_id and event:
                    events_writer.writerow(
                        {
                            "frame_index": frame_idx,
                            "time_seconds": f"{elapsed:.3f}",
                            "camera_id": args.camera_id,
                            "event": event,
                            "person_id": person_id,
                            "tracker_id": det.tracker_id,
                            "score": "" if score is None else f"{score:.4f}",
                            "cx": f"{det.point.x:.1f}",
                            "cy": f"{det.point.y:.1f}",
                        }
                    )
                    events_file.flush()

            if args.show_rejected:
                for det in rejected:
                    x1, y1, x2, y2 = [int(round(v)) for v in det.box]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (80, 80, 80), 1, cv2.LINE_AA)
                    draw_label(frame, det.rejected_reason or "rejected", (x1, max(18, y1 - 8)), (120, 120, 120))

            if now - last_tick >= 0.5:
                frames_delta = frame_idx - last_tick_frame
                display_fps = frames_delta / max(1e-6, now - last_tick)
                last_tick = now
                last_tick_frame = frame_idx
            status = f"cam_101 accepted:{len(accepted)} rejected:{len(rejected)} ids:{len(memory.identities)} fps:{display_fps:.1f}"
            draw_label(frame, status, (12, 26), (235, 235, 235))

            if writer is not None:
                writer.write(frame)
            if not args.no_show:
                cv2.imshow(window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break

            if frame_idx % 30 == 0:
                tracks_file.flush()
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        tracks_file.close()
        events_file.close()
        if not args.no_show:
            cv2.destroyAllWindows()
        print(f"Tracks CSV: {tracks_path}", flush=True)
        print(f"Events CSV: {events_path}", flush=True)
        if args.save_video:
            print(f"Video: {output_video}", flush=True)


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
