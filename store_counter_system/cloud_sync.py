"""Lightweight, dependency-free cloud sync for store entrance events.

Pushes each entry/exit event to a Supabase (hosted Postgres) table over its REST
API so counts can be read from anywhere. Designed for real-store deployment:

  * Sending happens on a background daemon thread via a bounded queue, so a slow
    or down internet connection never blocks or crashes the camera/detection loop.
  * If the cloud is not configured, every call is a no-op and the app runs as before.
  * Failed sends are retried with backoff; the local CSV remains the source of truth.

Configuration (either works; env vars win over the file):

  Environment variables:
    STORE_COUNTER_SUPABASE_URL   e.g. https://abcdxyz.supabase.co
    STORE_COUNTER_SUPABASE_KEY   the project's anon or service_role API key
    STORE_COUNTER_SUPABASE_TABLE optional, defaults to "store_events"

  Or a JSON file next to this script named cloud_config.json:
    {
      "supabase_url": "https://abcdxyz.supabase.co",
      "supabase_key": "eyJhbGc...",
      "table": "store_events"
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
    """Background uploader for store entrance events.

    Use ``CloudSync.from_config()`` to build one, then call ``enqueue(event)``
    from the detection loop and ``close()`` on shutdown.
    """

    def __init__(
        self,
        url: str | None,
        key: str | None,
        table: str = "store_events",
        max_queue: int = 5000,
        timeout: float = 8.0,
        max_retries: int = 5,
    ) -> None:
        self.table = table
        self.timeout = timeout
        self.max_retries = max_retries
        self._endpoint = f"{url.rstrip('/')}/rest/v1/{table}" if url else None
        self._key = key
        self._enabled = bool(url and key)
        self._queue: "queue.Queue[dict[str, Any] | None]" = queue.Queue(maxsize=max_queue)
        self._worker: threading.Thread | None = None
        self._dropped = 0
        self._sent = 0
        self._warned_full = False

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_config(cls, base_dir: str | Path | None = None) -> "CloudSync":
        url = os.environ.get("STORE_COUNTER_SUPABASE_URL")
        key = os.environ.get("STORE_COUNTER_SUPABASE_KEY")
        table = os.environ.get("STORE_COUNTER_SUPABASE_TABLE", "store_events")

        if not (url and key):
            cfg_path = Path(base_dir or Path(__file__).resolve().parent) / CONFIG_FILENAME
            if cfg_path.exists():
                try:
                    data = json.loads(cfg_path.read_text(encoding="utf-8"))
                    url = url or data.get("supabase_url")
                    key = key or data.get("supabase_key")
                    table = data.get("table", table)
                except (json.JSONDecodeError, OSError) as exc:
                    print(f"[cloud] Could not read {cfg_path.name}: {exc}", flush=True)

        return cls(url=url, key=key, table=table)

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        if not self._enabled:
            print(
                "[cloud] Cloud sync disabled (no Supabase URL/key configured). "
                "Events are saved to the local CSV only.",
                flush=True,
            )
            return
        self._worker = threading.Thread(target=self._run, name="cloud-sync", daemon=True)
        self._worker.start()
        print(f"[cloud] Cloud sync enabled -> {self._endpoint}", flush=True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enqueue(self, event: dict[str, Any]) -> None:
        """Queue an event for upload. Never blocks; drops if the queue is full."""
        if not self._enabled:
            return
        if "event_time" not in event:
            event["event_time"] = _utc_now_iso()
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self._dropped += 1
            if not self._warned_full:
                self._warned_full = True
                print(
                    "[cloud] Upload queue full (internet down for a while?). "
                    "Dropping newest events; the local CSV still has everything.",
                    flush=True,
                )

    def close(self, drain_seconds: float = 5.0) -> None:
        if not self._enabled or self._worker is None:
            return
        self._queue.put(None)
        self._worker.join(timeout=drain_seconds)
        print(f"[cloud] Cloud sync stopped. sent={self._sent} dropped={self._dropped}", flush=True)

    # -- worker ---------------------------------------------------------------

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                return
            self._send_with_retry(event)
            if self._warned_full and self._queue.qsize() == 0:
                self._warned_full = False

    def _send_with_retry(self, event: dict[str, Any]) -> None:
        body = json.dumps([event]).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Prefer": "return=minimal",
        }
        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(self._endpoint, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if 200 <= resp.status < 300:
                        self._sent += 1
                        return
                    print(f"[cloud] Unexpected status {resp.status} sending event.", flush=True)
                    return
            except urllib.error.HTTPError as exc:
                # 4xx are config/schema errors that won't fix themselves on retry.
                detail = exc.read().decode("utf-8", "replace")[:200] if exc.fp else ""
                if 400 <= exc.code < 500:
                    print(f"[cloud] Rejected (HTTP {exc.code}): {detail}. Check table/keys.", flush=True)
                    return
                print(f"[cloud] Server error HTTP {exc.code} (attempt {attempt}/{self.max_retries}).", flush=True)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                # Network down / DNS / timeout -> retry with backoff.
                if attempt == self.max_retries:
                    print(f"[cloud] Giving up on event after {attempt} attempts: {exc}", flush=True)
            if attempt < self.max_retries:
                time.sleep(min(delay, 30.0))
                delay *= 2
