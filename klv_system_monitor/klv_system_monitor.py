# klv_system_monitor.py
# Cross-platform “Ubuntu-style” System Monitor with centered tabs:
#   • Processes   • Resources   • File Systems
#
# New in this version:
#   - Left Y axis with % labels (right axis hidden).
#   - Click colored swatch in the CPU legend to choose a custom color per thread.
#   - File Systems tab: "Used" shows a progress bar (like Ubuntu).
#   - Preferences: antialiasing toggle, thread line width, toggle X/Y grid,
#                  extra smoothing (double-EMA), and all previous knobs
#                  (history, update cadences, EMA alphas, show per-CPU frequencies).
#   - Separate plot vs text refresh intervals.
#   - File Systems tab only lists active drives and refreshes on demand.
#
# Dependencies: psutil, PyQt5, pyqtgraph
# License: MIT (adjust as desired)

import sys
import time
from collections import deque
from typing import Dict, Tuple, List, Optional

import psutil
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg


# ------------------------------- Utilities -------------------------------

def human_bytes(n: float) -> str:
    """Format bytes in binary units (KiB, MiB, GiB...)."""
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    i = 0
    n = float(n)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return (f"{n:,.0f} {units[i]}" if n >= 100 else f"{n:,.1f} {units[i]}").replace(",", " ")

def human_rate_kib(n_kib_s: float) -> str:
    """Format a rate given in KiB/s (switch to MiB/s above 1 MiB/s)."""
    n = float(n_kib_s)
    return (f"{n/1024.0:,.2f} MiB/s" if n >= 1024 else f"{n:,.1f} KiB/s").replace(",", " ")

def human_freq(mhz: Optional[float]) -> str:
    """Format frequency in MHz as MHz/GHz with sensible precision."""
    if mhz is None or mhz <= 0:
        return "—"
    return f"{mhz/1000.0:.2f} GHz" if mhz >= 1000.0 else f"{mhz:.0f} MHz"

def set_dark_palette(app: QtWidgets.QApplication):
    """Apply a dark Fusion palette + small style tweaks."""
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    bg = QtGui.QColor(30, 30, 30)
    base = QtGui.QColor(40, 40, 40)
    text = QtGui.QColor(220, 220, 220)
    accent = QtGui.QColor(53, 132, 228)

    palette.setColor(QtGui.QPalette.Window, bg)
    palette.setColor(QtGui.QPalette.WindowText, text)
    palette.setColor(QtGui.QPalette.Base, base)
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(50, 50, 50))
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(255, 255, 220))
    palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(0, 0, 0))
    palette.setColor(QtGui.QPalette.Text, text)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(45, 45, 45))
    palette.setColor(QtGui.QPalette.ButtonText, text)
    palette.setColor(QtGui.QPalette.Highlight, accent)
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
    app.setPalette(palette)

    app.setStyleSheet("""
        QTableWidget { gridline-color: #555; }
        QHeaderView::section { background:#2a2a2a; color:#ddd; padding: 4px; border: 0px; }
        QTableWidget::item { selection-background-color:#35507a; selection-color:#fff; }
        QLabel { color:#ddd; }
        QTabWidget::pane { border: 1px solid #444; }
        QTabBar::tab { background: #2a2a2a; color:#ddd; padding:6px 12px; }
        QTabBar::tab:selected { background:#353535; }
        QProgressBar { color: #ddd; border: 0px; background: #333; }
        QProgressBar::chunk { background-color: #2d7ff7; }
    """)


# ------------------------------- Centered tabs -------------------------------

class CenteredTabWidget(QtWidgets.QWidget):
    """
    A compact tab container that keeps the tab bar centered.
    API mirrors a subset of QTabWidget: addTab(), setCurrentIndex(), currentIndex().
    """
    currentChanged = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabBar = QtWidgets.QTabBar(movable=False, tabsClosable=False)
        self.tabBar.setExpanding(False)
        self.tabBar.setDocumentMode(True)
        self.tabBar.setDrawBase(False)
        self.tabBar.currentChanged.connect(self._on_tab_changed)

        self.stack = QtWidgets.QStackedWidget()

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addStretch(1)
        top.addWidget(self.tabBar, 0, QtCore.Qt.AlignCenter)
        top.addStretch(1)

        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addLayout(top)
        main.addWidget(self.stack)

    def addTab(self, widget: QtWidgets.QWidget, title: str):
        idx = self.stack.addWidget(widget)
        self.tabBar.addTab(title)
        if self.stack.count() == 1:
            self.setCurrentIndex(0)
        return idx

    def setCurrentIndex(self, i: int):
        self.tabBar.setCurrentIndex(i)
        self.stack.setCurrentIndex(i)

    def currentIndex(self) -> int:
        return self.stack.currentIndex()

    def _on_tab_changed(self, i: int):
        self.stack.setCurrentIndex(i)
        self.currentChanged.emit(i)


# ------------------------------- Axes (Ubuntu-like) -------------------------------

