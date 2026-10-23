"""In-memory store of recent analyses, so the web app can explore chunks after a report."""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections import OrderedDict
from typing import Any

from ragcompass.analyze import Analysis

MAX_ITEMS = int(os.environ.get("RAGCOMPASS_STORE_ITEMS", "32"))
TTL_SECONDS = int(os.environ.get("RAGCOMPASS_STORE_TTL", "1800"))


class Entry:
    def __init__(self, analysis: Analysis) -> None:
        self.analysis = analysis
        self.created = time.monotonic()
        self.bench: Any = None


class AnalysisStore:
    """Least-recently-used, time-limited. Nothing is written to disk."""

    def __init__(self, max_items: int = MAX_ITEMS, ttl: float = TTL_SECONDS) -> None:
        self.max_items = max_items
        self.ttl = ttl
        self._items: OrderedDict[str, Entry] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, analysis: Analysis) -> str:
        report_id = secrets.token_hex(8)
        analysis.report.id = report_id
        with self._lock:
            self._items[report_id] = Entry(analysis)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        return report_id

    def get(self, report_id: str) -> Entry | None:
        with self._lock:
            entry = self._items.get(report_id)
            if entry is None:
                return None
            if time.monotonic() - entry.created > self.ttl:
                del self._items[report_id]
                return None
            self._items.move_to_end(report_id)
            return entry
