"""Disk information helpers."""

from __future__ import annotations

from typing import Dict

from ..list_disks import disk_io_counters, safe_partitions

__all__ = ["partitions", "io_counters"]


def partitions():
    """Return a list of mounted partitions."""
    return safe_partitions()


def io_counters() -> Dict[str, object]:
    """Return per-disk I/O statistics."""
    return disk_io_counters()
