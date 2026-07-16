"""QPC-backed timestamp source with deterministic per-session ordering."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable

from ..models import Timestamp


class QpcClock:
    """Pair Windows' QPC-backed Python clock with UTC and a stable sequence."""

    def __init__(
        self,
        *,
        monotonic_ns: Callable[[], int] = time.perf_counter_ns,
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._monotonic_ns = monotonic_ns
        self._utc_now = utc_now
        self._lock = threading.Lock()
        self._sequence = 0
        self._last_monotonic_ns = 0

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    def now(self) -> Timestamp:
        with self._lock:
            value = max(self._last_monotonic_ns, self._monotonic_ns())
            sequence = self._sequence
            self._last_monotonic_ns = value
            self._sequence += 1
            return Timestamp(value, self._utc_now(), sequence)
