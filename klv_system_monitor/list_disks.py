#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
list_disks.py — Safe disk partitions and usage (Windows/Linux).

- Avoids WinError 21 (device not ready) by filtering CD-ROM / empty removable volumes.
- Ignores mountpoints that don’t exist or can’t be accessed.
- Provides helpers to list partitions and disk I/O counters.
- When executed as a script it prints a table similar to the original
  stand-alone tool.
"""

from __future__ import annotations

import os
import sys
import psutil
from typing import List, Tuple, Optional, Dict


def human_bytes(n: float) -> str:
    """Convert bytes into a human-readable string."""
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    i = 0
    n = float(n)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {units[i]}"


def safe_partitions() -> List[Tuple[str, str, str, Optional[psutil._common.sdiskusage]]]:
    """Return tuples (device, mountpoint, fstype, usage or None) safely."""
    parts = []
    is_win = sys.platform.startswith("win")
    try:
        p_list = psutil.disk_partitions(all=False)
    except Exception:
        p_list = []

    for p in p_list:
        # Windows-specific filters
        if is_win:
            opts = (p.opts or "").lower()
            if "cdrom" in opts:
                continue
            if "removable" in opts and not p.fstype:
                continue
            if not p.fstype:
                continue

        if not os.path.exists(p.mountpoint):
            continue

        usage = None
        try:
            usage = psutil.disk_usage(p.mountpoint)
        except (PermissionError, OSError):
            continue
        except Exception:
            continue

        parts.append((p.device or "-", p.mountpoint, p.fstype or "-", usage))
    return parts


def disk_io_counters() -> Dict[str, psutil._common.sdiskio]:
    """Return per-disk I/O counters safely."""
    try:
        return psutil.disk_io_counters(perdisk=True) or {}
    except Exception:
        return {}


# ---------------------------- CLI helpers below ----------------------------


def print_partitions_table(parts: List[Tuple[str, str, str, Optional[psutil._common.sdiskusage]]]):
    headers = ["Device", "Mount", "Type", "Total", "Used", "Free", "%"]
    rows = []
    for dev, mnt, fstype, usage in parts:
        if usage is None:
            continue
        rows.append([
            dev,
            mnt,
            fstype,
            human_bytes(usage.total),
            human_bytes(usage.used),
            human_bytes(usage.free),
            f"{usage.percent:.1f}",
        ])

    cols = list(zip(*([headers] + rows))) if rows else []
    widths = [max(len(str(cell)) for cell in col) for col in cols] if cols else [7, 5, 4, 5, 5, 5, 1]

    def fmt(row):
        return "  ".join(str(cell).ljust(w) for cell, w in zip(row, widths))

    print("Mounted partitions")
    print(fmt(headers))
    print(fmt(["-" * w for w in widths]))
    for r in rows:
        print(fmt(r))
    if not rows:
        print("(no entries)")


def print_disk_io():
    print("\nDisk I/O (totals since boot)")
    io = disk_io_counters()
    if not io:
        print("(no data)")
        return

    headers = [
        "Disk",
        "Reads",
        "Writes",
        "Read bytes",
        "Write bytes",
        "Read time ms",
        "Write time ms",
        "Busy ms",
    ]
    rows = []
    for disk, st in io.items():
        rows.append([
            disk,
            getattr(st, "read_count", 0),
            getattr(st, "write_count", 0),
            human_bytes(getattr(st, "read_bytes", 0)),
            human_bytes(getattr(st, "write_bytes", 0)),
            getattr(st, "read_time", 0),
            getattr(st, "write_time", 0),
            getattr(st, "busy_time", 0) if hasattr(st, "busy_time") else "-",
        ])

    cols = list(zip(*([headers] + rows)))
    widths = [max(len(str(cell)) for cell in col) for col in cols]

    def fmt(row):
        return "  ".join(str(cell).ljust(w) for cell, w in zip(row, widths))

    print(fmt(headers))
    print(fmt(["-" * w for w in widths]))
    for r in rows:
        print(fmt(r))


def main():
    parts = safe_partitions()
    print_partitions_table(parts)
    print_disk_io()


if __name__ == "__main__":
    main()
