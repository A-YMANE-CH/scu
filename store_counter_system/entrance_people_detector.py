from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2

from person_101_reid import load_cameras, open_capture, parse_source, sane_fps
from retail_dashboard_core import apply_rtsp_channel, draw_label, encode_jpeg


SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class EntranceGeometry:
    camera_id: str
    roi: tuple[float, float, float, float]
    line: tuple[float, float, float, float]
    direction_axis: str
    enter_direction: int
    min_box_height_ratio: float
    min_box_area_ratio: float
    reflection_zone: tuple[float, float, float, float] | None = None


@dataclass
class TrackHistory:
    tracker_id: int
    first_frame: int
    last_frame: int
    first_time: float
    last_time: float
    first_side: int | None = None
    last_side: int | None = None
    previous_side: int | None = None
    transition_from_side: int | None = None
    transition_to_side: int | None = None
    first_point: tuple[float, float] | None = None
    last_point: tuple[float, float] | None = None
    frames_seen: int = 0
    inside_hits: int = 0
    outside_hits: int = 0
    counted: bool = False
    exit_counted: bool = False
    max_confidence: float = 0.0
    last_box: list[float] = field(default_factory=list)


@dataclass
class CameraRuntime:
    camera_id: str
    source: Any
    capture: cv2.VideoCapture
    model: Any
    geometry: EntranceGeometry
    fps: float
    frame_index: int = 0
    tracks: dict[int, TrackHistory] = field(default_factory=dict)
    event_count: int = 0


DEFAULT_GEOMETRIES: dict[str, EntranceGeometry] = {
    # 201 is the primary view. People enter by crossing downward from the back doorway
    # into the selling floor.
    "cam_201": EntranceGeometry(
        camera_id="cam_201",
        roi=(0.20, 0.03, 0.47, 0.46),
        line=(0.22, 0.34, 0.47, 0.34),
        direction_axis="y",
        enter_direction=1,
        min_box_height_ratio=0.08,
        min_box_area_ratio=0.0020,
    ),
    # 501 is mounted above the door. The glass side can create reflections, so detections
    # mostly contained in the right reflection band are ignored.
    "cam_501": EntranceGeometry(
        camera_id="cam_501",
        roi=(0.53, 0.28, 0.86, 1.00),
        line=(0.68, 0.40, 0.68, 1.00),
        direction_axis="x",
        enter_direction=-1,
        min_box_height_ratio=0.11,
        min_box_area_ratio=0.0030,
        reflection_zone=(0.73, 0.00, 1.00, 1.00),
    ),
}


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path
    return SCRIPT_DIR / path


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


def denorm_box(box: tuple[float, float, float, float], shape: tuple[int, int]) -> tuple[int, int, int, int]:
    h, w = shape[:2]
    x1, y1, x2, y2 = box
    return (
        int(round(x1 * w)),
        int(round(y1 * h)),
        int(round(x2 * w)),
        int(round(y2 * h)),
    )


def denorm_line(line: tuple[float, float, float, float], shape: tuple[int, int]) -> tuple[int, int, int, int]:
    h, w = shape[:2]
    x1, y1, x2, y2 = line
    return (
        int(round(x1 * w)),
        int(round(y1 * h)),
        int(round(x2 * w)),
        int(round(y2 * h)),
    )


def bottom_center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2]) * 0.5, box[3]


def point_inside_box(point: tuple[float, float], box: tuple[int, int, int, int]) -> bool:
    x, y = point
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def side_of_line(point: tuple[float, float], geometry: EntranceGeometry, frame_shape: tuple[int, int]) -> int:
    x1, y1, x2, y2 = denorm_line(geometry.line, frame_shape)
    x, y = point
    value = (y - y1) if geometry.direction_axis == "y" else (x - x1)
    if abs(value) <= 2.0:
        return 0
    return 1 if value > 0 else -1