class TimeAxisItem(pg.AxisItem):
    """
    Bottom axis that displays remaining time (left→right): "1 min" ... "0 secs".
    history_len = number of points in the buffer; interval_seconds = time per point.
    """
    def __init__(self, history_len: int, interval_seconds: float, *args, **kwargs):
        super().__init__(orientation='bottom', *args, **kwargs)
        self.history_len = max(1, int(history_len))
        self.interval_seconds = max(1e-6, float(interval_seconds))

    def update_params(self, history_len: int, interval_seconds: float):
        self.history_len = max(1, int(history_len))
        self.interval_seconds = max(1e-6, float(interval_seconds))
        self.picture = None  # force re-render

    def tickStrings(self, values, scale, spacing):
        labels = []
        total_secs = (self.history_len - 1) * self.interval_seconds
        for x in values:
            remaining = max(0.0, total_secs - float(x) * self.interval_seconds)
            if remaining >= 60:
                mins = int(round(remaining / 60.0))
                labels.append(f"{mins} min" if mins == 1 else f"{mins} mins")
            else:
                secs = int(round(remaining))
                labels.append(f"{secs} secs")
        return labels

class PercentAxisItem(pg.AxisItem):
    """Left Y axis that renders ticks as 'xx %'."""
    def __init__(self, *args, **kwargs):
        super().__init__(orientation='left', *args, **kwargs)

    def tickStrings(self, values, scale, spacing):
        return [f"{int(round(v))} %" for v in values]


# ------------------------------- Clickable swatch -------------------------------

class ClickableLabel(QtWidgets.QLabel):
    """Small color swatch that emits a clicked() signal."""
    clicked = QtCore.pyqtSignal()

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ------------------------------- Legend (per-CPU usage + freq + color picker) -------------------------------

class LegendGrid(QtWidgets.QWidget):
    """
    Compact multi-column legend with:
      • swatch (click to pick a color),
      • "CPU<i>",
      • dynamic label "<usage>% · <freq>" for each logical CPU (thread).
    Max 4 columns; grows downward; meant to live inside a QScrollArea.
    """
    def __init__(self, labels: List[str], colors: List[QtGui.QColor], on_color_change, columns=4, parent=None):
        super().__init__(parent)
        self.value_labels: List[QtWidgets.QLabel] = []
        self.swatches: List[ClickableLabel] = []
        self.on_color_change = on_color_change

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)

        columns = max(1, min(4, int(columns)))  # hard cap at 4

        for idx, (text, col) in enumerate(zip(labels, colors)):
            r, c = divmod(idx, columns)

            swatch = ClickableLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background:{col.name()}; border-radius:2px;")
            swatch.clicked.connect(lambda i=idx: self._pick_color(i))
            self.swatches.append(swatch)

            name = QtWidgets.QLabel(text)
            name.setStyleSheet("color:white;")

            val = QtWidgets.QLabel("0.0% · —")
            val.setStyleSheet("color:#bbbbbb;")
            self.value_labels.append(val)

            roww = QtWidgets.QWidget()
            rowl = QtWidgets.QHBoxLayout(roww)
            rowl.setContentsMargins(0, 0, 0, 0)
            rowl.addWidget(swatch)
            rowl.addWidget(name)
            rowl.addWidget(val)
            grid.addWidget(roww, r, c)

    def _pick_color(self, i: int):
        """Open QColorDialog and notify the parent when a color is chosen."""
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if col.isValid():
            self.swatches[i].setStyleSheet(f"background:{col.name()}; border-radius:2px;")
            if callable(self.on_color_change):
                self.on_color_change(i, col)

    def set_values(self, usages: List[float], freqs_mhz: Optional[List[float]] = None):
        """Update the per-CPU legend values."""
        for i, lab in enumerate(self.value_labels):
            pct = usages[i] if i < len(usages) else 0.0
            if freqs_mhz and i < len(freqs_mhz) and freqs_mhz[i] and freqs_mhz[i] > 0:
                lab.setText(f"{pct:,.1f}% · {human_freq(freqs_mhz[i])}")
            else:
                lab.setText(f"{pct:,.1f}% · —")


# ------------------------------- Resources tab -------------------------------

