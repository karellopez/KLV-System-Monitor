"""Memory usage helpers."""

from __future__ import annotations

from typing import Optional, Tuple

import psutil


def stats() -> Tuple[psutil._common.svmem, Optional[psutil._common.sswap]]:
    """Return virtual memory and swap statistics."""
    vm = psutil.virtual_memory()
    try:
        sm = psutil.swap_memory()
    except Exception:
        sm = None
    return vm, sm