def box_overlap_fraction(a: list[float], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    return inter / area


def detection_is_usable(
    box: list[float],
    confidence: float,
    frame_shape: tuple[int, int],
    geometry: EntranceGeometry,
    args: argparse.Namespace,
) -> bool:
    h, w = frame_shape[:2]
    width = max(1.0, box[2] - box[0])
    height = max(1.0, box[3] - box[1])
    if confidence < args.conf:
        return False
    if height < h * geometry.min_box_height_ratio:
        return False
    if (width * height) < (w * h) * geometry.min_box_area_ratio:
        return False
    point = bottom_center(box)
    if not point_inside_box(point, denorm_box(geometry.roi, frame_shape)):
        return False
    if geometry.reflection_zone is not None:
        reflection_box = denorm_box(geometry.reflection_zone, frame_shape)
        if box_overlap_fraction(box, reflection_box) >= args.reflection_overlap_reject:
            return False
    return True


def crossed_entering(history: TrackHistory, geometry: EntranceGeometry, args: argparse.Namespace) -> bool:
    if history.counted:
        return False
    if history.frames_seen < args.min_track_frames:
        return False
    if history.outside_hits < args.min_outside_frames or history.inside_hits < args.min_inside_frames:
        return False
    if history.first_side is None or history.last_side is None:
        return False
    outside_side = -geometry.enter_direction
    return history.first_side == outside_side and history.last_side == geometry.enter_direction


def update_history(
    camera: CameraRuntime,
    tracker_id: int,
    box: list[float],
    confidence: float,
    elapsed: float,
    args: argparse.Namespace,
) -> TrackHistory:
    point = bottom_center(box)
    side = side_of_line(point, camera.geometry, camera.last_frame_shape)
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
    history.last_point = point
    history.last_box = box
    history.max_confidence = max(history.max_confidence, confidence)
    if history.first_point is None:
        history.first_point = point
    if side != 0:
        if history.first_side is None:
            history.first_side = side
        history.last_side = side
        if side == camera.geometry.enter_direction:
            history.inside_hits += 1
        else:
            history.outside_hits += 1
    return history


def prune_tracks(camera: CameraRuntime, max_missing_frames: int) -> None:
    cutoff = camera.frame_index - max_missing_frames
    for tracker_id in list(camera.tracks):
        if camera.tracks[tracker_id].last_frame < cutoff:
            del camera.tracks[tracker_id]


def draw_overlay(frame: Any, camera: CameraRuntime, detections: list[dict[str, Any]], display_fps: float) -> None:
    roi = denorm_box(camera.geometry.roi, frame.shape[:2])
    line = denorm_line(camera.geometry.line, frame.shape[:2])
    cv2.rectangle(frame, roi[:2], roi[2:], (255, 190, 60), 2, cv2.LINE_AA)
    cv2.line(frame, line[:2], line[2:], (0, 220, 255), 3, cv2.LINE_AA)
    if camera.geometry.reflection_zone is not None:
        reflection = denorm_box(camera.geometry.reflection_zone, frame.shape[:2])
        cv2.rectangle(frame, reflection[:2], reflection[2:], (80, 80, 220), 1, cv2.LINE_AA)
    for det in detections:
        box = [int(round(v)) for v in det["box"]]
        color = (60, 220, 60) if det["usable"] else (80, 80, 80)
        cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), color, 2 if det["usable"] else 1, cv2.LINE_AA)
        draw_label(
            frame,
            f"id:{det['tracker_id']} {det['confidence']:.2f}",
            (box[0], max(18, box[1] - 8)),
            color,
        )
    draw_label(
        frame,
        f"{camera.camera_id} entries:{camera.event_count} tracks:{len(camera.tracks)} fps:{display_fps:.1f}",
        (12, 28),
        (235, 235, 235),
    )


def load_geometries(path: Path | None) -> dict[str, EntranceGeometry]:
    geometries = dict(DEFAULT_GEOMETRIES)
    if path is None or not path.exists():
        return geometries
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("entrance_geometries", []):
        camera_id = str(item["camera_id"])
        geometries[camera_id] = EntranceGeometry(
            camera_id=camera_id,
            roi=tuple(float(v) for v in item["roi"]),
            line=tuple(float(v) for v in item["line"]),
            direction_axis=str(item["direction_axis"]),
            enter_direction=int(item["enter_direction"]),
            min_box_height_ratio=float(item.get("min_box_height_ratio", 0.08)),
            min_box_area_ratio=float(item.get("min_box_area_ratio", 0.002)),
            reflection_zone=tuple(float(v) for v in item["reflection_zone"]) if item.get("reflection_zone") else None,
        )
    return geometries


def open_camera_runtime(
    camera_id: str,
    source: Any,
    geometry: EntranceGeometry,
    args: argparse.Namespace,
) -> CameraRuntime:
    from ultralytics import YOLO

    capture = open_capture(
        source,
        rtsp_max_delay_ms=args.rtsp_max_delay_ms,
        rtsp_read_timeout_ms=args.rtsp_read_timeout_ms,
        capture_buffer_size=args.capture_buffer_size,
    )
    if not capture.isOpened():
        raise SystemExit(f"Could not open source for {camera_id}: {source}")
    model = YOLO(str(resolve_project_path(args.model)))
    return CameraRuntime(
        camera_id=camera_id,
        source=source,
        capture=capture,
        model=model,
        geometry=geometry,
        fps=sane_fps(capture.get(cv2.CAP_PROP_FPS)),
    )


