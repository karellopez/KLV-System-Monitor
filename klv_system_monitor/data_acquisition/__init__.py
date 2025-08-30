"""Data acquisition modules for KLV System Monitor.

This package groups together the platform-independent helpers used to
collect system statistics.  Each submodule focuses on a specific area
such as CPU, memory, network, processes, or disks.  The GUI layer imports
these helpers so all data gathering logic lives outside of the interface
code."""

from . import cpu, memory, network, processes, disks

__all__ = ["cpu", "memory", "network", "processes", "disks"]