class ResourcesTab(QtWidgets.QWidget):
    """
    Ubuntu-style resources page:
      • CPU multi-line plot with extra smoothing, custom colors, left % axis,
        and per-thread frequency in legend (optional) + average frequency label.
      • Memory/Swap filled area plot (left % axis).
      • Network RX/TX plot with autoscaling.
    Performance:
      - Separate timers: plots (graphs) vs text (legend & labels).
      - Optional per-CPU frequencies to save syscalls when disabled.
    """
    # Defaults (can be changed live from Preferences)
    HISTORY_SECONDS   = 60
    PLOT_UPDATE_MS    = 150    # graphs cadence
    TEXT_UPDATE_MS    = 1000    # legend/labels cadence
    EMA_ALPHA         = 0.60   # base EMA alpha
    MEM_EMA_ALPHA     = 0.90
    SHOW_CPU_FREQ     = True
    EXTRA_SMOOTHING   = True   # double-EMA for CPU lines (tames spikes)
    THREAD_LINE_WIDTH = 1.5    # px
    SHOW_GRID_X       = True
    SHOW_GRID_Y       = True
    ANTIALIAS         = True

    def __init__(self, parent=None):
        super().__init__(parent)

        # Global plot settings
        pg.setConfigOptions(antialias=self.ANTIALIAS)
        pg.setConfigOption('background', (30, 30, 30))
        pg.setConfigOption('foreground', 'w')

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # ----- CPU plot (time bottom axis, percent left axis) -----
        self.n_cpu = psutil.cpu_count(logical=True) or 1
        history_len = self._history_len()

        self.cpu_axis_bottom = TimeAxisItem(history_len, self.PLOT_UPDATE_MS / 1000.0)
        self.cpu_axis_left   = PercentAxisItem()
        self.cpu_plot = pg.PlotWidget(axisItems={'bottom': self.cpu_axis_bottom, 'left': self.cpu_axis_left})
        self.cpu_plot.showAxis('right', False)  # ensure right axis hidden
        self._apply_grid(self.cpu_plot)
        self.cpu_plot.setYRange(0, 100)
        self.cpu_plot.setMouseEnabled(x=False, y=False)
        self.cpu_plot.setMenuEnabled(False)
        self.cpu_plot.setXRange(0, history_len - 1)

        # Colors & pens (HSV palette to start, user can override via legend)
        self.cpu_colors: List[QtGui.QColor] = []
        self.cpu_curves, self.cpu_histories = [], []
        self.cpu_plot_ema1 = [0.0] * self.n_cpu   # for double EMA (extra smoothing)
        self.cpu_plot_ema2 = [0.0] * self.n_cpu
        for i in range(self.n_cpu):
            hue = i / max(1, self.n_cpu)
            color = QtGui.QColor.fromHsvF(hue, 0.75, 0.95, 1.0)
            self.cpu_colors.append(color)
        for i in range(self.n_cpu):
            history = deque([0.0] * history_len, maxlen=history_len)
            self.cpu_histories.append(history)
            pen = pg.mkPen(color=self.cpu_colors[i], width=self.THREAD_LINE_WIDTH)
            curve = self.cpu_plot.plot([0] * history_len, pen=pen, name=f"CPU{i+1}")
            try:
                curve.setClipToView(True)
                curve.setDownsampling(auto=True, method='mean')
            except Exception:
                pass
            self.cpu_curves.append(curve)

        legend_labels = [f"CPU{i+1}" for i in range(self.n_cpu)]
        # Legend in a scroll area (max 4 columns; grows downward)
        self.cpu_legend_grid = LegendGrid(legend_labels, self.cpu_colors, self._on_color_change, columns=4)
        self.cpu_legend_scroll = QtWidgets.QScrollArea()
        self.cpu_legend_scroll.setWidget(self.cpu_legend_grid)
        self.cpu_legend_scroll.setWidgetResizable(True)
        self.cpu_legend_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.cpu_legend_scroll.setMaximumHeight(240)

        # Average frequency label (visible only when SHOW_CPU_FREQ is True)
        self.cpu_freq_avg_label = QtWidgets.QLabel("Average frequency: —")
        self.cpu_freq_avg_label.setStyleSheet("color:#bbbbbb; margin-left:2px;")

        # ----- Memory / Swap (left % axis) -----
        self.mem_axis_bottom = TimeAxisItem(history_len, self.PLOT_UPDATE_MS / 1000.0)
        self.mem_axis_left   = PercentAxisItem()
        self.mem_plot = pg.PlotWidget(axisItems={'bottom': self.mem_axis_bottom, 'left': self.mem_axis_left})
        self.mem_plot.showAxis('right', False)
        self._apply_grid(self.mem_plot)
        self.mem_plot.setYRange(0, 100)
        self.mem_plot.setMouseEnabled(x=False, y=False)
        self.mem_plot.setMenuEnabled(False)
        self.mem_plot.setXRange(0, history_len - 1)

        self.mem_hist = deque([0.0] * history_len, maxlen=history_len)
        self.swap_hist = deque([0.0] * history_len, maxlen=history_len)

        self.mem_base = pg.PlotCurveItem([0] * history_len, pen=None)
        self.mem_curve = pg.PlotCurveItem(pen=pg.mkPen(width=2))
        self.mem_fill = pg.FillBetweenItem(self.mem_curve, self.mem_base, brush=(60, 130, 200, 80))
        self.mem_plot.addItem(self.mem_base)
        self.mem_plot.addItem(self.mem_curve)
        self.mem_plot.addItem(self.mem_fill)

        self.swap_base = pg.PlotCurveItem([0] * history_len, pen=None)
        self.swap_curve = pg.PlotCurveItem(pen=pg.mkPen((200, 120, 60), width=2, style=QtCore.Qt.DashLine))
        self.swap_fill = pg.FillBetweenItem(self.swap_curve, self.swap_base, brush=(200, 120, 60, 60))
        self.mem_plot.addItem(self.swap_base)
        self.mem_plot.addItem(self.swap_curve)
        self.mem_plot.addItem(self.swap_fill)

        self.mem_label = QtWidgets.QLabel("Memory —")
        self.mem_label.setStyleSheet("color:white;")

        # ----- Network (left numeric axis) -----
        self.net_axis_bottom = TimeAxisItem(history_len, self.PLOT_UPDATE_MS / 1000.0)
        self.net_plot = pg.PlotWidget(axisItems={'bottom': self.net_axis_bottom, 'left': pg.AxisItem('left')})
        self.net_plot.showAxis('right', False)
        self._apply_grid(self.net_plot)
        self.net_plot.setMouseEnabled(x=False, y=False)
        self.net_plot.setMenuEnabled(False)
        self.net_plot.setXRange(0, history_len - 1)

        self.rx_hist = deque([0.0] * history_len, maxlen=history_len)
        self.tx_hist = deque([0.0] * history_len, maxlen=history_len)
        self.rx_curve = self.net_plot.plot([0] * history_len, pen=pg.mkPen((100, 180, 255), width=2))
        self.tx_curve = self.net_plot.plot([0] * history_len, pen=pg.mkPen((255, 120, 100), width=2))
        self.net_label = QtWidgets.QLabel("Receiving —  Sending —")
        self.net_label.setStyleSheet("color:white;")

        # Text placeholders updated by the text timer
        self._mem_label_text = "Memory —"
        self._net_label_text = "Receiving —  Sending —"

        # ----- Assemble layout -----
        layout.addWidget(self.cpu_plot, stretch=3)
        layout.addWidget(self.cpu_legend_scroll)
        layout.addWidget(self.cpu_freq_avg_label)
        layout.addWidget(self.mem_plot, stretch=2)
        layout.addWidget(self.mem_label)
        layout.addWidget(self.net_plot, stretch=2)
        layout.addWidget(self.net_label)

        # ----- Initial state & timers -----
        self.prev_net = psutil.net_io_counters(pernic=False)
        self.prev_t = time.monotonic()

        self.cpu_last_raw = [0.0] * self.n_cpu
        self.cpu_display_ema1 = [0.0] * self.n_cpu  # legend smoothing (double-EMA)
        self.cpu_display_ema2 = [0.0] * self.n_cpu

        psutil.cpu_percent(percpu=True)  # warm-up to set baselines

        # Separate timers: plot vs stats
        self.plot_timer = QtCore.QTimer(self)
        self.plot_timer.timeout.connect(self._update_plots)
        self.plot_timer.start(self.PLOT_UPDATE_MS)

        self.text_timer = QtCore.QTimer(self)
        self.text_timer.timeout.connect(self._update_text)
        self.text_timer.start(self.TEXT_UPDATE_MS)

        self._apply_freq_visibility()
        self._update_plots()
        self._update_text()

    # ---------- helpers ----------
    def _history_len(self) -> int:
        return max(1, int(self.HISTORY_SECONDS * 1000 / self.PLOT_UPDATE_MS))

    def _apply_grid(self, plot: pg.PlotWidget):
        plot.showGrid(x=self.SHOW_GRID_X, y=self.SHOW_GRID_Y, alpha=0.2)

    def _on_color_change(self, cpu_index: int, color: QtGui.QColor):
        """Legend callback: update curve and local color store."""
        if 0 <= cpu_index < len(self.cpu_curves):
            self.cpu_colors[cpu_index] = color
            pen = pg.mkPen(color=color, width=self.THREAD_LINE_WIDTH)
            self.cpu_curves[cpu_index].setPen(pen)

    def _apply_freq_visibility(self):
        self.cpu_freq_avg_label.setVisible(self.SHOW_CPU_FREQ)

    # ---------- public API (Preferences) ----------
    def apply_settings(
        self,
        history_seconds: int,
        plot_update_ms: int,
        text_update_ms: int,
        ema_alpha: float,
        mem_ema_alpha: float,
        show_cpu_freq: bool,
        thread_line_width: float,
        show_grid_x: bool,
        show_grid_y: bool,
        extra_smoothing: bool,
        antialias: bool,
    ):
        """Rebuild buffers/axes and timers according to Preferences."""
        self.HISTORY_SECONDS   = int(max(5, history_seconds))
        self.PLOT_UPDATE_MS    = int(max(50, plot_update_ms))
        self.TEXT_UPDATE_MS    = int(max(50, text_update_ms))
        self.EMA_ALPHA         = float(min(0.999, max(0.0, ema_alpha)))
        self.MEM_EMA_ALPHA     = float(min(0.999, max(0.0, mem_ema_alpha)))
        self.SHOW_CPU_FREQ     = bool(show_cpu_freq)
        self.THREAD_LINE_WIDTH = float(max(0.5, thread_line_width))
        self.SHOW_GRID_X       = bool(show_grid_x)
        self.SHOW_GRID_Y       = bool(show_grid_y)
        self.EXTRA_SMOOTHING   = bool(extra_smoothing)
        self.ANTIALIAS         = bool(antialias)
        pg.setConfigOptions(antialias=self.ANTIALIAS)

        # Update timers
        if self.plot_timer.isActive():  self.plot_timer.stop()
        if self.text_timer.isActive(): self.text_timer.stop()
        self.plot_timer.start(self.PLOT_UPDATE_MS)
        self.text_timer.start(self.TEXT_UPDATE_MS)

        # Axes / ranges / grids
        history_len = self._history_len()
        for axis in (self.cpu_axis_bottom, self.mem_axis_bottom, self.net_axis_bottom):
            axis.update_params(history_len, self.PLOT_UPDATE_MS / 1000.0)
        for plot in (self.cpu_plot, self.mem_plot, self.net_plot):
            plot.setXRange(0, history_len - 1)
            self._apply_grid(plot)

        # Rebuild buffers for graphs
        self.cpu_histories = [deque([0.0] * history_len, maxlen=history_len) for _ in range(self.n_cpu)]
        for i, curve in enumerate(self.cpu_curves):
            pen = pg.mkPen(color=self.cpu_colors[i], width=self.THREAD_LINE_WIDTH)
            curve.setPen(pen)
            curve.setData([0.0] * history_len)
        self.cpu_plot_ema1 = [0.0] * self.n_cpu
        self.cpu_plot_ema2 = [0.0] * self.n_cpu

        self.mem_hist = deque([0.0] * history_len, maxlen=history_len)
        self.swap_hist = deque([0.0] * history_len, maxlen=history_len)
        self.mem_base.setData(list(range(history_len)), [0] * history_len)
        self.swap_base.setData(list(range(history_len)), [0] * history_len)
        self.rx_hist = deque([0.0] * history_len, maxlen=history_len)
        self.tx_hist = deque([0.0] * history_len, maxlen=history_len)

        # Frequencies visibility
        self._apply_freq_visibility()

    # ---------- TEXT TIMER (legend & labels) ----------
    def _update_text(self):
        # Per-CPU usage (store raw, then double-EMA for stable legend)
        per = psutil.cpu_percent(interval=None, percpu=True)
        n = min(len(per), self.n_cpu)
        usages = []
        for i in range(n):
            raw = float(per[i])
            self.cpu_last_raw[i] = raw
            # Double EMA to tame spikes while keeping responsiveness
            a = self.EMA_ALPHA
            self.cpu_display_ema1[i] = a * self.cpu_display_ema1[i] + (1.0 - a) * raw
            self.cpu_display_ema2[i] = a * self.cpu_display_ema2[i] + (1.0 - a) * self.cpu_display_ema1[i]
            smoothed = 2 * self.cpu_display_ema1[i] - self.cpu_display_ema2[i] if self.EXTRA_SMOOTHING else self.cpu_display_ema1[i]
            usages.append(smoothed)

        # Optional per-CPU frequency + average
        per_freq_mhz: Optional[List[float]] = None
        avg_freq = None
        if self.SHOW_CPU_FREQ:
            try:
                freqs = psutil.cpu_freq(percpu=True)
                if freqs:
                    per_freq_mhz = [getattr(f, 'current', 0.0) for f in freqs[:self.n_cpu]]
                    valid = [f for f in per_freq_mhz if f and f > 0]
                    if valid:
                        avg_freq = sum(valid) / len(valid)
            except Exception:
                pass

        self.cpu_legend_grid.set_values(usages, per_freq_mhz)
        self.cpu_freq_avg_label.setVisible(self.SHOW_CPU_FREQ)
        if self.SHOW_CPU_FREQ:
            self.cpu_freq_avg_label.setText(
                f"Average frequency: {human_freq(avg_freq)}" if avg_freq else "Average frequency: —"
            )

        # Update cached labels for memory and network
        self.mem_label.setText(self._mem_label_text)
        self.net_label.setText(self._net_label_text)
    # ---------- PLOT TIMER (graphs only) ----------
    def _update_plots(self):
        # CPU: double-EMA toward the latest raw usage values for smooth lines
        a = self.EMA_ALPHA
        for i in range(self.n_cpu):
            self.cpu_plot_ema1[i] = a * self.cpu_plot_ema1[i] + (1.0 - a) * self.cpu_last_raw[i]
            if self.EXTRA_SMOOTHING:
                self.cpu_plot_ema2[i] = a * self.cpu_plot_ema2[i] + (1.0 - a) * self.cpu_plot_ema1[i]
                use_val = 2 * self.cpu_plot_ema1[i] - self.cpu_plot_ema2[i]
            else:
                use_val = self.cpu_plot_ema1[i]
            self.cpu_histories[i].append(use_val)
            self.cpu_curves[i].setData(list(self.cpu_histories[i]))

        # Memory / Swap (EMA)
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        mem_val = vm.percent
        swap_val = sm.percent if sm.total > 0 else 0.0
        mem_ema = self.MEM_EMA_ALPHA * (self.mem_hist[-1] if self.mem_hist else 0.0) + (1.0 - self.MEM_EMA_ALPHA) * mem_val
        swap_ema = self.MEM_EMA_ALPHA * (self.swap_hist[-1] if self.swap_hist else 0.0) + (1.0 - self.MEM_EMA_ALPHA) * swap_val

        self.mem_hist.append(mem_ema)
        self.swap_hist.append(swap_ema)
        x = list(range(len(self.mem_hist)))
        self.mem_curve.setData(x, list(self.mem_hist))
        self.mem_base.setData(x, [0] * len(x))
        self.swap_curve.setData(x, list(self.swap_hist))
        self.swap_base.setData(x, [0] * len(x))

        cache_txt = f"Cache {human_bytes(getattr(vm, 'cached', 0))}" if getattr(vm, 'cached', 0) else "Cache —"
        swap_txt = "Swap not available" if sm.total == 0 else f"Swap {swap_ema:.1f}% of {human_bytes(sm.total)}"
        self._mem_label_text = (
            f"Memory {human_bytes(vm.used)} ({mem_ema:.1f}%) of {human_bytes(vm.total)} — {cache_txt}   |   {swap_txt}"
        )

        # Network rates
        now = time.monotonic()
        dt = max(1e-6, now - self.prev_t)
        cur = psutil.net_io_counters(pernic=False)
        rx_kib = (cur.bytes_recv - self.prev_net.bytes_recv) / 1024.0 / dt
        tx_kib = (cur.bytes_sent - self.prev_net.bytes_sent) / 1024.0 / dt
        self.prev_net, self.prev_t = cur, now

        self.rx_hist.append(rx_kib)
        self.tx_hist.append(tx_kib)
        x = list(range(len(self.rx_hist)))
        self.rx_curve.setData(x, list(self.rx_hist))
        self.tx_curve.setData(x, list(self.tx_hist))

        max_y = max(1.0, max(max(self.rx_hist), max(self.tx_hist)))
        self.net_plot.setYRange(0, max_y * 1.2)
        self._net_label_text = (
            f"Receiving {rx_kib:,.1f} KiB/s — Total {human_bytes(cur.bytes_recv)}     "
            f"Sending {tx_kib:,.1f} KiB/s — Total {human_bytes(cur.bytes_sent)}"
        )