def camera_source(camera_id: str, cameras: dict[str, Any], video_sources: dict[str, str], args: argparse.Namespace) -> Any:
    if camera_id in video_sources:
        return str(resolve_project_path(video_sources[camera_id]))
    source = parse_source(args.source, cameras.get(camera_id))
    if args.rtsp_channel:
        source = apply_rtsp_channel(source, args.rtsp_channel)
    return source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect people entering through the store entrance from cameras 201 and 501.")
    parser.add_argument("--cameras-file", default="camera_config/cameras.json")
    parser.add_argument("--camera-ids", nargs="+", default=["cam_201", "cam_501"])
    parser.add_argument("--source", default=None, help="Override source for all selected cameras.")
    parser.add_argument("--camera-video", nargs="*", default=[], help="Use local videos, e.g. cam_201=demo.mp4 cam_501=door.mp4")
    parser.add_argument("--geometry-file", default="", help="Optional JSON file overriding normalized entrance geometries.")
    parser.add_argument("--rtsp-channel", default=None)
    parser.add_argument("--rtsp-max-delay-ms", type=int, default=500)
    parser.add_argument("--rtsp-read-timeout-ms", type=int, default=3000)
    parser.add_argument("--capture-buffer-size", type=int, default=1)
    parser.add_argument("--model", default="model weights/yolov8n.pt")
    parser.add_argument("--tracker", default="botsort.yaml")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.42)
    parser.add_argument("--iou", type=float, default=0.50)
    parser.add_argument("--device", default="0")
    parser.add_argument("--half", action="store_true", default=True)
    parser.add_argument("--no-half", action="store_false", dest="half")
    parser.add_argument("--max-det", type=int, default=20)
    parser.add_argument("--min-track-frames", type=int, default=3)
    parser.add_argument("--min-outside-frames", type=int, default=1)
    parser.add_argument("--min-inside-frames", type=int, default=2)
    parser.add_argument("--max-missing-frames", type=int, default=45)
    parser.add_argument("--reflection-overlap-reject", type=float, default=0.65)
    parser.add_argument("--events-csv", default="outputs/metrics/entrance_entries.csv")
    parser.add_argument("--tracks-csv", default="outputs/metrics/entrance_tracks.csv")
    parser.add_argument("--save-video", action="store_true", default=False)
    parser.add_argument("--video-dir", default="outputs/entrance")
    parser.add_argument("--codec", default="mp4v")
    parser.add_argument("--show", action="store_true", default=False)
    parser.add_argument("--jpeg-dir", default="", help="Optional folder where the latest annotated frame per camera is written.")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after this many frames per camera. Use 0 to run continuously.")
    return parser.parse_args()


