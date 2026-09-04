"""Background upload of store events and health reports to Google Apps Script.

Local CSV files remain the source of truth. This module only mirrors rows to a
central Apps Script endpoint when configured, and it never blocks the camera loop.

Configuration can be provided with environment variables:

  STORE_COUNTER_APPS_SCRIPT_URL
  STORE_COUNTER_APPS_SCRIPT_SECRET

or with ``cloud_config.json`` next to this file:

  {
    "appscript_url": "https://script.google.com/macros/s/.../exec",
    "appscript_secret": "shared-secret"
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CloudSync:
    """Asynchronous Apps Script uploader for entry and health rows."""

    def __init__(
        self,
        url: str | None,
        secret: str | None,
        max_queue: int = 5000,
        timeout: float = 10.0,
        max_retries: int = 5,
    ) -> None:
        self.url = (url or "").strip()
        self.secret = (secret or "").strip()
        self.timeout = timeout
        self.max_retries = max_retries
        self._enabled = bool(self.url and self.secret)
        self._queue: "queue.Queue[dict[str, Any] | None]" = queue.Queue(maxsize=max_queue)
        self._worker: threading.Thread | None = None
        self._dropped = 0
        self._sent = 0
        self._warned_full = False

    @classmethod
    def from_config(cls, base_dir: str | Path | None = None) -> "CloudSync":
        url = os.environ.get("STORE_COUNTER_APPS_SCRIPT_URL")
        secret = os.environ.get("STORE_COUNTER_APPS_SCRIPT_SECRET")

        cfg_path = Path(base_dir or Path(__file__).resolve().parent) / CONFIG_FILENAME
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                url = url or data.get("appscript_url") or data.get("url")
                secret = secret or data.get("appscript_secret") or data.get("secret")
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[cloud] Could not read {cfg_path.name}: {exc}", flush=True)

        return cls(url=url, secret=secret)

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
        print(f"[cloud] Apps Script sync enabled -> {self.url}", flush=True)

    def enqueue_entry(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["type"] = "entry"
        self.enqueue(payload)

    def enqueue_health(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["type"] = "health"
        self.enqueue(payload)

    def enqueue(self, payload: dict[str, Any]) -> None:
        if not self._enabled:
            return
        payload.setdefault("sent_at", _utc_now_iso())
        payload["secret"] = self.secret
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self._dropped += 1
            if not self._warned_full:
                self._warned_full = True
                print("[cloud] Upload queue full. Local CSVs are still being written.", flush=True)

    def close(self, drain_seconds: float = 5.0) -> None:
        if not self._enabled or self._worker is None:
            return
        self._queue.put(None)
        self._worker.join(timeout=drain_seconds)
        print(f"[cloud] Apps Script sync stopped. sent={self._sent} dropped={self._dropped}", flush=True)

    def _run(self) -> None:
        while True:
            payload = self._queue.get()
            if payload is None:
                return
            self._send_with_retry(payload)
            if self._warned_full and self._queue.qsize() == 0:
                self._warned_full = False

    def _send_with_retry(self, payload: dict[str, Any]) -> None:
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
                        self._sent += 1
                        return
                    print(f"[cloud] Unexpected Apps Script response HTTP {resp.status}: {text}", flush=True)
                    return
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300] if exc.fp else ""
                if 400 <= exc.code < 500:
                    print(f"[cloud] Apps Script rejected HTTP {exc.code}: {detail}", flush=True)
                    return
                print(f"[cloud] Apps Script server error HTTP {exc.code} attempt {attempt}/{self.max_retries}", flush=True)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == self.max_retries:
                    print(f"[cloud] Giving up after {attempt} upload attempts: {exc}", flush=True)
            if attempt < self.max_retries:
                time.sleep(min(delay, 30.0))
                delay *= 2
