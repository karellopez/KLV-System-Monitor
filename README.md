# KLV-System-Monitor

KLV System Monitor is a lightweight, cross-platform system monitoring tool
written in Python with PyQt5 and psutil. It provides a modern, customizable
interface inspired by the Ubuntu system monitor, while adding advanced features
for efficiency, flexibility, and user control.

The application now includes a theme system with a range of built-in color
palettes. Use the moon button on the toolbar to select a preferred theme, which
is saved and restored on the next launch.

Recent updates further reduce the monitor's own CPU usage by batching
per-process information retrieval, decoupling plot and text refresh rates,
and refreshing the file system view only on demand. Graph antialiasing is
enabled again for crisp rendering and can now be toggled in Preferences.
The Processes tab now updates only when visible, and its refresh interval is
configurable via the Preferences dialog.

