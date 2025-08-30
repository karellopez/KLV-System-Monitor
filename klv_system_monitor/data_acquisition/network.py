"""Network I/O helpers."""

from __future__ import annotations

import time
from typing import Tuple

import psutil


def io_counters():
    """Return aggregated network I/O counters."""
    return psutil.net_io_counters(pernic=False)


def rates(prev, prev_time: float) -> Tuple[float, float, psutil._common.snetio, float]:
    """Compute network transfer rates.

    Parameters
    ----------
    prev: psutil._common.snetio
        Previous I/O counters.
    prev_time: float
        Timestamp when ``prev`` was captured.
    """
    now = time.monotonic()
    dt = max(1e-6, now - prev_time)
    cur = psutil.net_io_counters(pernic=False)
    rx_kib = (cur.bytes_recv - prev.bytes_recv) / 1024.0 / dt
    tx_kib = (cur.bytes_sent - prev.bytes_sent) / 1024.0 / dt
    return rx_kib, tx_kib, cur, now