# ------------------------------- Processes tab -------------------------------

class ProcessesTab(QtWidgets.QWidget):
    """
    Process table (name, user, %CPU, PID, RSS, IO totals, IO rates, cmdline).
    Efficient refresh:
      - Sorting & painting disabled during batch update.
      - Rows updated in place; removals done in descending order.
      - Caches cleaned when processes exit (no growth over time).
    """
    UPDATE_MS = 1000
    COLUMNS = [
        "Process Name", "User", "% CPU", "ID",
        "Memory", "Disk read total", "Disk write total",
        "Disk read", "Disk write", "Cmdline"
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Interactive)

        widths = [220, 110, 80, 80, 120, 140, 140, 120, 120, 600]
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)

        layout.addWidget(self.table)

        self.prev_io: Dict[int, Tuple[int, int]] = {}
        self.prev_time = time.monotonic()
        self.row_for_pid: Dict[int, int] = {}

        for p in psutil.process_iter(['pid']):
            try:
                p.cpu_percent(None)
            except Exception:
                pass

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.UPDATE_MS)

    def _item(self, text: str, sort_value=None, tip: str = "") -> QtWidgets.QTableWidgetItem:
        it = QtWidgets.QTableWidgetItem(text)
        it.setToolTip(tip if tip else text)
        it.setData(QtCore.Qt.UserRole, text if sort_value is None else sort_value)
        return it

    def _set_row(self, row: int, cols):
        for c, (txt, sortv, tip) in enumerate(cols):
            self.table.setItem(row, c, self._item(txt, sortv, tip))

    def refresh(self):
        now = time.monotonic()
        dt = max(1e-6, now - self.prev_time)
        seen = set()

        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)

        try:
            for proc in psutil.process_iter([
                'pid', 'name', 'username', 'cpu_percent',
                'memory_info', 'io_counters', 'cmdline'
            ]):
                info = proc.info
                pid = info['pid']
                seen.add(pid)

                name = info.get('name') or ""
                user = info.get('username') or ""

                cpu = float(info.get('cpu_percent') or 0.0)

                mem_txt, mem_sort = "—", 0
                meminfo = info.get('memory_info')
                if meminfo is not None:
                    rss = getattr(meminfo, 'rss', 0)
                    if rss:
                        mem_txt, mem_sort = human_bytes(rss), rss

                read_total = write_total = 0
                read_rate = write_rate = 0.0
                io = info.get('io_counters')
                if io is not None:
                    read_total = getattr(io, 'read_bytes', 0)
                    write_total = getattr(io, 'write_bytes', 0)
                    prev = self.prev_io.get(pid)
                    if prev:
                        read_rate  = max(0, read_total  - prev[0]) / 1024.0 / dt
                        write_rate = max(0, write_total - prev[1]) / 1024.0 / dt
                    self.prev_io[pid] = (read_total, write_total)

                cmdline_list = info.get('cmdline') or []
                cmdline = " ".join(cmdline_list) if cmdline_list else ""

                if pid in self.row_for_pid:
                    row = self.row_for_pid[pid]
                else:
                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    self.row_for_pid[pid] = row

                cols = [
                    (name, name.lower(), cmdline or name),
                    (user, user.lower(), user),
                    (f"{cpu:.2f}", cpu, f"{cpu:.2f}%"),
                    (str(pid), pid, str(pid)),
                    (mem_txt, mem_sort, mem_txt),
                    (human_bytes(read_total), read_total, human_bytes(read_total)),
                    (human_bytes(write_total), write_total, human_bytes(write_total)),
                    (human_rate_kib(read_rate), read_rate, f"{read_rate:.2f} KiB/s"),
                    (human_rate_kib(write_rate), write_rate, f"{write_rate:.2f} KiB/s"),
                    (cmdline if cmdline else "—", cmdline.lower() if cmdline else "", cmdline),
                ]
                self._set_row(row, cols)

            # Remove finished processes safely
            gone_pids = [pid for pid in list(self.row_for_pid.keys()) if pid not in seen]
            rows_to_remove = []
            for pid in gone_pids:
                row = self.row_for_pid.pop(pid, None)
                if row is not None:
                    rows_to_remove.append(row)
                self.prev_io.pop(pid, None)
            for row in sorted(set(rows_to_remove), reverse=True):
                if 0 <= row < self.table.rowCount():
                    self.table.removeRow(row)

            # Rebuild mapping
            new_map: Dict[int, int] = {}
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 3)
                if it:
                    try:
                        new_map[int(it.text())] = r
                    except ValueError:
                        pass
            self.row_for_pid = new_map

        finally:
            self.prev_time = now
            self.table.setUpdatesEnabled(True)
            self.table.setSortingEnabled(was_sorting)


