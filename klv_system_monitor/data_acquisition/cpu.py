"""CPU related data acquisition helpers."""

from __future__ import annotations

import platform
import subprocess
import threading
from typing import List, Optional, Tuple

import psutil

# Cache for Windows frequency fetching to avoid stalling the UI.  The
# PowerShell call used on Windows can take a noticeable amount of time, so
# we run it in a background thread and keep the latest result here.
_win_freqs_cache: Tuple[Optional[List[float]], Optional[float]] = (None, None)
_win_freqs_thread: Optional[threading.Thread] = None


def count(logical: bool = True) -> int:
    """Return the number of CPUs available on the system."""
    return psutil.cpu_count(logical=logical) or 1


def percent(percpu: bool = True) -> List[float]:
    """Return CPU utilisation percentage.

    Parameters
    ----------
    percpu: bool
        When ``True`` a list with one entry per logical CPU is returned,
        otherwise the overall percentage is reported.
    """
    return psutil.cpu_percent(interval=None, percpu=percpu)


def _windows_cpu_freqs() -> Tuple[Optional[List[float]], Optional[float]]:
    """Fetch per-CPU frequencies on Windows via ``Get-Counter``.

    Returns a list of frequencies in MHz and their average. If unavailable,
    ``(None, None)`` is returned.
    """
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            r"(Get-Counter '\\Processor Information(*)\\Processor Frequency').CounterSamples | ForEach-Object { $_.InstanceName + '=' + $_.CookedValue }",
        ]
        out = subprocess.check_output(cmd, text=True)
        freqs: List[float] = []
        for line in out.strip().splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            name, val = line.split("=", 1)
            if name.strip().lower() == "_total":
                continue
            try:
                freqs.append(float(val))
            except ValueError:
                pass
        if freqs:
            avg = sum(freqs) / len(freqs)
            return freqs, avg
    except Exception:
        pass
    return None, None


def _windows_freq_worker() -> None:
    global _win_freqs_cache, _win_freqs_thread
    _win_freqs_cache = _windows_cpu_freqs()
    _win_freqs_thread = None


def _schedule_windows_freqs() -> None:
    global _win_freqs_thread
    if _win_freqs_thread is None or not _win_freqs_thread.is_alive():
        _win_freqs_thread = threading.Thread(target=_windows_freq_worker, daemon=True)
        _win_freqs_thread.start()


def freqs(n_cpu: int) -> Tuple[Optional[List[float]], Optional[float]]:
    """Return per-CPU and average frequency in MHz.

    The function tries :func:`psutil.cpu_freq` first.  On Windows the
    PowerShell based helper above is scheduled in the background to
    provide more accurate readings without blocking the caller.
    """
    per_freq_mhz: Optional[List[float]] = None
    avg_freq: Optional[float] = None
    try:
        freqs = psutil.cpu_freq(percpu=True)
        if freqs:
            per_freq_mhz = [max(0.0, getattr(f, "current", 0.0)) for f in freqs[:n_cpu]]
            valid = [f for f in per_freq_mhz if f and f > 0]
            if valid:
                avg_freq = sum(valid) / len(valid)
    except Exception:
        pass

    if platform.system() == "Windows":
        _schedule_windows_freqs()
        win_freqs, win_avg = _win_freqs_cache
        if win_freqs:
            per_freq_mhz = win_freqs[:n_cpu]
            avg_freq = win_avg
    return per_freq_mhz, avg_freq


def temperature() -> Optional[float]:
    """Return the highest available CPU temperature in Celsius."""
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    if not temps:
        return None
    max_temp = None
    for entries in temps.values():
        for t in entries:
            cur = getattr(t, "current", None)
            if cur is None:
                continue
            if max_temp is None or cur > max_temp:
                max_temp = cur
    return max_temp