def run(args: argparse.Namespace) -> None:
    cameras = load_cameras(resolve_project_path(args.cameras_file))
    geometries = load_geometries(resolve_project_path(args.geometry_file) if args.geometry_file else None)
    video_sources = parse_camera_video_sources(args.camera_video)

    runtimes: list[CameraRuntime] = []
    for camera_id in args.camera_ids:
        if camera_id not in geometries:
            raise SystemExit(f"No entrance geometry configured for {camera_id}")
        source = camera_source(camera_id, cameras, video_sources, args)
        runtimes.append(open_camera_runtime(camera_id, source, geometries[camera_id], args))

    events_path = resolve_project_path(args.events_csv)
    tracks_path = resolve_project_path(args.tracks_csv)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    tracks_path.parent.mkdir(parents=True, exist_ok=True)
    video_dir = resolve_project_path(args.video_dir)
    jpeg_dir = resolve_project_path(args.jpeg_dir) if args.jpeg_dir else None
    if jpeg_dir is not None:
        jpeg_dir.mkdir(parents=True, exist_ok=True)

    events_file = events_path.open("w", newline="", encoding="utf-8")
    tracks_file = tracks_path.open("w", newline="", encoding="utf-8")
    events_writer = csv.DictWriter(
        events_file,
        fieldnames=[
            "event_id",
            "time_seconds",
            "camera_id",
            "tracker_id",
            "confidence",
            "first_frame",
            "last_frame",
            "x1",
            "y1",
            "x2",
            "y2",
            "entry_count_camera",
        ],
    )
    tracks_writer = csv.DictWriter(
        tracks_file,
        fieldnames=["time_seconds", "camera_id", "frame_index", "tracker_id", "confidence", "usable", "x1", "y1", "x2", "y2", "cx", "cy"],
    )
    events_writer.writeheader()
    tracks_writer.writeheader()

    writers: dict[str, cv2.VideoWriter] = {}
    start = time.monotonic()
    last_tick = time.monotonic()
    last_frames = {camera.camera_id: 0 for camera in runtimes}
    display_fps = {camera.camera_id: 0.0 for camera in runtimes}

    try:
        while True:
            any_frame = False
            for camera in runtimes:
                ok, frame = camera.capture.read()
                if not ok or frame is None:
                    continue
                any_frame = True
                camera.frame_index += 1
                camera.last_frame_shape = frame.shape[:2]
                elapsed = time.monotonic() - start

                results = camera.model.track(
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

                detections: list[dict[str, Any]] = []
                result = results[0] if results else None
                if result is not None and result.boxes is not None and result.boxes.id is not None:
                    boxes = result.boxes.xyxy.cpu().numpy()
                    ids = result.boxes.id.cpu().numpy().astype(int)
                    confs = result.boxes.conf.cpu().numpy()
                    for box_arr, tracker_id, conf in zip(boxes, ids, confs):
                        box = [float(v) for v in box_arr.tolist()]
                        usable = detection_is_usable(box, float(conf), frame.shape[:2], camera.geometry, args)
                        detections.append({"box": box, "tracker_id": int(tracker_id), "confidence": float(conf), "usable": usable})
                        point = bottom_center(box)
                        tracks_writer.writerow(
                            {
                                "time_seconds": f"{elapsed:.3f}",
                                "camera_id": camera.camera_id,
                                "frame_index": camera.frame_index,
                                "tracker_id": int(tracker_id),
                                "confidence": f"{float(conf):.4f}",
                                "usable": int(usable),
                                "x1": f"{box[0]:.1f}",
                                "y1": f"{box[1]:.1f}",
                                "x2": f"{box[2]:.1f}",
                                "y2": f"{box[3]:.1f}",
                                "cx": f"{point[0]:.1f}",
                                "cy": f"{point[1]:.1f}",
                            }
                        )
                        if not usable:
                            continue
                        history = update_history(camera, int(tracker_id), box, float(conf), elapsed, args)
                        if crossed_entering(history, camera.geometry, args):
                            history.counted = True
                            camera.event_count += 1
                            event_id = f"{camera.camera_id}-{camera.event_count:06d}"
                            events_writer.writerow(
                                {
                                    "event_id": event_id,
                                    "time_seconds": f"{elapsed:.3f}",
                                    "camera_id": camera.camera_id,
                                    "tracker_id": int(tracker_id),
                                    "confidence": f"{history.max_confidence:.4f}",
                                    "first_frame": history.first_frame,
                                    "last_frame": history.last_frame,
                                    "x1": f"{box[0]:.1f}",
                                    "y1": f"{box[1]:.1f}",
                                    "x2": f"{box[2]:.1f}",
                                    "y2": f"{box[3]:.1f}",
                                    "entry_count_camera": camera.event_count,
                                }
                            )
                            events_file.flush()
                            print(f"[entry] {event_id} tracker={tracker_id} t={elapsed:.2f}s", flush=True)
                prune_tracks(camera, args.max_missing_frames)

                now = time.monotonic()
                if now - last_tick >= 1.0:
                    for item in runtimes:
                        frames_delta = item.frame_index - last_frames[item.camera_id]
                        display_fps[item.camera_id] = frames_delta / max(1e-6, now - last_tick)
                        last_frames[item.camera_id] = item.frame_index
                    last_tick = now

                draw_overlay(frame, camera, detections, display_fps[camera.camera_id])

                if args.save_video:
                    writer = writers.get(camera.camera_id)
                    if writer is None:
                        video_dir.mkdir(parents=True, exist_ok=True)
                        h, w = frame.shape[:2]
                        video_path = video_dir / f"{camera.camera_id}_entrance.mp4"
                        writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*args.codec), camera.fps, (w, h))
                        if not writer.isOpened():
                            raise SystemExit(f"Could not open video writer: {video_path}")
                        writers[camera.camera_id] = writer
                    writer.write(frame)

                if jpeg_dir is not None:
                    jpeg = encode_jpeg(frame, 82)
                    if jpeg:
                        (jpeg_dir / f"{camera.camera_id}_latest.jpg").write_bytes(jpeg)

                if args.show:
                    cv2.imshow(camera.camera_id, frame)

            if args.max_frames > 0 and all(camera.frame_index >= args.max_frames for camera in runtimes):
                break
            if args.show and (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                break
            if not any_frame:
                time.sleep(0.02)
    finally:
        for camera in runtimes:
            camera.capture.release()
        for writer in writers.values():
            writer.release()
        events_file.close()
        tracks_file.close()
        if args.show:
            cv2.destroyAllWindows()
        print(f"Entry events CSV: {events_path}", flush=True)
        print(f"Track CSV: {tracks_path}", flush=True)


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