# ------------------------------- File Systems tab -------------------------------

class FileSystemsTab(QtWidgets.QWidget):
    """
    Mounted file systems table (like Ubuntu):
      - Device | Directory | Type | Total | Available | Used (with progress bar)
    Plus a second table with per-disk I/O totals and rates.
    Refreshed on demand when the tab becomes visible.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(12)

        # --- Mounted file systems (progress bar in "Used") ---
        self.mounts_label = QtWidgets.QLabel("Mounted File Systems")
        self.mounts_label.setStyleSheet("font-weight:bold;")
        self.mounts = QtWidgets.QTableWidget(0, 6)
        self.mounts.setHorizontalHeaderLabels(
            ["Device", "Directory", "Type", "Total", "Available", "Used"]
        )
        self.mounts.setSortingEnabled(True)
        self.mounts.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.mounts.verticalHeader().setVisible(False)
        self.mounts.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        for i, w in enumerate([180, 260, 90, 130, 130, 200]):
            self.mounts.setColumnWidth(i, w)

        # --- Disk I/O table (as before) ---
        self.io_label = QtWidgets.QLabel("Disk I/O")
        self.io_label.setStyleSheet("font-weight:bold;")
        self.disks = QtWidgets.QTableWidget(0, 8)
        self.disks.setHorizontalHeaderLabels(
            ["Disk", "Read total", "Write total", "Read/s", "Write/s", "Reads", "Writes", "Busy time"]
        )
        self.disks.setSortingEnabled(True)
        self.disks.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.disks.verticalHeader().setVisible(False)
        self.disks.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        for i, w in enumerate([120, 140, 140, 110, 110, 90, 90, 110]):
            self.disks.setColumnWidth(i, w)

        main.addWidget(self.mounts_label)
        main.addWidget(self.mounts)
        main.addSpacing(10)
        main.addWidget(self.io_label)
        main.addWidget(self.disks)

        self.prev_disk: Dict[str, psutil._common.sdiskio] = {}
        self.prev_t = time.monotonic()

        # Populate once; refreshed again when tab is shown
        self.refresh()

    def _progress_cell(self, percent: float, used_text: str) -> QtWidgets.QWidget:
        """Return a QWidget containing a progress bar with 'used_text' as label."""
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(4, 2, 4, 2)
        p = QtWidgets.QProgressBar()
        p.setRange(0, 100)
        p.setValue(int(round(percent)))
        p.setFormat(f"{used_text}   {percent:.0f}%")
        p.setTextVisible(True)
        p.setFixedHeight(18)
        lay.addWidget(p)
        return w

    def refresh(self):
        # ----- Mounted partitions with progress bar -----
        try:
            parts = psutil.disk_partitions(all=False)
        except Exception:
            parts = []

        self.mounts.setRowCount(0)
        for p in parts:
            try:
                usage = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue
            if not p.device or usage.total <= 0:
                continue
            row = self.mounts.rowCount()
            self.mounts.insertRow(row)

            self.mounts.setItem(row, 0, QtWidgets.QTableWidgetItem(p.device or "—"))
            self.mounts.setItem(row, 1, QtWidgets.QTableWidgetItem(p.mountpoint))
            self.mounts.setItem(row, 2, QtWidgets.QTableWidgetItem(p.fstype or "—"))
            self.mounts.setItem(row, 3, QtWidgets.QTableWidgetItem(human_bytes(usage.total)))
            self.mounts.setItem(row, 4, QtWidgets.QTableWidgetItem(human_bytes(usage.free)))

            used_text = human_bytes(usage.used)
            used_widget = self._progress_cell(usage.percent, used_text)
            self.mounts.setCellWidget(row, 5, used_widget)

        # ----- Per-disk I/O (totals + rates) -----
        now = time.monotonic()
        dt = max(1e-6, now - self.prev_t)
        try:
            io_per = psutil.disk_io_counters(perdisk=True)
        except Exception:
            io_per = {}

        self.disks.setRowCount(0)
        for disk, io in io_per.items():
            read_total = getattr(io, 'read_bytes', 0)
            write_total = getattr(io, 'write_bytes', 0)
            reads = getattr(io, 'read_count', 0)
            writes = getattr(io, 'write_count', 0)
            busy = getattr(io, 'busy_time', 0) if hasattr(io, 'busy_time') else 0

            prev = self.prev_disk.get(disk)
            read_s = write_s = 0.0
            if prev:
                read_s = max(0, read_total - getattr(prev, 'read_bytes', 0)) / 1024.0 / dt
                write_s = max(0, write_total - getattr(prev, 'write_bytes', 0)) / 1024.0 / dt
            self.prev_disk[disk] = io

            row = self.disks.rowCount()
            self.disks.insertRow(row)
            self.disks.setItem(row, 0, QtWidgets.QTableWidgetItem(disk))
            self.disks.setItem(row, 1, QtWidgets.QTableWidgetItem(human_bytes(read_total)))
            self.disks.setItem(row, 2, QtWidgets.QTableWidgetItem(human_bytes(write_total)))
            self.disks.setItem(row, 3, QtWidgets.QTableWidgetItem(human_rate_kib(read_s)))
            self.disks.setItem(row, 4, QtWidgets.QTableWidgetItem(human_rate_kib(write_s)))
            self.disks.setItem(row, 5, QtWidgets.QTableWidgetItem(str(reads)))
            self.disks.setItem(row, 6, QtWidgets.QTableWidgetItem(str(writes)))
            self.disks.setItem(row, 7, QtWidgets.QTableWidgetItem(f"{busy} ms" if busy else "—"))

        self.prev_t = now

    def showEvent(self, e: QtGui.QShowEvent):
        self.refresh()
        super().showEvent(e)


# ------------------------------- Preferences dialog -------------------------------

class PreferencesDialog(QtWidgets.QDialog):
    """
    Tune the Resources tab at runtime:
      - History window (seconds)
      - Plot update interval (ms)  [graphs]
      - Text update interval (ms) [legend numbers & labels]
      - CPU EMA alpha
      - Memory EMA alpha
      - Show per-CPU frequencies
      - Thread line width (px)
      - Toggle X grid / Y grid
      - Extra smoothing (double-EMA) for CPU lines
      - Enable/disable antialiasing
    """
    def __init__(self, resources_tab: ResourcesTab, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resources_tab = resources_tab

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.in_history = QtWidgets.QSpinBox()
        self.in_history.setRange(5, 3600)
        self.in_history.setValue(resources_tab.HISTORY_SECONDS)

        self.in_plot = QtWidgets.QSpinBox()
        self.in_plot.setRange(50, 5000)
        self.in_plot.setSingleStep(10)
        self.in_plot.setValue(resources_tab.PLOT_UPDATE_MS)

        self.in_text = QtWidgets.QSpinBox()
        self.in_text.setRange(50, 5000)
        self.in_text.setSingleStep(10)
        self.in_text.setValue(resources_tab.TEXT_UPDATE_MS)

        self.in_ema = QtWidgets.QDoubleSpinBox()
        self.in_ema.setDecimals(3)
        self.in_ema.setRange(0.0, 0.999)
        self.in_ema.setSingleStep(0.01)
        self.in_ema.setValue(resources_tab.EMA_ALPHA)

        self.in_mem_ema = QtWidgets.QDoubleSpinBox()
        self.in_mem_ema.setDecimals(3)
        self.in_mem_ema.setRange(0.0, 0.999)
        self.in_mem_ema.setSingleStep(0.01)
        self.in_mem_ema.setValue(resources_tab.MEM_EMA_ALPHA)

        self.in_show_freq = QtWidgets.QCheckBox("Show per-CPU frequencies (and average)")
        self.in_show_freq.setChecked(resources_tab.SHOW_CPU_FREQ)

        self.in_width = QtWidgets.QDoubleSpinBox()
        self.in_width.setRange(0.5, 8.0)
        self.in_width.setSingleStep(0.5)
        self.in_width.setValue(resources_tab.THREAD_LINE_WIDTH)

        self.in_grid_x = QtWidgets.QCheckBox("Show X grid")
        self.in_grid_x.setChecked(resources_tab.SHOW_GRID_X)
        self.in_grid_y = QtWidgets.QCheckBox("Show Y grid")
        self.in_grid_y.setChecked(resources_tab.SHOW_GRID_Y)

        self.in_extra = QtWidgets.QCheckBox("Extra smoothing for CPU lines (double-EMA)")
        self.in_extra.setChecked(resources_tab.EXTRA_SMOOTHING)

        self.in_antialias = QtWidgets.QCheckBox("Enable antialiasing (smooth curves)")
        self.in_antialias.setChecked(resources_tab.ANTIALIAS)

        form.addRow("History window (seconds):", self.in_history)
        form.addRow("Plot update interval (ms):", self.in_plot)
        form.addRow("Text update interval (ms):", self.in_text)
        form.addRow("CPU EMA alpha (0–0.999):", self.in_ema)
        form.addRow("Memory EMA alpha (0–0.999):", self.in_mem_ema)
        form.addRow(self.in_show_freq)
        form.addRow("Thread line width (px):", self.in_width)
        form.addRow(self.in_grid_x)
        form.addRow(self.in_grid_y)
        form.addRow(self.in_extra)
        form.addRow(self.in_antialias)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self.apply)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

    def _read_values(self):
        return (
            int(self.in_history.value()),
            int(self.in_plot.value()),
            int(self.in_text.value()),
            float(self.in_ema.value()),
            float(self.in_mem_ema.value()),
            bool(self.in_show_freq.isChecked()),
            float(self.in_width.value()),
            bool(self.in_grid_x.isChecked()),
            bool(self.in_grid_y.isChecked()),
            bool(self.in_extra.isChecked()),
            bool(self.in_antialias.isChecked()),
        )

    def apply(self):
        self.resources_tab.apply_settings(*self._read_values())

    def accept(self):
        self.apply()
        super().accept()


# ------------------------------- Main window -------------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KLV System Monitor")
        self.resize(860, 900)

        # Centered tabs
        self.tabs = CenteredTabWidget()
        self.processes_tab   = ProcessesTab()
        self.resources_tab   = ResourcesTab()
        self.filesystems_tab = FileSystemsTab()
        self.tabs.addTab(self.processes_tab,  "Processes")
        self.tabs.addTab(self.resources_tab,  "Resources")
        self.tabs.addTab(self.filesystems_tab,"File Systems")

        # Put centered tabs into the main area
        container = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(container)
        v.setContentsMargins(6, 6, 6, 6)
        v.addWidget(self.tabs)
        self.setCentralWidget(container)

        # Toolbar with Preferences (right aligned)
        tb = QtWidgets.QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(18, 18))
        self.addToolBar(QtCore.Qt.TopToolBarArea, tb)

        pref_act = QtWidgets.QAction("Preferences", self)
        pref_act.triggered.connect(self.open_preferences)
        tb.addAction(pref_act)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        tb.addWidget(spacer)

    def open_preferences(self):
        dlg = PreferencesDialog(self.resources_tab, self)
        dlg.exec_()


def main():
    app = QtWidgets.QApplication(sys.argv)
    set_dark_palette(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
