from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path


READ_ATTEMPTS = 3
READ_RETRY_SECONDS = 1.0

CENTRAL_FIELDS = ["store_id", "store_name", "date", "time", "number"]
DAILY_FIELDS = ["store_id", "store_name", "date", "number"]

HEALTH_FIELDS = [
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


def read_rows(path: Path, fields: list[str]) -> list[dict[str, str]]:
    last_error: OSError | None = None
    for attempt in range(READ_ATTEMPTS):
        try:
            if not path.exists() or path.stat().st_size == 0:
                return []
            with path.open("r", newline="", encoding="utf-8-sig") as file:
                return [{field: str(row.get(field, "")) for field in fields} for row in csv.DictReader(file)]
        except OSError as exc:
            last_error = exc
            if attempt < READ_ATTEMPTS - 1:
                time.sleep(READ_RETRY_SECONDS)
    if last_error is not None:
        raise last_error
    return []


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def input_patterns(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def is_merge_artifact(path: Path, output_path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".tmp") or "all_stores" in name:
        return True
    try:
        if path.resolve() == output_path.resolve():
            return True
    except OSError:
        return False
    return False


def discover_files(input_dir: Path, pattern: str, recursive: bool) -> list[Path]:
    files: list[Path] = []
    for one_pattern in input_patterns(pattern):
        files.extend(input_dir.rglob(one_pattern) if recursive else input_dir.glob(one_pattern))
    return sorted(files)


def log_line(args: argparse.Namespace, message: str) -> None:
    text = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(text, flush=True)
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write(text + "\n")


def merge_many(
    args: argparse.Namespace,
    input_dirs: list[Path],
    pattern: str,
    output_path: Path,
    fields: list[str],
    sort_fields: list[str],
    label: str,
) -> None:
    rows: list[dict[str, str]] = []
    seen_paths: set[Path] = set()
    matched_files: list[Path] = []
    read_ok_files = 0
    read_errors = 0
    for input_dir in input_dirs:
        if not input_dir.exists():
            log_line(args, f"[{label}] missing input folder: {input_dir}")
            continue
        for one_pattern in input_patterns(pattern):
            for path in discover_files(input_dir, one_pattern, args.recursive):
                try:
                    resolved = path.resolve()
                except OSError as exc:
                    read_errors += 1
                    log_line(args, f"[{label}] skipped unavailable path: {path} ({type(exc).__name__}: {exc})")
                    continue
                if resolved in seen_paths or is_merge_artifact(path, output_path):
                    continue
                if not path.is_file():
                    continue
                seen_paths.add(resolved)
                matched_files.append(path)
                try:
                    file_rows = read_rows(path, fields)
                except (OSError, csv.Error, UnicodeDecodeError) as exc:
                    read_errors += 1
                    log_line(args, f"[{label}] skipped unreadable file: {path} ({type(exc).__name__}: {exc})")
                    continue
                read_ok_files += 1
                rows.extend(file_rows)
                log_line(args, f"[{label}] {len(file_rows)} rows <- {path}")
    if read_errors and read_ok_files == 0:
        log_line(args, f"[{label}] no readable input files; keeping previous output -> {output_path}")
        return
    rows.sort(key=lambda row: tuple(row.get(field, "") for field in sort_fields))
    write_rows(output_path, fields, rows)
    log_line(args, f"[{label}] wrote {len(rows)} rows from {read_ok_files} files -> {output_path}")


def run_once(args: argparse.Namespace) -> None:
    input_dirs = [Path(value) for value in (args.input_dir or ["outputs/exports"])]
    output_dir = Path(args.output_dir)

    merge_many(
        args,
        input_dirs,
        args.central_pattern,
        output_dir / args.central_output,
        CENTRAL_FIELDS,
        ["date", "time", "store_id"],
        "entries",
    )
    merge_many(
        args,
        input_dirs,
        args.daily_pattern,
        output_dir / args.daily_output,
        DAILY_FIELDS,
        ["date", "store_id"],
        "daily",
    )
    merge_many(
        args,
        input_dirs,
        args.health_pattern,
        output_dir / args.health_output,
        HEALTH_FIELDS,
        ["date", "store_id", "row_type", "reported_at"],
        "health",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge per-store Google Drive CSV exports into supervisor-facing CSV files.")
    parser.add_argument("--input-dir", action="append", default=None, help="Folder containing per-store CSV exports. Can be repeated.")
    parser.add_argument("--output-dir", default="outputs/exports")
    parser.add_argument("--central-pattern", default="central_entries*.csv")
    parser.add_argument("--daily-pattern", default="daily_entries*.csv")
    parser.add_argument("--health-pattern", default="store_health*.csv,health*.csv")
    parser.add_argument("--central-output", default="entries/entries.csv")
    parser.add_argument("--daily-output", default="entries/daily_entries.csv")
    parser.add_argument("--health-output", default="health/health.csv")
    parser.add_argument("--recursive", action="store_true", default=True, help="Scan input folders recursively.")
    parser.add_argument("--no-recursive", action="store_false", dest="recursive")
    parser.add_argument("--log-file", default="outputs/exports/merge_status.log")
    parser.add_argument("--watch", action="store_true", help="Keep merging periodically.")
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.watch:
        while True:
            run_once(args)
            time.sleep(max(5.0, float(args.interval_seconds)))
    run_once(args)


if __name__ == "__main__":
    main()
