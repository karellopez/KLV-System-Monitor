# KLV-System-Monitor

KLV System Monitor is a lightweight, cross-platform system monitoring tool
written in Python with PyQt5 and psutil. It provides a modern, customizable
interface inspired by the Ubuntu system monitor, while adding advanced features
for efficiency, flexibility, and user control.

CPU usage can be visualized in three modes—**Multi thread**, **General view**, and
**Multi window**—selectable from the Preferences dialog.

Plots adapt to the selected theme, and "Multi window" graphs hide axes while
showing each core's usage (and frequency when enabled) atop its panel. The
Preferences dialog also offers options to fill CPU graphs with translucent
colors and to smooth only the network plot if desired.

Recent updates further reduce the monitor's own CPU usage by batching
per-process information retrieval, decoupling plot and text refresh rates,
and refreshing the file system view only on demand. Graph antialiasing is
enabled again for crisp rendering and can now be toggled in Preferences.
The Processes tab now updates only when visible, and its refresh interval is
configurable via the Preferences dialog.

