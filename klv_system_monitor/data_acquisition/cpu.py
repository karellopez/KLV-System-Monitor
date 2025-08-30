"""CPU related data acquisition helpers."""

from __future__ import annotations

import platform
import subprocess
import threading
from typing import List, Optional, Tuple

import psutil

# ---------------------------------------------------------------------------
# Windows specific setup for fast per-core frequency readings
# ---------------------------------------------------------------------------

if platform.system() == "Windows":
    import ctypes as C
    from ctypes import wintypes as W

    # Basic PDH (Performance Data Helper) declarations
    DWORD_PTR = C.c_uint64 if C.sizeof(C.c_void_p) == 8 else C.c_uint32
    PDH_HQUERY = C.c_void_p
    PDH_HCOUNTER = C.c_void_p
    PDH_MORE_DATA = 0x800007D2
    PDH_FMT_DOUBLE = 0x00000200

    pdh = C.WinDLL("pdh.dll")
    PdhOpenQuery = pdh.PdhOpenQueryW
    PdhOpenQuery.argtypes = [W.LPCWSTR, DWORD_PTR, C.POINTER(PDH_HQUERY)]
    PdhOpenQuery.restype = W.DWORD
    PdhCloseQuery = pdh.PdhCloseQuery
    PdhCloseQuery.argtypes = [PDH_HQUERY]
    PdhCloseQuery.restype = W.DWORD
    PdhAddCounter = pdh.PdhAddEnglishCounterW
    PdhAddCounter.argtypes = [PDH_HQUERY, W.LPCWSTR, DWORD_PTR, C.POINTER(PDH_HCOUNTER)]
    PdhAddCounter.restype = W.DWORD
    PdhCollectQueryData = pdh.PdhCollectQueryData
    PdhCollectQueryData.argtypes = [PDH_HQUERY]
    PdhCollectQueryData.restype = W.DWORD

    class PDH_FMT_COUNTERVALUE(C.Structure):
        _fields_ = [("CStatus", W.DWORD), ("doubleValue", C.c_double)]

    class PDH_FMT_COUNTERVALUE_ITEM_W(C.Structure):
        _fields_ = [("szName", W.LPWSTR), ("FmtValue", PDH_FMT_COUNTERVALUE)]

    PdhGetFormattedCounterArrayW = pdh.PdhGetFormattedCounterArrayW
    PdhGetFormattedCounterArrayW.argtypes = [
        PDH_HCOUNTER,
        W.DWORD,
        C.POINTER(W.DWORD),
        C.POINTER(W.DWORD),
        C.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W),
    ]
    PdhGetFormattedCounterArrayW.restype = W.DWORD

    def _core_key(n: str) -> tuple:
        """Return a sortable key for core names like '0,0'."""

        parts = [p.strip() for p in n.split(",")]
        try:
            return tuple(int(p) for p in parts)
        except Exception:
            return (n,)

    class PerCorePerfPDH:
        """Persistent reader for % Processor Performance per core."""

        def __init__(self) -> None:
            self.hQ = PDH_HQUERY()
            if PdhOpenQuery(None, DWORD_PTR(0), C.byref(self.hQ)) != 0:
                raise RuntimeError("PdhOpenQuery failed")
            self.hC = PDH_HCOUNTER()
            last = None
            for path in (
                r"\Processor(*)\% Processor Performance",
                r"\Processor Information(*)\% Processor Performance",
            ):
                res = PdhAddCounter(self.hQ, path, DWORD_PTR(0), C.byref(self.hC))
                if res == 0:
                    self.path = path
                    break
                last = res
            else:  # pragma: no cover - best effort
                PdhCloseQuery(self.hQ)
                raise RuntimeError(f"AddCounter failed (last=0x{last:08X})")
            # Prime the query so subsequent reads are instantaneous
            if PdhCollectQueryData(self.hQ) != 0:
                PdhCloseQuery(self.hQ)
                raise RuntimeError("PdhCollectQueryData prime failed")
            self.buf_size = W.DWORD(0)
            self.item_count = W.DWORD(0)
            self.raw = None

        def __del__(self) -> None:  # pragma: no cover - invoked by GC
            if getattr(self, "hQ", None):
                PdhCloseQuery(self.hQ)

        def read_percent(self) -> dict:
            """Return dict mapping core name to % Processor Performance."""

            if PdhCollectQueryData(self.hQ) != 0:
                return {}
            if self.raw is None:
                bs = W.DWORD(0)
                ic = W.DWORD(0)
                if (
                    PdhGetFormattedCounterArrayW(
                        self.hC, PDH_FMT_DOUBLE, C.byref(bs), C.byref(ic), None
                    )
                    != PDH_MORE_DATA
                ):
                    return {}
                self.buf_size = bs
                self.item_count = ic
                self.raw = (C.c_byte * bs.value)()
            while True:
                pItems = C.cast(self.raw, C.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
                res = PdhGetFormattedCounterArrayW(
                    self.hC,
                    PDH_FMT_DOUBLE,
                    C.byref(self.buf_size),
                    C.byref(self.item_count),
                    pItems,
                )
                if res == PDH_MORE_DATA:
                    self.raw = (C.c_byte * self.buf_size.value)()
                    continue
                if res != 0:
                    return {}
                break
            out = {}
            for i in range(self.item_count.value):
                it = pItems[i]
                if (
                    it.FmtValue.CStatus == 0
                    and it.szName
                    and "total" not in it.szName.lower()
                ):
                    out[it.szName] = float(it.FmtValue.doubleValue)
            return dict(sorted(out.items(), key=lambda kv: _core_key(kv[0])))

    def get_base_mhz_once() -> float:
        """Return the base processor frequency in MHz using PDH."""

        hQ = PDH_HQUERY()
        if PdhOpenQuery(None, DWORD_PTR(0), C.byref(hQ)) != 0:
            raise RuntimeError("PdhOpenQuery failed")
        hC = PDH_HCOUNTER()
        if pdh.PdhAddEnglishCounterW(
            hQ,
            r"\Processor Information(_Total)\Processor Frequency",
            DWORD_PTR(0),
            C.byref(hC),
        ) != 0:
            PdhCloseQuery(hQ)
            raise RuntimeError("Cannot get base MHz")
        PdhCollectQueryData(hQ)
        import time

        time.sleep(0.05)
        PdhCollectQueryData(hQ)
        bs = W.DWORD(0)
        ic = W.DWORD(0)
        PdhGetFormattedCounterArrayW(hC, PDH_FMT_DOUBLE, C.byref(bs), C.byref(ic), None)
        raw = (C.c_byte * bs.value)()
        p = C.cast(raw, C.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
        if (
            PdhGetFormattedCounterArrayW(
                hC, PDH_FMT_DOUBLE, C.byref(bs), C.byref(ic), p
            )
            == 0
            and ic.value
        ):
            val = float(p[0].FmtValue.doubleValue)
            PdhCloseQuery(hQ)
            return val
        PdhCloseQuery(hQ)
        raise RuntimeError("Cannot read base MHz")


# Cache for Windows frequency fetching to avoid stalling the UI.  The
# PowerShell call used as a fallback on Windows can take a noticeable
# amount of time, so we run it in a background thread and keep the latest
# result here.
_win_freqs_cache: Tuple[Optional[List[float]], Optional[float]] = (None, None)
_win_freqs_thread: Optional[threading.Thread] = None
_win_perf: Optional["PerCorePerfPDH"] = None
_win_base_mhz: Optional[float] = None


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



def _windows_cpu_freqs_powershell() -> Tuple[Optional[List[float]], Optional[float]]:
    """Slow PowerShell-based fallback for per-CPU frequencies."""

    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            r"(Get-Counter '\Processor Information(*)\Processor Frequency').CounterSamples | ForEach-Object { $_.InstanceName = $_.CookedValue }",
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


def _windows_cpu_freqs() -> Tuple[Optional[List[float]], Optional[float]]:
    """Fetch per-CPU frequencies on Windows using PDH with PowerShell fallback."""

    global _win_perf, _win_base_mhz
    try:
        if _win_perf is None:
            _win_perf = PerCorePerfPDH()
        if _win_base_mhz is None:
            _win_base_mhz = get_base_mhz_once()
        perc = _win_perf.read_percent()
        if perc and _win_base_mhz:
            per_core = [_win_base_mhz * (val / 100.0) for val in perc.values()]
            if per_core:
                avg = sum(per_core) / len(per_core)
                return per_core, avg
    except Exception:
        _win_perf = None
        _win_base_mhz = None

    return _windows_cpu_freqs_powershell()



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

    The function tries :func:`psutil.cpu_freq` first.  On Windows a
    PDH-based reader (with a slower PowerShell fallback) is scheduled in
    the background to provide accurate readings without blocking the
    caller.
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
