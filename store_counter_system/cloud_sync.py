"""Background upload of store events and health reports to Google Apps Script.

Local CSV files remain the source of truth. This module mirrors rows to a
central Apps Script endpoint when configured, and it never blocks the camera loop.

Rows are batched by default so large deployments do not create one Apps Script
request per entry or health sample.

Configuration can be provided with environment variables:

  STORE_COUNTER_APPS_SCRIPT_URL
  STORE_COUNTER_APPS_SCRIPT_SECRET
  STORE_COUNTER_CLOUD_BATCH_SECONDS optional, defaults to 600

or with ``cloud_config.json`` next to this file:

  {
    "appscript_url": "https://script.google.com/macros/s/.../exec",
    "appscript_secret": "shared-secret",
    "batch_seconds": 600
  }
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_FILENAME = "cloud_config.json"
DEFAULT_BATCH_SECONDS = 600.0
INSTANT_HEALTH_STATUSES = {"critical", "offline"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _device_key(row: dict[str, Any]) -> str:
    return f"{row.get('store_id') or 'unknown'}|{row.get('pc_name') or 'unknown'}"


class CloudSync:
    """Asynchronous Apps Script uploader for batched entry and health rows."""

    def __init__(
        self,
        url: str | None,
        secret: str | None,
        batch_seconds: float = DEFAULT_BATCH_SECONDS,
        max_queue: int = 10000,
        timeout: float = 20.0,
        max_retries: int = 5,
    ) -> None:
        self.url = (url or "").strip()
        self.secret = (secret or "").strip()
        self.batch_seconds = max(10.0, float(batch_seconds or DEFAULT_BATCH_SECONDS))
        self.timeout = timeout
        self.max_retries = max_retries
        self._enabled = bool(self.url and self.secret)
        self._queue: "queue.Queue[dict[str, Any] | None]" = queue.Queue(maxsize=max_queue)
        self._flush_now = threading.Event()
        self._worker: threading.Thread | None = None
        self._dropped = 0
        self._sent_batches = 0
        self._sent_rows = 0
        self._warned_full = False
        self._instant_status_by_device: dict[str, str] = {}

    @classmethod
    def from_config(cls, base_dir: str | Path | None = None) -> "CloudSync":
        url = os.environ.get("STORE_COUNTER_APPS_SCRIPT_URL")
        secret = os.environ.get("STORE_COUNTER_APPS_SCRIPT_SECRET")
        batch_seconds = os.environ.get("STORE_COUNTER_CLOUD_BATCH_SECONDS")

        cfg_path = Path(base_dir or Path(__file__).resolve().parent) / CONFIG_FILENAME
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                url = url or data.get("appscript_url") or data.get("url")
                secret = secret or data.get("appscript_secret") or data.get("secret")
                batch_seconds = batch_seconds or data.get("batch_seconds")
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[cloud] Could not read {cfg_path.name}: {exc}", flush=True)

        return cls(url=url, secret=secret, batch_seconds=float(batch_seconds or DEFAULT_BATCH_SECONDS))

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        if not self._enabled:
            print(
                "[cloud] Apps Script sync disabled. Set cloud_config.json or "
                "STORE_COUNTER_APPS_SCRIPT_URL/SECRET to enable it.",
                flush=True,
            )
            return
        self._worker = threading.Thread(target=self._run, name="appscript-sync", daemon=True)
        self._worker.start()
        print(f"[cloud] Apps Script batch sync enabled -> {self.url} every {self.batch_seconds:.0f}s", flush=True)

    def enqueue_entry(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["type"] = "entry"
        self.enqueue(payload)

    def enqueue_health(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["type"] = "health"
        status = str(payload.get("status") or "").lower()
        key = _device_key(payload)
        if status in INSTANT_HEALTH_STATUSES and self._instant_status_by_device.get(key) != status:
            payload["_flush_now"] = True
            self._instant_status_by_device[key] = status
        elif status not in INSTANT_HEALTH_STATUSES:
            self._instant_status_by_device.pop(key, None)
        self.enqueue(payload)

    def enqueue(self, payload: dict[str, Any]) -> None:
        if not self._enabled:
            return
        payload.setdefault("sent_at", _utc_now_iso())
        flush_now = bool(payload.pop("_flush_now", False))
        try:
            self._queue.put_nowait(payload)
            if flush_now:
                self._flush_now.set()
        except queue.Full:
            self._dropped += 1
            if not self._warned_full:
                self._warned_full = True
                print("[cloud] Upload queue full. Local CSVs are still being written.", flush=True)

    def close(self, drain_seconds: float = 10.0) -> None:
        if not self._enabled or self._worker is None:
            return
        self._queue.put(None)
        self._flush_now.set()
        self._worker.join(timeout=drain_seconds)
        print(
            f"[cloud] Apps Script sync stopped. batches={self._sent_batches} "
            f"rows={self._sent_rows} dropped={self._dropped}",
            flush=True,
        )

    def _run(self) -> None:
        entries: list[dict[str, Any]] = []
        health: list[dict[str, Any]] = []
        next_flush = time.monotonic() + self.batch_seconds

        while True:
            timeout = max(0.0, next_flush - time.monotonic())
            try:
                payload = self._queue.get(timeout=timeout)
            except queue.Empty:
                payload = {"_flush_timer": True}

            if payload is None:
                self._flush(entries, health)
                return

            flush_now = bool(payload.pop("_flush_now", False) or payload.pop("_flush_timer", False))
            payload_type = payload.get("type")
            if payload_type == "entry":
                entries.append(payload)
            elif payload_type == "health":
                health.append(payload)
            elif not flush_now:
                print(f"[cloud] Dropping unknown payload type: {payload_type}", flush=True)

            if self._flush_now.is_set():
                self._flush_now.clear()
                flush_now = True

            if flush_now:
                self._flush(entries, health)
                entries = []
                health = []
                next_flush = time.monotonic() + self.batch_seconds
                if self._warned_full and self._queue.qsize() == 0:
                    self._warned_full = False

    def _flush(self, entries: list[dict[str, Any]], health: list[dict[str, Any]]) -> None:
        if not entries and not health:
            return
        payload = {
            "secret": self.secret,
            "type": "batch",
            "sent_at": _utc_now_iso(),
            "entries": entries,
            "health": health,
        }
        if self._send_with_retry(payload):
            rows = len(entries) + len(health)
            self._sent_batches += 1
            self._sent_rows += rows
            print(f"[cloud] Uploaded batch rows={rows} entries={len(entries)} health={len(health)}", flush=True)

    def _send_with_retry(self, payload: dict[str, Any]) -> bool:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    text = resp.read().decode("utf-8", "replace")[:300]
                    compact = text.replace(" ", "").lower()
                    if 200 <= resp.status < 300 and '"ok":true' in compact:
                        return True
                    print(f"[cloud] Unexpected Apps Script response HTTP {resp.status}: {text}", flush=True)
                    return False
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300] if exc.fp else ""
                if 400 <= exc.code < 500:
                    print(f"[cloud] Apps Script rejected HTTP {exc.code}: {detail}", flush=True)
                    return False
                print(f"[cloud] Apps Script server error HTTP {exc.code} attempt {attempt}/{self.max_retries}", flush=True)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == self.max_retries:
                    print(f"[cloud] Giving up after {attempt} upload attempts: {exc}", flush=True)
                    return False
            if attempt < self.max_retries:
                time.sleep(min(delay, 30.0))
                delay *= 2
        return False
