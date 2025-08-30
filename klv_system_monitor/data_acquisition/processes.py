"""Process related utilities."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import psutil

# Re-export common psutil exceptions so callers don't need to import psutil.
NoSuchProcess = psutil.NoSuchProcess
AccessDenied = psutil.AccessDenied
ZombieProcess = psutil.ZombieProcess


def iter_processes(attrs: Optional[Sequence[str]] = None) -> Iterable[psutil.Process]:
    """Yield processes using :func:`psutil.process_iter`."""
    return psutil.process_iter(attrs)


def kill(pid: int) -> None:
    """Terminate process ``pid``."""
    psutil.Process(pid).kill()


def prime_cpu_percent() -> None:
    """Warm up per-process CPU percentage measurements."""
    for p in psutil.process_iter(["pid"]):
        try:
            p.cpu_percent(None)
        except Exception:
            pass
