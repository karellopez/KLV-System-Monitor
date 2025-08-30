# klv_system_monitor.py
# Cross-platform “Ubuntu-style” System Monitor with centered tabs:
#   • Processes   • Resources   • File Systems
#
# New in this version:
#   - Left Y axis with % labels (right axis hidden).
#   - Click colored swatch in the CPU legend to choose a custom color per thread.
#   - File Systems tab: percentage column shows a progress bar.
#   - Preferences: antialiasing toggle, thread line width, toggle X/Y grid,
#                  extra smoothing (double-EMA), and all previous knobs
#                  (history, update cadences, EMA alphas, show per-CPU frequencies).
#   - Separate plot vs text refresh intervals.
#   - File Systems tab refreshes only when visible and its interval is configurable.
#   - Processes tab refreshes only when visible and its interval is configurable.
#   - Processes tab adds buttons to clear the selection and kill processes.
#
# Dependencies: psutil, PyQt5, pyqtgraph
# License: MIT (adjust as desired)

import sys
import time
import json
from collections import deque
from typing import Dict, Tuple, List, Optional
from pathlib import Path

import platform
import threading
import os
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

# Data acquisition helpers are kept separate from the GUI layer so that
# all system queries live outside of this module.
from .data_acquisition import cpu, memory, network, processes, disks

# Directory used to store persistent user preferences
PREF_DIR = Path(__file__).resolve().parent / "user_preferences"

# Default theme name (also used when restoring preferences)
DEFAULT_THEME = "Deep Dark"

# Simple OS helpers
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


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


def build_theme_dict() -> Dict[str, QtGui.QPalette]:
    """Return dictionary mapping theme names to QPalettes."""
    themes: Dict[str, QtGui.QPalette] = {}

    deep = QtGui.QPalette()
    deep.setColor(QtGui.QPalette.Window, QtGui.QColor(30, 30, 30))
    deep.setColor(QtGui.QPalette.WindowText, QtGui.QColor(220, 220, 220))
    deep.setColor(QtGui.QPalette.Base, QtGui.QColor(40, 40, 40))
    deep.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(50, 50, 50))
    deep.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(255, 255, 220))
    deep.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(0, 0, 0))
    deep.setColor(QtGui.QPalette.Text, QtGui.QColor(220, 220, 220))
    deep.setColor(QtGui.QPalette.Button, QtGui.QColor(45, 45, 45))
    deep.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(220, 220, 220))
    deep.setColor(QtGui.QPalette.Highlight, QtGui.QColor(53, 132, 228))
    deep.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
    themes["Deep Dark"] = deep

    dark_purple = QtGui.QPalette()
    dark_purple.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    dark_purple.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    dark_purple.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    dark_purple.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    dark_purple.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(65, 65, 65))
    dark_purple.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    dark_purple.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    dark_purple.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    dark_purple.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    dark_purple.setColor(QtGui.QPalette.Highlight, QtGui.QColor(142, 45, 197))
    dark_purple.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Dark-purple"] = dark_purple

    dark_blue = QtGui.QPalette()
    dark_blue.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    dark_blue.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    dark_blue.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    dark_blue.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    dark_blue.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(65, 65, 65))
    dark_blue.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    dark_blue.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    dark_blue.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    dark_blue.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    dark_blue.setColor(QtGui.QPalette.Highlight, QtGui.QColor(65, 105, 225))
    dark_blue.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Dark-blue"] = dark_blue

    dark_gold = QtGui.QPalette()
    dark_gold.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    dark_gold.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    dark_gold.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    dark_gold.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    dark_gold.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(65, 65, 65))
    dark_gold.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    dark_gold.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    dark_gold.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    dark_gold.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    dark_gold.setColor(QtGui.QPalette.Highlight, QtGui.QColor(255, 215, 0))
    dark_gold.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Dark-gold"] = dark_gold

    light = QtGui.QPalette()
    light.setColor(QtGui.QPalette.Window, QtGui.QColor(210, 210, 210)) 
    light.setColor(QtGui.QPalette.WindowText, QtCore.Qt.black)
    light.setColor(QtGui.QPalette.Base, QtGui.QColor(230, 230, 230))  
    light.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(210, 210, 210))  
    light.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(230, 230, 230))
    light.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.black)
    light.setColor(QtGui.QPalette.Text, QtCore.Qt.black)
    light.setColor(QtGui.QPalette.Button, QtGui.QColor(215, 215, 215))  
    light.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.black)
    light.setColor(QtGui.QPalette.Highlight, QtGui.QColor(53, 132, 228)) 
    light.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    themes["Light"] = light

    beige = QtGui.QPalette()
    beige.setColor(QtGui.QPalette.Window, QtGui.QColor(239, 235, 222))
    beige.setColor(QtGui.QPalette.WindowText, QtGui.QColor(62, 50, 39))
    beige.setColor(QtGui.QPalette.Base, QtGui.QColor(252, 252, 252))
    beige.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(239, 235, 222))
    beige.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(239, 235, 222))
    beige.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(62, 50, 39))
    beige.setColor(QtGui.QPalette.Text, QtGui.QColor(62, 50, 39))
    beige.setColor(QtGui.QPalette.Button, QtGui.QColor(220, 210, 197))
    beige.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(62, 50, 39))
    beige.setColor(QtGui.QPalette.Highlight, QtGui.QColor(193, 154, 107))
    beige.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    themes["Beige"] = beige

    ocean_dark = QtGui.QPalette()
    ocean_dark.setColor(QtGui.QPalette.Window, QtGui.QColor(38, 50, 56))
    ocean_dark.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    ocean_dark.setColor(QtGui.QPalette.Base, QtGui.QColor(69, 90, 100))
    ocean_dark.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(55, 71, 79))
    ocean_dark.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(38, 50, 56))
    ocean_dark.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    ocean_dark.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    ocean_dark.setColor(QtGui.QPalette.Button, QtGui.QColor(55, 71, 79))
    ocean_dark.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    ocean_dark.setColor(QtGui.QPalette.Highlight, QtGui.QColor(0, 137, 123))
    ocean_dark.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Ocean dark"] = ocean_dark

    ocean_light = QtGui.QPalette()
    ocean_light.setColor(QtGui.QPalette.Window, QtGui.QColor(225, 238, 245))
    ocean_light.setColor(QtGui.QPalette.WindowText, QtCore.Qt.black)
    ocean_light.setColor(QtGui.QPalette.Base, QtGui.QColor(240, 248, 252))
    ocean_light.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(230, 240, 247))
    ocean_light.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(215, 230, 240))
    ocean_light.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.black)
    ocean_light.setColor(QtGui.QPalette.Text, QtCore.Qt.black)
    ocean_light.setColor(QtGui.QPalette.Button, QtGui.QColor(213, 234, 242))
    ocean_light.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.black)
    ocean_light.setColor(QtGui.QPalette.Highlight, QtGui.QColor(0, 123, 167))
    ocean_light.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    themes["Ocean light"] = ocean_light

    hc = QtGui.QPalette()
    hc.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0))
    hc.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    hc.setColor(QtGui.QPalette.Base, QtGui.QColor(0, 0, 0))
    hc.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(55, 55, 55))
    hc.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(0, 0, 0))
    hc.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    hc.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    hc.setColor(QtGui.QPalette.Button, QtGui.QColor(0, 0, 0))
    hc.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    hc.setColor(QtGui.QPalette.Highlight, QtGui.QColor(255, 0, 0))
    hc.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    themes["Contrast"] = hc

    hc_w = QtGui.QPalette()
    hc_w.setColor(QtGui.QPalette.Window, QtCore.Qt.white)
    hc_w.setColor(QtGui.QPalette.WindowText, QtCore.Qt.black)
    hc_w.setColor(QtGui.QPalette.Base, QtCore.Qt.white)
    hc_w.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(200, 200, 200))
    hc_w.setColor(QtGui.QPalette.ToolTipBase, QtCore.Qt.white)
    hc_w.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.black)
    hc_w.setColor(QtGui.QPalette.Text, QtCore.Qt.black)
    hc_w.setColor(QtGui.QPalette.Button, QtCore.Qt.white)
    hc_w.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.black)
    hc_w.setColor(QtGui.QPalette.Highlight, QtCore.Qt.black)
    hc_w.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    themes["Contrast White"] = hc_w

    moon = QtGui.QPalette()
    moon.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 43, 54))
    moon.setColor(QtGui.QPalette.WindowText, QtGui.QColor(253, 246, 227))
    moon.setColor(QtGui.QPalette.Base, QtGui.QColor(7, 54, 66))
    moon.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(0, 43, 54))
    moon.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(7, 54, 66))
    moon.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(253, 246, 227))
    moon.setColor(QtGui.QPalette.Text, QtGui.QColor(253, 246, 227))
    moon.setColor(QtGui.QPalette.Button, QtGui.QColor(7, 54, 66))
    moon.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(253, 246, 227))
    moon.setColor(QtGui.QPalette.Highlight, QtGui.QColor(38, 139, 210))
    moon.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Moon"] = moon

    solar = QtGui.QPalette()
    solar.setColor(QtGui.QPalette.Window, QtGui.QColor(253, 246, 227))
    solar.setColor(QtGui.QPalette.WindowText, QtGui.QColor(101, 123, 131))
    solar.setColor(QtGui.QPalette.Base, QtGui.QColor(255, 250, 240))
    solar.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(253, 246, 227))
    solar.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(238, 232, 213))
    solar.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(88, 110, 117))
    solar.setColor(QtGui.QPalette.Text, QtGui.QColor(88, 110, 117))
    solar.setColor(QtGui.QPalette.Button, QtGui.QColor(238, 232, 213))
    solar.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(88, 110, 117))
    solar.setColor(QtGui.QPalette.Highlight, QtGui.QColor(38, 139, 210))
    solar.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    themes["Solar"] = solar

    cyber = QtGui.QPalette()
    cyber.setColor(QtGui.QPalette.Window, QtGui.QColor(10, 10, 20))
    cyber.setColor(QtGui.QPalette.WindowText, QtGui.QColor(0, 255, 255))
    cyber.setColor(QtGui.QPalette.Base, QtGui.QColor(30, 30, 45))
    cyber.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(25, 25, 35))
    cyber.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(45, 45, 65))
    cyber.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(255, 0, 255))
    cyber.setColor(QtGui.QPalette.Text, QtGui.QColor(0, 255, 255))
    cyber.setColor(QtGui.QPalette.Button, QtGui.QColor(40, 40, 55))
    cyber.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(255, 0, 255))
    cyber.setColor(QtGui.QPalette.Highlight, QtGui.QColor(255, 0, 128))
    cyber.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    themes["Cyber"] = cyber

    drac = QtGui.QPalette()
    drac.setColor(QtGui.QPalette.Window, QtGui.QColor("#282a36"))
    drac.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#f8f8f2"))
    drac.setColor(QtGui.QPalette.Base, QtGui.QColor("#1e1f29"))
    drac.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#282a36"))
    drac.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#44475a"))
    drac.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#f8f8f2"))
    drac.setColor(QtGui.QPalette.Text, QtGui.QColor("#f8f8f2"))
    drac.setColor(QtGui.QPalette.Button, QtGui.QColor("#44475a"))
    drac.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#f8f8f2"))
    drac.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#bd93f9"))
    drac.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Dracula"] = drac

    nord = QtGui.QPalette()
    nord.setColor(QtGui.QPalette.Window, QtGui.QColor("#2e3440"))
    nord.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#d8dee9"))
    nord.setColor(QtGui.QPalette.Base, QtGui.QColor("#3b4252"))
    nord.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#434c5e"))
    nord.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#4c566a"))
    nord.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#eceff4"))
    nord.setColor(QtGui.QPalette.Text, QtGui.QColor("#e5e9f0"))
    nord.setColor(QtGui.QPalette.Button, QtGui.QColor("#4c566a"))
    nord.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#d8dee9"))
    nord.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#88c0d0"))
    nord.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Nord"] = nord

    gruv = QtGui.QPalette()
    gruv.setColor(QtGui.QPalette.Window, QtGui.QColor("#282828"))
    gruv.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#ebdbb2"))
    gruv.setColor(QtGui.QPalette.Base, QtGui.QColor("#32302f"))
    gruv.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#3c3836"))
    gruv.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#504945"))
    gruv.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#fbf1c7"))
    gruv.setColor(QtGui.QPalette.Text, QtGui.QColor("#ebdbb2"))
    gruv.setColor(QtGui.QPalette.Button, QtGui.QColor("#504945"))
    gruv.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#ebdbb2"))
    gruv.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#d79921"))
    gruv.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Gruvbox"] = gruv

    mono = QtGui.QPalette()
    mono.setColor(QtGui.QPalette.Window, QtGui.QColor("#272822"))
    mono.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#f8f8f2"))
    mono.setColor(QtGui.QPalette.Base, QtGui.QColor("#1e1f1c"))
    mono.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#272822"))
    mono.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#3e3d32"))
    mono.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#f8f8f2"))
    mono.setColor(QtGui.QPalette.Text, QtGui.QColor("#f8f8f2"))
    mono.setColor(QtGui.QPalette.Button, QtGui.QColor("#3e3d32"))
    mono.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#f8f8f2"))
    mono.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#a6e22e"))
    mono.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Monokai"] = mono

    tokyo = QtGui.QPalette()
    tokyo.setColor(QtGui.QPalette.Window, QtGui.QColor("#1a1b26"))
    tokyo.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#c0caf5"))
    tokyo.setColor(QtGui.QPalette.Base, QtGui.QColor("#1f2335"))
    tokyo.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#24283b"))
    tokyo.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#414868"))
    tokyo.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#c0caf5"))
    tokyo.setColor(QtGui.QPalette.Text, QtGui.QColor("#c0caf5"))
    tokyo.setColor(QtGui.QPalette.Button, QtGui.QColor("#414868"))
    tokyo.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#c0caf5"))
    tokyo.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#7aa2f7"))
    tokyo.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    themes["Tokyo"] = tokyo

    mocha = QtGui.QPalette()
    mocha.setColor(QtGui.QPalette.Window, QtGui.QColor("#1e1e2e"))
    mocha.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#cdd6f4"))
    mocha.setColor(QtGui.QPalette.Base, QtGui.QColor("#181825"))
    mocha.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#1e1e2e"))
    mocha.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#313244"))
    mocha.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#cdd6f4"))
    mocha.setColor(QtGui.QPalette.Text, QtGui.QColor("#cdd6f4"))
    mocha.setColor(QtGui.QPalette.Button, QtGui.QColor("#313244"))
    mocha.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#cdd6f4"))
    mocha.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#f38ba8"))
    mocha.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Mocha"] = mocha

    pale = QtGui.QPalette()
    pale.setColor(QtGui.QPalette.Window, QtGui.QColor("#292d3e"))
    pale.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#a6accd"))
    pale.setColor(QtGui.QPalette.Base, QtGui.QColor("#1b1d2b"))
    pale.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#222436"))
    pale.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#444267"))
    pale.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#a6accd"))
    pale.setColor(QtGui.QPalette.Text, QtGui.QColor("#a6accd"))
    pale.setColor(QtGui.QPalette.Button, QtGui.QColor("#444267"))
    pale.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#a6accd"))
    pale.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#82aaff"))
    pale.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    themes["Palenight"] = pale

    return themes


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

        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(2)

        self.columns = max(1, min(4, int(columns)))  # hard cap at 4

        for idx, (text, col) in enumerate(zip(labels, colors)):
            r, c = divmod(idx, self.columns)

            swatch = ClickableLabel()
            swatch.setFixedSize(20, 12)
            swatch.setStyleSheet(f"background:{col.name()}; border-radius:2px;")
            swatch.clicked.connect(lambda i=idx: self._pick_color(i))
            self.swatches.append(swatch)

            name = QtWidgets.QLabel(text)

            val = QtWidgets.QLabel("0.0% · —")
            self.value_labels.append(val)

            roww = QtWidgets.QWidget()
            roww.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            rowl = QtWidgets.QHBoxLayout(roww)
            rowl.setContentsMargins(0, 0, 0, 0)
            rowl.addWidget(swatch)
            rowl.addWidget(name)
            rowl.addWidget(val)
            rowl.addStretch(1)
            self.grid.addWidget(roww, r, c)
            self.grid.setColumnStretch(c, 1)

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
                lab.setText(f"{pct:,.1f}% ")


# ------------------------------- Collapsible section -------------------------------

class CollapsibleSection(QtWidgets.QWidget):
    """A simple widget that can hide or show its contents with a click."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.toggle = QtWidgets.QToolButton(text=title, checkable=True, checked=True)
        # Style the toggle so that its text color follows the current palette
        self._update_toggle_style()
        font = self.toggle.font()
        font.setBold(True)
        self.toggle.setFont(font)
        self.toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(QtCore.Qt.DownArrow)
        self.toggle.clicked.connect(self._on_toggle)

        self.content = QtWidgets.QWidget()
        self.content.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.content_layout = QtWidgets.QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(6)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)

        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.default_stretch = 1

    def _update_toggle_style(self):
        """Ensure the section title respects the palette's text color."""
        fg = self.palette().color(QtGui.QPalette.WindowText).name()
        self.toggle.setStyleSheet(
            f"QToolButton {{ border: none; color: {fg}; }}"
        )

    def changeEvent(self, event: QtCore.QEvent):  # type: ignore[override]
        if event.type() == QtCore.QEvent.PaletteChange:
            # When the theme changes, update the toggle color
            self._update_toggle_style()
        super().changeEvent(event)

    def _on_toggle(self):
        visible = self.toggle.isChecked()
        self.content.setVisible(visible)
        self.toggle.setArrowType(QtCore.Qt.DownArrow if visible else QtCore.Qt.RightArrow)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding if visible else QtWidgets.QSizePolicy.Fixed,
        )
        parent = self.parentWidget()
        if parent is not None:
            layout = parent.layout()
            if layout is not None:
                idx = layout.indexOf(self)
                if idx != -1:
                    layout.setStretch(idx, self.default_stretch if visible else 0)

    def add_widget(self, w: QtWidgets.QWidget):
        self.content_layout.addWidget(w)

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
    NET_EMA_ALPHA     = 0.60   # independent network EMA alpha
    SHOW_CPU_FREQ     = IS_LINUX or IS_WINDOWS
    SHOW_CPU_TEMP     = not IS_WINDOWS  # temperature reading not supported on Windows
    SMOOTH_GRAPHS     = True   # global smoothing toggle
    EXTRA_SMOOTHING   = True   # double-EMA for CPU lines (tames spikes)
    THREAD_LINE_WIDTH = 1.5    # px
    SHOW_GRID_X       = True
    SHOW_GRID_Y       = True
    GRID_DIVS         = 10
    ANTIALIAS         = True
    FILL_CPU          = False  # optionally fill area under CPU lines
    SMOOTH_NET_GRAPH  = True   # independent network smoothing toggle
    CPU_FILL_ALPHA    = 80     # alpha value for CPU area fills (0-255)
    CPU_MINI_MIN_W    = 120    # minimum width for mini-plots in multi window
    CPU_MINI_MIN_H    = 80     # minimum height for mini-plots in multi window
    CPU_MULTI_COLS    = 5      # default columns for multi window layout
    CPU_MULTI_AXES    = True   # show axes on mini-plots
    CPU_MULTI_MONO    = False  # use a single color for all mini-plots
    CPU_MULTI_LABEL_INSIDE = True  # place per-CPU labels inside plots
    CPU_MULTI_LABEL_COLOR = "#ffffff"  # color for per-CPU labels
    CPU_MULTI_LABEL_MATCH = False      # label text follows curve color
    CPU_GENERAL_COLOR = ""            # empty means use first CPU color

    # CPU view modes
    CPU_VIEW_MODES = ["Multi thread", "General view", "Multi window"]
    CPU_VIEW_MODE   = "Multi thread"  # default

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
        self.n_cpu = cpu.count(logical=True)
        history_len = self._history_len()
        self.cpu_view_mode = self.CPU_VIEW_MODE

        self.cpu_axis_bottom = TimeAxisItem(history_len, self.PLOT_UPDATE_MS / 1000.0)
        self.cpu_axis_left   = PercentAxisItem()
        self.cpu_plot = pg.PlotWidget(axisItems={'bottom': self.cpu_axis_bottom, 'left': self.cpu_axis_left})
        self.cpu_plot.showAxis('right', False)  # ensure right axis hidden
        self._apply_grid(self.cpu_plot)
        self.cpu_plot.setYRange(0, 100)
        self.cpu_plot.setMouseEnabled(x=False, y=False)
        self.cpu_plot.setMenuEnabled(False)
        self.cpu_plot.setXRange(0, history_len - 1)
        self.cpu_plot.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.cpu_plot.installEventFilter(self)

        # Colors & pens (HSV palette to start, user can override via legend)
        self.cpu_colors: List[QtGui.QColor] = []
        self.cpu_curves, self.cpu_histories = [], []
        self.cpu_plot_ema1 = [0.0] * self.n_cpu   # for double EMA (extra smoothing)
        self.cpu_plot_ema2 = [0.0] * self.n_cpu
        for i in range(self.n_cpu):
            hue = i / max(1, self.n_cpu)
            color = QtGui.QColor.fromHsvF(hue, 0.75, 0.95, 1.0)
            self.cpu_colors.append(color)
        # Default mono-color uses the first generated color
        self.cpu_mono_color = QtGui.QColor(self.cpu_colors[0])
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
        self.cpu_legend_scroll.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        # Average frequency label (visible only when SHOW_CPU_FREQ is True)
        self.cpu_freq_avg_label = QtWidgets.QLabel("Average frequency: —")
        self.cpu_freq_avg_label.setStyleSheet("margin-left:2px;")

        # CPU temperature label (may be None on Windows where temps are unsupported)
        self.cpu_temp_label: Optional[QtWidgets.QLabel] = None
        if not IS_WINDOWS:
            self.cpu_temp_label = QtWidgets.QLabel("CPU Temperature: —")
            self.cpu_temp_label.setStyleSheet("margin-left:2px;")

        # ----- Additional CPU view widgets -----
        # General view: single average usage line
        self.cpu_gen_axis_bottom = TimeAxisItem(history_len, self.PLOT_UPDATE_MS / 1000.0)
        self.cpu_gen_axis_left = PercentAxisItem()
        self.cpu_general_plot = pg.PlotWidget(
            axisItems={"bottom": self.cpu_gen_axis_bottom, "left": self.cpu_gen_axis_left}
        )
        self.cpu_general_plot.showAxis("right", False)
        self._apply_grid(self.cpu_general_plot)
        self.cpu_general_plot.setYRange(0, 100)
        self.cpu_general_plot.setMouseEnabled(x=False, y=False)
        self.cpu_general_plot.setMenuEnabled(False)
        self.cpu_general_plot.setXRange(0, history_len - 1)
        self.cpu_general_plot.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.cpu_general_plot.installEventFilter(self)
        self.cpu_general_history = deque([0.0] * history_len, maxlen=history_len)
        # Independent color for the average usage line (general view)
        self.cpu_general_color = QtGui.QColor(self.cpu_colors[0])
        pen = pg.mkPen(color=self.cpu_general_color, width=self.THREAD_LINE_WIDTH)
        self.cpu_general_curve = self.cpu_general_plot.plot([0] * history_len, pen=pen)
        try:
            self.cpu_general_curve.setClipToView(True)
            self.cpu_general_curve.setDownsampling(auto=True, method="mean")
        except Exception:
            pass

        # Multi window: one plot per CPU core in a scrollable grid
        self.cpu_mini_plots: List[pg.PlotWidget] = []
        self.cpu_mini_curves: List[pg.PlotDataItem] = []
        self.cpu_mini_axes_bottom: List[TimeAxisItem] = []
        self.cpu_mini_labels: List[pg.TextItem] = []  # per-plot usage/freq labels
        self.cpu_mini_label_widgets: List[QtWidgets.QLabel] = []
        self.cpu_mini_containers: List[QtWidgets.QWidget] = []
        self.cpu_label_color = QtGui.QColor(self.CPU_MULTI_LABEL_COLOR)
        self.cpu_multi_container = QtWidgets.QWidget()
        self.cpu_multi_layout = QtWidgets.QGridLayout(self.cpu_multi_container)
        self.cpu_multi_layout.setContentsMargins(0, 0, 0, 0)
        self.cpu_multi_layout.setSpacing(6)
        cols = self.CPU_MULTI_COLS
        for i in range(self.n_cpu):
            axis_b = TimeAxisItem(history_len, self.PLOT_UPDATE_MS / 1000.0)
            axis_l = PercentAxisItem()
            axis_b.setStyle(showValues=False)
            axis_l.setStyle(showValues=False)
            plot = pg.PlotWidget(axisItems={"bottom": axis_b, "left": axis_l})
            plot.showAxis("right", False)
            plot.showAxis("bottom", self.CPU_MULTI_AXES)
            plot.showAxis("left", self.CPU_MULTI_AXES)
            self._apply_grid(plot)
            plot.setYRange(0, 100)
            plot.setMouseEnabled(x=False, y=False)
            plot.setMenuEnabled(False)
            plot.setXRange(0, history_len - 1)
            plot.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
            )
            plot.setMinimumSize(self.CPU_MINI_MIN_W, self.CPU_MINI_MIN_H)
            plot.installEventFilter(self)
            color = self.cpu_mono_color if self.CPU_MULTI_MONO else self.cpu_colors[i]
            pen = pg.mkPen(color=color, width=self.THREAD_LINE_WIDTH)
            curve = plot.plot([0] * history_len, pen=pen)
            try:
                curve.setClipToView(True)
                curve.setDownsampling(auto=True, method="mean")
            except Exception:
                pass
            label = pg.TextItem("", color=self.cpu_label_color, anchor=(0.5, 0))
            label.setPos((history_len - 1) / 2, 100)
            plot.addItem(label)
            widget_label = QtWidgets.QLabel("")
            widget_label.setAlignment(QtCore.Qt.AlignCenter)
            widget_label.setStyleSheet(f"color: {self.cpu_label_color.name()};")
            container = QtWidgets.QWidget()
            vbox = QtWidgets.QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(0)
            vbox.addWidget(widget_label)
            vbox.addWidget(plot)
            widget_label.setVisible(not self.CPU_MULTI_LABEL_INSIDE)
            label.setVisible(self.CPU_MULTI_LABEL_INSIDE)
            self.cpu_mini_plots.append(plot)
            self.cpu_mini_curves.append(curve)
            self.cpu_mini_axes_bottom.append(axis_b)
            self.cpu_mini_labels.append(label)
            self.cpu_mini_label_widgets.append(widget_label)
            self.cpu_mini_containers.append(container)
            self.cpu_multi_layout.addWidget(container, i // cols, i % cols)

        self.cpu_multi_container.setMinimumSize(0, 0)

        self.cpu_multi_scroll = QtWidgets.QScrollArea()
        self.cpu_multi_scroll.setWidget(self.cpu_multi_container)
        self.cpu_multi_scroll.setWidgetResizable(True)
        self.cpu_multi_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.cpu_multi_scroll.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        # Apply optional area fills now that all CPU curves exist
        self._apply_cpu_fill()

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
        self.mem_plot.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.mem_plot.installEventFilter(self)

        self._x_vals = list(range(history_len))
        self._zeros = [0] * history_len
        self.mem_hist = deque([0.0] * history_len, maxlen=history_len)
        self.swap_hist = deque([0.0] * history_len, maxlen=history_len)

        self.mem_base = pg.PlotCurveItem(self._x_vals, self._zeros, pen=None)
        self.mem_curve = pg.PlotCurveItem(pen=pg.mkPen(width=2))
        self.mem_fill = pg.FillBetweenItem(self.mem_curve, self.mem_base, brush=(60, 130, 200, 80))
        self.mem_plot.addItem(self.mem_base)
        self.mem_plot.addItem(self.mem_curve)
        self.mem_plot.addItem(self.mem_fill)

        self.swap_base = pg.PlotCurveItem(self._x_vals, self._zeros, pen=None)
        self.swap_curve = pg.PlotCurveItem(pen=pg.mkPen((200, 120, 60), width=2, style=QtCore.Qt.DashLine))
        self.swap_fill = pg.FillBetweenItem(self.swap_curve, self.swap_base, brush=(200, 120, 60, 60))
        self.mem_plot.addItem(self.swap_base)
        self.mem_plot.addItem(self.swap_curve)
        self.mem_plot.addItem(self.swap_fill)

        self.mem_label = QtWidgets.QLabel("Memory —")

        # ----- Network (left numeric axis) -----
        self.net_axis_bottom = TimeAxisItem(history_len, self.PLOT_UPDATE_MS / 1000.0)
        self.net_plot = pg.PlotWidget(axisItems={'bottom': self.net_axis_bottom, 'left': pg.AxisItem('left')})
        self.net_plot.showAxis('right', False)
        self._apply_grid(self.net_plot)
        self.net_plot.setMouseEnabled(x=False, y=False)
        self.net_plot.setMenuEnabled(False)
        self.net_plot.setXRange(0, history_len - 1)
        self.net_plot.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.net_plot.installEventFilter(self)

        self.rx_hist = deque([0.0] * history_len, maxlen=history_len)
        self.tx_hist = deque([0.0] * history_len, maxlen=history_len)
        self.rx_curve = self.net_plot.plot(self._x_vals, self._zeros, pen=pg.mkPen((100, 180, 255), width=2))
        self.tx_curve = self.net_plot.plot(self._x_vals, self._zeros, pen=pg.mkPen((255, 120, 100), width=2))
        self.net_ema_rx = 0.0
        self.net_ema_tx = 0.0
        self.net_label = QtWidgets.QLabel("<span style='color:#64b4ff'>Receiving —</span>  <span style='color:#ff7864'>Sending —</span>")
        self.net_label.setTextFormat(QtCore.Qt.RichText)

        # Text placeholders updated by the text timer
        self._mem_label_text = "Memory —"
        self._net_label_text = "<span style='color:#64b4ff'>Receiving —</span>  <span style='color:#ff7864'>Sending —</span>"

        # ----- Assemble layout -----
        self.cpu_total_label = QtWidgets.QLabel("Total CPU Usage: —")
        self.cpu_total_label.setStyleSheet("margin-left:2px;")

        self.cpu_section = CollapsibleSection("CPU")
        self.set_cpu_view_mode(self.cpu_view_mode)

        self.mem_section = CollapsibleSection("Memory and Swap")
        self.mem_section.add_widget(self.mem_plot)
        self.mem_section.add_widget(self.mem_label)
        self.mem_section.default_stretch = 1

        self.net_section = CollapsibleSection("Network")
        self.net_section.add_widget(self.net_plot)
        self.net_section.add_widget(self.net_label)
        self.net_section.default_stretch = 1

        layout.addWidget(self.cpu_section, 2)
        layout.addWidget(self.mem_section, 1)
        layout.addWidget(self.net_section, 1)

        # ----- Initial state & timers -----
        self.prev_net = network.io_counters()
        self.prev_t = time.monotonic()

        self.cpu_last_raw = [0.0] * self.n_cpu
        self.cpu_display_ema1 = [0.0] * self.n_cpu  # legend smoothing (double-EMA)
        self.cpu_display_ema2 = [0.0] * self.n_cpu

        # Cache and worker thread for temperature queries so UI timer isn't blocked
        self._temp_cache: Optional[float] = None
        self._temp_thread: Optional[threading.Thread] = None

        cpu.percent(percpu=True)  # warm-up to set baselines

        # Separate timers: plot vs stats (started when visible)
        self.plot_timer = QtCore.QTimer(self)
        self.plot_timer.timeout.connect(self._update_plots)

        self.text_timer = QtCore.QTimer(self)
        self.text_timer.timeout.connect(self._update_text)

        self._apply_freq_visibility()
        if self.SHOW_CPU_TEMP and self.cpu_temp_label is not None:
            self._schedule_temperature()
        self._update_tick_steps()

    def showEvent(self, e: QtGui.QShowEvent):
        self.plot_timer.start(self.PLOT_UPDATE_MS)
        self.text_timer.start(self.TEXT_UPDATE_MS)
        self._update_plots()
        self._update_text()
        super().showEvent(e)

    def hideEvent(self, e: QtGui.QHideEvent):
        # Keep timers running even when the tab is hidden so plots remain up-to-date
        super().hideEvent(e)

    def eventFilter(self, obj, event):
        plots = [self.cpu_plot, self.cpu_general_plot] + self.cpu_mini_plots
        if hasattr(self, "mem_plot"):
            plots.append(self.mem_plot)
        if hasattr(self, "net_plot"):
            plots.append(self.net_plot)
        if event.type() == QtCore.QEvent.Resize and obj in plots:
            self._update_tick_steps(obj)
        return super().eventFilter(obj, event)

    # ---------- helpers ----------
    def _history_len(self) -> int:
        return max(1, int(self.HISTORY_SECONDS * 1000 / self.PLOT_UPDATE_MS))

    def _apply_grid(self, plot: pg.PlotWidget):
        plot.showGrid(x=self.SHOW_GRID_X, y=self.SHOW_GRID_Y, alpha=0.2)

    def _apply_cpu_fill(self):
        """Enable or disable translucent area under CPU curves for all view modes."""
        for i, curve in enumerate(self.cpu_curves):
            if self.FILL_CPU:
                c = QtGui.QColor(self.cpu_colors[i])
                c.setAlpha(self.CPU_FILL_ALPHA)
                curve.setBrush(c)
                curve.setFillLevel(0)
            else:
                curve.setBrush(None)
                curve.setFillLevel(None)

        # Average usage line (general view)
        # Always update the pen so color changes affect the curve itself
        pen = pg.mkPen(color=self.cpu_general_color, width=self.THREAD_LINE_WIDTH)
        self.cpu_general_curve.setPen(pen)
        if self.FILL_CPU:
            # Use the same color for the translucent fill under the curve
            c0 = QtGui.QColor(self.cpu_general_color)
            c0.setAlpha(self.CPU_FILL_ALPHA)
            self.cpu_general_curve.setBrush(c0)
            self.cpu_general_curve.setFillLevel(0)
        else:
            self.cpu_general_curve.setBrush(None)
            self.cpu_general_curve.setFillLevel(None)

        # Mini plots in multi-window view
        for i, curve in enumerate(self.cpu_mini_curves):
            if self.FILL_CPU:
                color = self.cpu_mono_color if self.CPU_MULTI_MONO else self.cpu_colors[i]
                c = QtGui.QColor(color)
                c.setAlpha(self.CPU_FILL_ALPHA)
                curve.setBrush(c)
                curve.setFillLevel(0)
            else:
                curve.setBrush(None)
                curve.setFillLevel(None)

    def _apply_multi_colors(self):
        """Update mini-plot pens according to mono-color settings."""
        for i, curve in enumerate(self.cpu_mini_curves):
            color = self.cpu_mono_color if self.CPU_MULTI_MONO else self.cpu_colors[i]
            pen = pg.mkPen(color=color, width=self.THREAD_LINE_WIDTH)
            curve.setPen(pen)
        if self.CPU_MULTI_LABEL_MATCH:
            self._apply_label_color()

    def _apply_label_color(self):
        if self.CPU_MULTI_LABEL_MATCH:
            for curve, lbl, w in zip(
                self.cpu_mini_curves, self.cpu_mini_labels, self.cpu_mini_label_widgets
            ):
                pen = curve.opts.get("pen")
                color = pen.color() if isinstance(pen, QtGui.QPen) else pen
                lbl.setColor(color)
                w.setStyleSheet(f"color: {color.name()};")
        else:
            color = self.cpu_label_color
            for lbl in self.cpu_mini_labels:
                lbl.setColor(color)
            for w in self.cpu_mini_label_widgets:
                w.setStyleSheet(f"color: {color.name()};")

    def _apply_label_mode(self):
        inside = self.CPU_MULTI_LABEL_INSIDE
        for txt, w in zip(self.cpu_mini_labels, self.cpu_mini_label_widgets):
            txt.setVisible(inside)
            w.setVisible(not inside)
        if inside:
            history_len = self._history_len()
            for lbl in self.cpu_mini_labels:
                lbl.setPos((history_len - 1) / 2, 100)

    def _regrid_mini_plots(self):
        """Reposition mini CPU plots based on current column count."""
        cols = max(1, self.CPU_MULTI_COLS)
        for i, container in enumerate(self.cpu_mini_containers):
            self.cpu_multi_layout.addWidget(container, i // cols, i % cols)

    def _update_tick_steps(self, plot: Optional[pg.PlotWidget] = None):
        """
        Choose tick steps that look good and stay visible even on small plots.
        - CPU & Memory: force Y range to 0..100 and choose a step that divides 100
          so we always hit nice ticks like 0,20,40,60,80,100.
        - X axis: pick from a 'nice' time step family so labels don't disappear.
        - Network: adaptive 1-2-5 step on current range.
        """
        import math

        plots = [plot] if plot else [self.cpu_plot, self.mem_plot, self.net_plot]

        # How dense can we label before things collide (rough heuristics, px/label)
        PX_PER_LABEL_X = 90
        PX_PER_LABEL_Y = 30

        # Always keep at least this many labels per axis visible
        MIN_LABELS_X = 4
        MIN_LABELS_Y = 3

        # Time axis helpers
        interval = self.PLOT_UPDATE_MS / 1000.0  # seconds per sample
        hist_len = self._history_len()
        total_secs = (hist_len - 1) * interval
        nice_time_steps = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600]

        # Nice step rounding (1-2-5 progression)
        def nice125(x: float) -> float:
            if x <= 0:
                return 1.0
            exp = math.floor(math.log10(x))
            frac = x / (10 ** exp)
            if frac <= 1.0:
                nice = 1.0
            elif frac <= 2.0:
                nice = 2.0
            elif frac <= 5.0:
                nice = 5.0
            else:
                nice = 10.0
            return nice * (10 ** exp)

        for p in plots:
            width = max(1, int(p.size().width()))
            height = max(1, int(p.size().height()))

            # ---------------- X axis (time) ----------------
            # Target how many labels fit across the width.
            target_lbls_x = max(MIN_LABELS_X, min(self.GRID_DIVS + 1, width // PX_PER_LABEL_X))
            # Step in *seconds* that would produce ~target_lbls_x labels:
            raw_step_sec = max(interval, total_secs / max(1, (target_lbls_x - 1)))
            # Snap to a nice value from the curated list (closest)
            step_sec = min(nice_time_steps, key=lambda s: abs(s - raw_step_sec))
            # Convert seconds -> samples (our X domain is 0..hist_len-1)
            step_x = max(1, int(round(step_sec / interval)))
            p.getAxis('bottom').setTickSpacing(step_x, step_x)

            # ---------------- Y axis (values) ----------------
            cpu_plots = [self.cpu_plot, self.mem_plot, self.cpu_general_plot] + self.cpu_mini_plots
            if p in cpu_plots:
                # Lock Y to 0..100 so CPU/Mem always show percentages consistently.
                p.setYRange(0, 100)

                # Candidate steps that *divide 100* → ensure 0 and 100 land on ticks.
                cpu_mem_steps = [1, 2, 4, 5, 10, 20, 25, 50]

                # How many labels can we fit vertically?
                target_lbls_y = max(MIN_LABELS_Y, min(self.GRID_DIVS + 1, height // PX_PER_LABEL_Y))

                # The "ideal" step for that label count on a 0..100 range:
                raw_step_y = 100.0 / max(1, (target_lbls_y - 1))

                # Pick the candidate that's closest to the ideal (but still divides 100)
                step_y = min(cpu_mem_steps, key=lambda s: abs(s - raw_step_y))

                # Extra safety: if chosen step would yield fewer than MIN_LABELS_Y,
                # clamp it down so we still meet the minimum label count.
                max_step_for_min = 100.0 / max(1, (MIN_LABELS_Y - 1))  # e.g., for 4 labels → 33.33
                step_y = min(step_y, max_step_for_min)

                p.getAxis('left').setTickSpacing(step_y, step_y)

            else:
                # Network (dynamic): choose a 1-2-5 step on the current view range.
                (y_min, y_max) = p.viewRange()[1]
                y_range = max(1.0, float(y_max - y_min))
                target_lbls_y = max(MIN_LABELS_Y, min(self.GRID_DIVS + 1, height // PX_PER_LABEL_Y))
                raw_step_y = y_range / max(1, (target_lbls_y - 1))
                step_y = nice125(raw_step_y)
                p.getAxis('left').setTickSpacing(step_y, step_y)


    def _on_color_change(self, cpu_index: int, color: QtGui.QColor):
        """Legend callback: update curve color across all views."""
        if 0 <= cpu_index < len(self.cpu_curves):
            old_color = self.cpu_colors[cpu_index]
            self.cpu_colors[cpu_index] = color
            pen = pg.mkPen(color=color, width=self.THREAD_LINE_WIDTH)
            self.cpu_curves[cpu_index].setPen(pen)
            if cpu_index == 0 and self.cpu_general_color == old_color:
                self.cpu_general_color = QtGui.QColor(color)
                self.cpu_general_curve.setPen(
                    pg.mkPen(color=self.cpu_general_color, width=self.THREAD_LINE_WIDTH)
                )
            if not self.CPU_MULTI_MONO and cpu_index < len(self.cpu_mini_curves):
                self.cpu_mini_curves[cpu_index].setPen(pen)
            else:
                self._apply_multi_colors()
            if self.FILL_CPU:
                self._apply_cpu_fill()
            if self.CPU_MULTI_LABEL_MATCH:
                self._apply_label_color()

    def set_cpu_view_mode(self, mode: str):
        if mode not in self.CPU_VIEW_MODES:
            mode = self.CPU_VIEW_MODE
        self.cpu_view_mode = mode
        lay = self.cpu_section.content_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        if mode == "Multi thread":
            self.cpu_section.add_widget(self.cpu_plot)
            self.cpu_section.add_widget(self.cpu_legend_scroll)
            self.cpu_section.add_widget(self.cpu_freq_avg_label)
            if self.SHOW_CPU_TEMP and self.cpu_temp_label is not None:
                self.cpu_section.add_widget(self.cpu_temp_label)
            self.cpu_section.add_widget(self.cpu_total_label)
            lay.setStretch(0, 3)
            lay.setStretch(1, 2)
            self._update_tick_steps(self.cpu_plot)
        elif mode == "General view":
            self.cpu_section.add_widget(self.cpu_general_plot)
            self.cpu_section.add_widget(self.cpu_freq_avg_label)
            if self.SHOW_CPU_TEMP and self.cpu_temp_label is not None:
                self.cpu_section.add_widget(self.cpu_temp_label)
            self.cpu_section.add_widget(self.cpu_total_label)
            lay.setStretch(0, 3)
            self._update_tick_steps(self.cpu_general_plot)
        else:  # Multi window
            self.cpu_section.add_widget(self.cpu_multi_scroll)
            self.cpu_section.add_widget(self.cpu_freq_avg_label)
            if self.SHOW_CPU_TEMP and self.cpu_temp_label is not None:
                self.cpu_section.add_widget(self.cpu_temp_label)
            self.cpu_section.add_widget(self.cpu_total_label)
            lay.setStretch(0, 3)
            for p in self.cpu_mini_plots:
                self._update_tick_steps(p)
                p.showAxis("bottom", self.CPU_MULTI_AXES)
                p.showAxis("left", self.CPU_MULTI_AXES)
            self._apply_multi_colors()
            self._apply_label_color()
            self._apply_label_mode()
        self.cpu_section.default_stretch = 2

    def _apply_freq_visibility(self):
        self.cpu_freq_avg_label.setVisible(self.SHOW_CPU_FREQ)

    def _temperature_worker(self):
        """Background worker to fetch CPU temperature without stalling UI."""
        self._temp_cache = cpu.temperature()
        self._temp_thread = None

    def _schedule_temperature(self):
        """Spawn a worker thread to refresh CPU temperature."""
        if self._temp_thread is None or not self._temp_thread.is_alive():
            self._temp_thread = threading.Thread(
                target=self._temperature_worker, daemon=True
            )
            self._temp_thread.start()

    # ---------- public API (Preferences) ----------
    def apply_settings(
        self,
        history_seconds: int,
        plot_update_ms: int,
        text_update_ms: int,
        ema_alpha: float,
        mem_ema_alpha: float,
        show_cpu_freq: bool,
        show_cpu_temp: bool,
        thread_line_width: float,
        show_grid_x: bool,
        show_grid_y: bool,
        grid_divs: int,
        smooth_graphs: bool,
        extra_smoothing: bool,
        antialias: bool,
        cpu_view_mode: str,
        fill_cpu: bool,
        smooth_net_graph: bool,
        net_ema_alpha: float,
        mini_w: int,
        mini_h: int,
        multi_cols: int,
        multi_axes: bool,
        multi_mono: bool,
        mono_color: str,
        general_color: str,
        label_pos: str,
        label_match: bool,
        label_color: str,
    ):
        """Rebuild buffers/axes and timers according to Preferences."""
        self.HISTORY_SECONDS   = int(max(5, history_seconds))
        self.PLOT_UPDATE_MS    = int(max(50, plot_update_ms))
        self.TEXT_UPDATE_MS    = int(max(50, text_update_ms))
        self.EMA_ALPHA         = float(min(0.999, max(0.0, ema_alpha)))
        self.MEM_EMA_ALPHA     = float(min(0.999, max(0.0, mem_ema_alpha)))
        self.SHOW_CPU_FREQ     = bool(show_cpu_freq) if (IS_LINUX or IS_WINDOWS) else False
        self.SHOW_CPU_TEMP     = bool(show_cpu_temp) if not IS_WINDOWS else False
        self.THREAD_LINE_WIDTH = float(max(0.5, thread_line_width))
        self.SHOW_GRID_X       = bool(show_grid_x)
        self.SHOW_GRID_Y       = bool(show_grid_y)
        self.GRID_DIVS         = int(max(1, grid_divs))
        self.SMOOTH_GRAPHS     = bool(smooth_graphs)
        self.EXTRA_SMOOTHING   = bool(extra_smoothing)
        self.ANTIALIAS         = bool(antialias)
        pg.setConfigOptions(antialias=self.ANTIALIAS)
        self.FILL_CPU          = bool(fill_cpu)
        self.SMOOTH_NET_GRAPH  = bool(smooth_net_graph)
        self.NET_EMA_ALPHA     = float(min(0.999, max(0.0, net_ema_alpha)))
        self.CPU_MINI_MIN_W    = int(max(20, mini_w))
        self.CPU_MINI_MIN_H    = int(max(20, mini_h))
        self.CPU_MULTI_COLS    = int(max(1, multi_cols))
        self.CPU_MULTI_AXES    = bool(multi_axes)
        self.CPU_MULTI_MONO    = bool(multi_mono)
        if mono_color:
            self.cpu_mono_color = QtGui.QColor(mono_color)
        if general_color:
            self.cpu_general_color = QtGui.QColor(general_color)
        else:
            self.cpu_general_color = QtGui.QColor(self.cpu_colors[0])
        self.CPU_MULTI_LABEL_INSIDE = label_pos == "Inside"
        self.CPU_MULTI_LABEL_MATCH = bool(label_match)
        if label_color and not self.CPU_MULTI_LABEL_MATCH:
            self.cpu_label_color = QtGui.QColor(label_color)
        self.set_cpu_view_mode(cpu_view_mode)

        # Update timers only if currently active
        was_plot = self.plot_timer.isActive()
        was_text = self.text_timer.isActive()
        if was_plot:
            self.plot_timer.stop()
        if was_text:
            self.text_timer.stop()
        if was_plot:
            self.plot_timer.start(self.PLOT_UPDATE_MS)
        if was_text:
            self.text_timer.start(self.TEXT_UPDATE_MS)

        # Axes / ranges / grids
        history_len = self._history_len()
        for axis in (self.cpu_axis_bottom, self.mem_axis_bottom, self.net_axis_bottom, self.cpu_gen_axis_bottom, *self.cpu_mini_axes_bottom):
            axis.update_params(history_len, self.PLOT_UPDATE_MS / 1000.0)
        for plot in [self.cpu_plot, self.mem_plot, self.net_plot, self.cpu_general_plot] + self.cpu_mini_plots:
            plot.setXRange(0, history_len - 1)
            self._apply_grid(plot)
            if plot in self.cpu_mini_plots:
                plot.setMinimumSize(self.CPU_MINI_MIN_W, self.CPU_MINI_MIN_H)
                plot.showAxis("bottom", self.CPU_MULTI_AXES)
                plot.showAxis("left", self.CPU_MULTI_AXES)
        self._update_tick_steps()
        self._update_tick_steps(self.cpu_general_plot)
        for p in self.cpu_mini_plots:
            self._update_tick_steps(p)
        self._regrid_mini_plots()
        self.cpu_multi_container.setMinimumSize(0, 0)

        # Rebuild buffers for graphs
        self.cpu_histories = [deque([0.0] * history_len, maxlen=history_len) for _ in range(self.n_cpu)]
        for i, curve in enumerate(self.cpu_curves):
            pen = pg.mkPen(color=self.cpu_colors[i], width=self.THREAD_LINE_WIDTH)
            curve.setPen(pen)
            curve.setData([0.0] * history_len)
        for curve in self.cpu_mini_curves:
            curve.setData([0.0] * history_len)
        self._apply_multi_colors()
        self._apply_label_color()
        self._apply_label_mode()
        self._apply_cpu_fill()
        self.cpu_general_history = deque([0.0] * history_len, maxlen=history_len)
        self.cpu_general_curve.setData([0.0] * history_len)
        self.cpu_plot_ema1 = [0.0] * self.n_cpu
        self.cpu_plot_ema2 = [0.0] * self.n_cpu
        self.cpu_display_ema1 = [0.0] * self.n_cpu
        self.cpu_display_ema2 = [0.0] * self.n_cpu

        # Reposition mini labels for the new history length
        if self.CPU_MULTI_LABEL_INSIDE:
            for lbl in self.cpu_mini_labels:
                lbl.setPos((history_len - 1) / 2, 100)

        self._x_vals = list(range(history_len))
        self._zeros = [0] * history_len
        self.mem_hist = deque([0.0] * history_len, maxlen=history_len)
        self.swap_hist = deque([0.0] * history_len, maxlen=history_len)
        self.mem_base.setData(self._x_vals, self._zeros)
        self.swap_base.setData(self._x_vals, self._zeros)
        self.rx_hist = deque([0.0] * history_len, maxlen=history_len)
        self.tx_hist = deque([0.0] * history_len, maxlen=history_len)
        self.rx_curve.setData(self._x_vals, self._zeros)
        self.tx_curve.setData(self._x_vals, self._zeros)
        self.net_ema_rx = 0.0
        self.net_ema_tx = 0.0

        # Frequencies visibility
        self._apply_freq_visibility()
        if self.SHOW_CPU_TEMP and self.cpu_temp_label is not None:
            self._schedule_temperature()
        
    def apply_theme(self, palette: QtGui.QPalette):
        """Update plot colors to match the given palette."""
        bg = palette.color(QtGui.QPalette.Window)
        fg = palette.color(QtGui.QPalette.WindowText)
        all_plots = [
            self.cpu_plot,
            self.mem_plot,
            self.net_plot,
            self.cpu_general_plot,
            *self.cpu_mini_plots,
        ]
        for plot in all_plots:
            plot.setBackground(bg)
            for name in ("left", "bottom"):
                ax = plot.getPlotItem().getAxis(name)
                ax.setPen(fg)
                ax.setTextPen(fg)

        # Labels using style sheets need manual palette updates
        fg_hex = fg.name()
        self.cpu_total_label.setStyleSheet(f"margin-left:2px; color: {fg_hex};")
        self.cpu_freq_avg_label.setStyleSheet(f"margin-left:2px; color: {fg_hex};")
        if self.cpu_temp_label is not None:
            self.cpu_temp_label.setStyleSheet(f"margin-left:2px; color: {fg_hex};")

    # ---------- TEXT TIMER (legend & labels) ----------
    def _update_text(self):
        # Per-CPU usage (store raw, then double-EMA for stable legend)
        per = cpu.percent(percpu=True)
        n = min(len(per), self.n_cpu)
        usages = []
        for i in range(n):
            raw = max(0.0, float(per[i]))
            self.cpu_last_raw[i] = raw
            if self.SMOOTH_GRAPHS:
                a_cpu = self.EMA_ALPHA
                self.cpu_display_ema1[i] = a_cpu * self.cpu_display_ema1[i] + (1.0 - a_cpu) * raw
                self.cpu_display_ema2[i] = a_cpu * self.cpu_display_ema2[i] + (1.0 - a_cpu) * self.cpu_display_ema1[i]
                smoothed = (
                    2 * self.cpu_display_ema1[i] - self.cpu_display_ema2[i]
                    if self.EXTRA_SMOOTHING
                    else self.cpu_display_ema1[i]
                )
                usages.append(max(0.0, smoothed))
            else:
                self.cpu_display_ema1[i] = raw
                self.cpu_display_ema2[i] = raw
                usages.append(raw)

        # Optional per-CPU frequency + average
        per_freq_mhz: Optional[List[float]] = None
        avg_freq = None
        if self.SHOW_CPU_FREQ:
            per_freq_mhz, avg_freq = cpu.freqs(self.n_cpu)

        if self.cpu_view_mode == "Multi thread":
            self.cpu_legend_grid.set_values(usages, per_freq_mhz)
        elif self.cpu_view_mode == "Multi window":
            for i, (txt, w) in enumerate(
                zip(self.cpu_mini_labels, self.cpu_mini_label_widgets)
            ):
                if i >= len(usages):
                    continue
                freq_txt = ""
                if self.SHOW_CPU_FREQ and per_freq_mhz and i < len(per_freq_mhz):
                    freq_txt = f" {human_freq(per_freq_mhz[i])}"
                text = f"CPU{i+1}: {usages[i]:.0f}%{freq_txt}"
                if self.CPU_MULTI_LABEL_INSIDE:
                    txt.setText(text)
                else:
                    w.setText(text)
        self.cpu_freq_avg_label.setVisible(self.SHOW_CPU_FREQ)
        if self.SHOW_CPU_FREQ:
            self.cpu_freq_avg_label.setText(
                f"Average frequency: {human_freq(avg_freq)}" if avg_freq else "Average frequency: —"
            )

        if self.SHOW_CPU_TEMP and self.cpu_temp_label is not None:
            # Non-blocking temperature update using cached value
            self._schedule_temperature()
            temp_c = self._temp_cache
            if temp_c is not None:
                self.cpu_temp_label.setText(f"CPU Temperature: {temp_c:.1f}°C")
            else:
                self.cpu_temp_label.setText("CPU Temperature: —")

        total_usage = sum(usages) / len(usages) if usages else 0.0
        self.cpu_total_label.setText(f"Total CPU Usage: {total_usage:.1f}%")

        # Update cached labels for memory and network
        self.mem_label.setText(self._mem_label_text)
        self.net_label.setText(self._net_label_text)
    # ---------- PLOT TIMER (graphs only) ----------
    def _update_plots(self):
        # CPU: optional smoothing toward the latest raw usage values
        a_cpu = self.EMA_ALPHA
        avg_vals: List[float] = []
        for i in range(self.n_cpu):
            if self.SMOOTH_GRAPHS:
                self.cpu_plot_ema1[i] = a_cpu * self.cpu_plot_ema1[i] + (1.0 - a_cpu) * self.cpu_last_raw[i]
                if self.EXTRA_SMOOTHING:
                    self.cpu_plot_ema2[i] = a_cpu * self.cpu_plot_ema2[i] + (1.0 - a_cpu) * self.cpu_plot_ema1[i]
                    use_val = 2 * self.cpu_plot_ema1[i] - self.cpu_plot_ema2[i]
                else:
                    use_val = self.cpu_plot_ema1[i]
            else:
                self.cpu_plot_ema1[i] = self.cpu_last_raw[i]
                self.cpu_plot_ema2[i] = self.cpu_last_raw[i]
                use_val = self.cpu_last_raw[i]
            use_val = max(0.0, use_val)
            self.cpu_histories[i].append(use_val)
            avg_vals.append(use_val)
            if self.cpu_view_mode == "Multi thread":
                self.cpu_curves[i].setData(list(self.cpu_histories[i]))
            elif self.cpu_view_mode == "Multi window":
                self.cpu_mini_curves[i].setData(list(self.cpu_histories[i]))

        if self.cpu_view_mode == "General view":
            avg = sum(avg_vals) / len(avg_vals) if avg_vals else 0.0
            self.cpu_general_history.append(avg)
            self.cpu_general_curve.setData(list(self.cpu_general_history))

        # Memory / Swap (EMA)
        vm, sm = memory.stats()
        mem_val = vm.percent
        swap_val = sm.percent if sm and sm.total > 0 else 0.0
        if self.SMOOTH_GRAPHS:
            mem_ema = self.MEM_EMA_ALPHA * (self.mem_hist[-1] if self.mem_hist else 0.0) + (1.0 - self.MEM_EMA_ALPHA) * mem_val
            swap_ema = self.MEM_EMA_ALPHA * (self.swap_hist[-1] if self.swap_hist else 0.0) + (1.0 - self.MEM_EMA_ALPHA) * swap_val
        else:
            mem_ema = mem_val
            swap_ema = swap_val

        self.mem_hist.append(mem_ema)
        self.swap_hist.append(swap_ema)
        self.mem_curve.setData(self._x_vals, list(self.mem_hist))
        self.mem_base.setData(self._x_vals, self._zeros)
        self.swap_curve.setData(self._x_vals, list(self.swap_hist))
        self.swap_base.setData(self._x_vals, self._zeros)

        cache_txt = f"Cache {human_bytes(getattr(vm, 'cached', 0))}" if getattr(vm, 'cached', 0) else "Cache —"
        swap_txt = (
            "Swap not available"
            if not sm or sm.total == 0
            else f"Swap {swap_ema:.1f}% of {human_bytes(sm.total)}"
        )
        self._mem_label_text = (
            f"Memory {human_bytes(vm.used)} ({mem_ema:.1f}%) of {human_bytes(vm.total)} — {cache_txt}   |   {swap_txt}"
        )

        # Network rates
        rx_kib, tx_kib, self.prev_net, self.prev_t = network.rates(self.prev_net, self.prev_t)
        cur = self.prev_net

        if self.SMOOTH_NET_GRAPH:
            na = self.NET_EMA_ALPHA
            self.net_ema_rx = na * self.net_ema_rx + (1.0 - na) * rx_kib
            self.net_ema_tx = na * self.net_ema_tx + (1.0 - na) * tx_kib
            rx_use = self.net_ema_rx
            tx_use = self.net_ema_tx
        else:
            self.net_ema_rx = rx_kib
            self.net_ema_tx = tx_kib
            rx_use = rx_kib
            tx_use = tx_kib

        self.rx_hist.append(rx_use)
        self.tx_hist.append(tx_use)
        self.rx_curve.setData(self._x_vals, list(self.rx_hist))
        self.tx_curve.setData(self._x_vals, list(self.tx_hist))

        max_y = max(1.0, max(max(self.rx_hist), max(self.tx_hist)))
        self.net_plot.setYRange(0, max_y * 1.2)
        self._update_tick_steps(self.net_plot)
        self._net_label_text = (
            f"<span style='color:#64b4ff'>Receiving {rx_use:,.1f} KiB/s</span> — Total {human_bytes(cur.bytes_recv)}     "
            f"<span style='color:#ff7864'>Sending {tx_use:,.1f} KiB/s</span> — Total {human_bytes(cur.bytes_sent)}"
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
    UPDATE_MS = 3000
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

        # --- Controls above the process table ---
        controls = QtWidgets.QHBoxLayout()

        # Text box used to filter processes by name, user or PID
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by name, user, or PID...")
        self.filter_edit.textChanged.connect(self.apply_filter)
        controls.addWidget(self.filter_edit)

        # Button allowing the user to clear any current selection so that the
        # table no longer follows a particular process during refresh.
        self.clear_btn = QtWidgets.QPushButton("Clear Selection")
        self.clear_btn.setToolTip("Deselect all processes")
        self.clear_btn.clicked.connect(self.table_clear_selection)
        controls.addWidget(self.clear_btn)

        # Button to terminate the selected processes.  A confirmation dialog is
        # presented to prevent accidental termination.
        self.kill_btn = QtWidgets.QPushButton("Kill Selected")
        self.kill_btn.setToolTip("Kill highlighted process(es)")
        self.kill_btn.clicked.connect(self.kill_selected)
        controls.addWidget(self.kill_btn)

        layout.addLayout(controls)

        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        # Allow selection of multiple processes
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Interactive)

        widths = [220, 110, 80, 80, 120, 140, 140, 120, 120, 600]
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)

        layout.addWidget(self.table)
        # Allow clearing selection with the Escape key
        self.table.installEventFilter(self)

        # Caches used during refresh
        self.prev_io: Dict[int, Tuple[int, int]] = {}
        self.prev_time = time.monotonic()
        self.row_for_pid: Dict[int, int] = {}
        self.update_ms = self.UPDATE_MS
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self._primed = False

    def _item(self, text: str, sort_value=None, tip: str = "") -> QtWidgets.QTableWidgetItem:
        it = QtWidgets.QTableWidgetItem(text)
        it.setToolTip(tip if tip else text)
        it.setData(QtCore.Qt.UserRole, text if sort_value is None else sort_value)
        return it

    def _set_row(self, row: int, cols):
        for c, (txt, sortv, tip) in enumerate(cols):
            it = self.table.item(row, c)
            if it is None:
                it = self._item(txt, sortv, tip)
                self.table.setItem(row, c, it)
            else:
                it.setText(txt)
                it.setToolTip(tip if tip else txt)
                it.setData(QtCore.Qt.UserRole, txt if sortv is None else sortv)

    def table_clear_selection(self):
        """Deselect all rows in the process table."""
        self.table.clearSelection()

    def kill_selected(self):
        """Kill all currently selected processes after confirmation."""
        pids = self.selected_pids()
        if not pids:
            return
        msg = ("Kill the selected process?" if len(pids) == 1
               else f"Kill {len(pids)} selected processes?")
        if QtWidgets.QMessageBox.question(
            self,
            "Confirm Kill",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        ) != QtWidgets.QMessageBox.Yes:
            return
        for pid in pids:
            try:
                processes.kill(pid)
            except (processes.NoSuchProcess, processes.AccessDenied, processes.ZombieProcess) as e:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Kill failed",
                    f"PID {pid}: {e}",
                )
        # Immediately refresh so the table reflects the changes
        self.refresh()

    def selected_pids(self) -> List[int]:
        """Return list of PIDs for currently selected processes."""
        pids: List[int] = []
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), 3)
            if item:
                try:
                    pids.append(int(item.text()))
                except ValueError:
                    pass
        return pids

    def restore_selection(self, pids: List[int]):
        """Restore selection for *pids* and ensure the first one is visible."""
        if not pids:
            return
        self.table.clearSelection()
        first_row: Optional[int] = None
        for pid in pids:
            row = self.row_for_pid.get(pid)
            if row is not None:
                self.table.selectRow(row)
                if first_row is None:
                    first_row = row
        if first_row is not None:
            self.table.scrollToItem(
                self.table.item(first_row, 0),
                QtWidgets.QAbstractItemView.PositionAtCenter,
            )

    def apply_filter(self):
        """Hide rows not matching the filter text."""
        text = self.filter_edit.text().strip().lower()
        for row in range(self.table.rowCount()):
            if text:
                name = self.table.item(row, 0).text().lower()
                user = self.table.item(row, 1).text().lower()
                pid = self.table.item(row, 3).text().lower()
                match = text in name or text in user or text in pid
            else:
                match = True
            self.table.setRowHidden(row, not match)

    def refresh(self):
        now = time.monotonic()
        dt = max(1e-6, now - self.prev_time)
        seen = set()

        # Remember which processes were selected before refresh
        selected = self.selected_pids()

        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)

        try:
            for proc in processes.iter_processes([
                'pid', 'name', 'username', 'cpu_percent',
                'memory_info', 'io_counters', 'cmdline'
            ]):
                info = proc.info
                pid = info['pid']
                seen.add(pid)

                name = info.get('name') or ""
                user = info.get('username') or ""

                cpu = max(0.0, float(info.get('cpu_percent') or 0.0))

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
            # Apply filter and restore previous selection
            self.apply_filter()
            self.restore_selection(selected)

        finally:
            self.prev_time = now
            self.table.setUpdatesEnabled(True)
            self.table.setSortingEnabled(was_sorting)

    def eventFilter(self, obj, event):
        """Handle custom shortcuts for the processes table."""
        if obj is self.table and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Escape:
                # ESC clears the current selection so the view stops
                # auto-centering on a process during refreshes.
                self.table_clear_selection()
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, e: QtGui.QShowEvent):
        if not self._primed:
            processes.prime_cpu_percent()
            self._primed = True
        self.timer.start(self.update_ms)
        super().showEvent(e)

    def hideEvent(self, e: QtGui.QHideEvent):
        self.timer.stop()
        super().hideEvent(e)

    def set_update_ms(self, ms: int):
        self.update_ms = max(50, int(ms))
        if self.timer.isActive():
            self.timer.start(self.update_ms)


# ------------------------------- File Systems tab -------------------------------

class FileSystemsTab(QtWidgets.QWidget):
    """Display mounted partitions and per-disk I/O totals.

    The table is periodically refreshed while the tab is visible.  When the
    user switches to another tab the refresh timer is paused so that gathering
    disk statistics does not waste resources in the background.  A configurable
    refresh interval mirrors the behaviour of the Processes tab.
    """

    # Default refresh cadence (milliseconds)
    UPDATE_MS = 3000

    def __init__(self, parent=None):
        super().__init__(parent)
        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(12)

        # --- Mounted file systems ---
        self.mounts_label = QtWidgets.QLabel("Mounted File Systems")
        self.mounts_label.setStyleSheet("font-weight:bold;")
        self.mounts = QtWidgets.QTableWidget(0, 7)
        self.mounts.setHorizontalHeaderLabels(
            ["Device", "Mount", "Type", "Total", "Used", "Free", "%"]
        )
        self.mounts.setSortingEnabled(True)
        self.mounts.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.mounts.verticalHeader().setVisible(False)
        self.mounts.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        # Allow the user to resize columns manually (previous behaviour)
        header = self.mounts.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.setStretchLastSection(True)

        # --- Disk I/O table ---
        self.io_label = QtWidgets.QLabel("Disk I/O")
        self.io_label.setStyleSheet("font-weight:bold;")
        self.disks = QtWidgets.QTableWidget(0, 8)
        self.disks.setHorizontalHeaderLabels(
            [
                "Disk",
                "Reads",
                "Writes",
                "Read bytes",
                "Write bytes",
                "Read time ms",
                "Write time ms",
                "Busy ms",
            ]
        )
        self.disks.setSortingEnabled(True)
        self.disks.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.disks.verticalHeader().setVisible(False)
        self.disks.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        header = self.disks.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.setStretchLastSection(True)

        main.addWidget(self.mounts_label)
        main.addWidget(self.mounts)
        main.addSpacing(10)
        main.addWidget(self.io_label)
        main.addWidget(self.disks)

        # Timer used to refresh the tables when the tab is active
        self.update_ms = self.UPDATE_MS
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)

        # Populate once so the user sees something immediately
        self.refresh()
        # Auto-fit columns initially but keep user sizes afterwards
        self.mounts.resizeColumnsToContents()
        self.disks.resizeColumnsToContents()

    def refresh(self):
        # Preserve current sort and scroll position so that refreshing does not
        # disturb the user's view.  Sorting is temporarily disabled while the
        # tables are rebuilt to prevent rows from jumping around or cell
        # widgets (progress bars) from being dropped.

        # ----- Mounted partitions -----
        m_header = self.mounts.horizontalHeader()
        m_sort_col = m_header.sortIndicatorSection()
        m_sort_order = m_header.sortIndicatorOrder()
        m_scroll = self.mounts.verticalScrollBar().value()
        self.mounts.setSortingEnabled(False)
        self.mounts.setRowCount(0)
        parts = disks.partitions()
        for dev, mnt, fstype, usage in parts:
            if usage is None:
                continue
            row = self.mounts.rowCount()
            self.mounts.insertRow(row)
            self.mounts.setItem(row, 0, QtWidgets.QTableWidgetItem(dev))
            self.mounts.setItem(row, 1, QtWidgets.QTableWidgetItem(mnt))
            self.mounts.setItem(row, 2, QtWidgets.QTableWidgetItem(fstype))
            self.mounts.setItem(
                row, 3, QtWidgets.QTableWidgetItem(human_bytes(usage.total))
            )
            self.mounts.setItem(
                row, 4, QtWidgets.QTableWidgetItem(human_bytes(usage.used))
            )
            self.mounts.setItem(
                row, 5, QtWidgets.QTableWidgetItem(human_bytes(usage.free))
            )

            # Progress bar in the percentage column for an at-a-glance view of
            # disk usage.  We still keep a hidden QTableWidgetItem so that
            # sorting remains numeric rather than lexical.
            percent_item = QtWidgets.QTableWidgetItem(f"{usage.percent:.1f}")
            percent_item.setData(QtCore.Qt.UserRole, usage.percent)
            self.mounts.setItem(row, 6, percent_item)
            bar = QtWidgets.QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(round(usage.percent)))
            bar.setFormat(f"{usage.percent:.1f}%")
            bar.setAlignment(QtCore.Qt.AlignCenter)
            self.mounts.setCellWidget(row, 6, bar)

        self.mounts.setSortingEnabled(True)
        self.mounts.sortItems(m_sort_col, m_sort_order)
        self.mounts.verticalScrollBar().setValue(m_scroll)

        # ----- Per-disk I/O totals -----
        d_header = self.disks.horizontalHeader()
        d_sort_col = d_header.sortIndicatorSection()
        d_sort_order = d_header.sortIndicatorOrder()
        d_scroll = self.disks.verticalScrollBar().value()
        self.disks.setSortingEnabled(False)
        self.disks.setRowCount(0)
        io_per = disks.io_counters()
        for disk, io in io_per.items():
            row = self.disks.rowCount()
            self.disks.insertRow(row)
            self.disks.setItem(row, 0, QtWidgets.QTableWidgetItem(disk))
            self.disks.setItem(row, 1, QtWidgets.QTableWidgetItem(str(getattr(io, 'read_count', 0))))
            self.disks.setItem(row, 2, QtWidgets.QTableWidgetItem(str(getattr(io, 'write_count', 0))))
            self.disks.setItem(row, 3, QtWidgets.QTableWidgetItem(human_bytes(getattr(io, 'read_bytes', 0))))
            self.disks.setItem(row, 4, QtWidgets.QTableWidgetItem(human_bytes(getattr(io, 'write_bytes', 0))))
            self.disks.setItem(row, 5, QtWidgets.QTableWidgetItem(str(getattr(io, 'read_time', 0))))
            self.disks.setItem(row, 6, QtWidgets.QTableWidgetItem(str(getattr(io, 'write_time', 0))))
            busy = getattr(io, 'busy_time', None)
            self.disks.setItem(row, 7, QtWidgets.QTableWidgetItem(str(busy) if busy is not None else "-"))

        self.disks.setSortingEnabled(True)
        self.disks.sortItems(d_sort_col, d_sort_order)
        self.disks.verticalScrollBar().setValue(d_scroll)

    def showEvent(self, e: QtGui.QShowEvent):
        """Start refreshing when the tab becomes visible."""
        self.refresh()
        self.timer.start(self.update_ms)
        super().showEvent(e)

    def hideEvent(self, e: QtGui.QHideEvent):
        """Pause updates when the tab is hidden."""
        self.timer.stop()
        super().hideEvent(e)

    def set_update_ms(self, ms: int) -> None:
        """Adjust refresh interval for the file system information."""
        self.update_ms = max(50, int(ms))
        if self.timer.isActive():
            self.timer.start(self.update_ms)


# ------------------------------- Preferences dialog -------------------------------

class PreferencesDialog(QtWidgets.QDialog):
    """
    Tune refresh rates and the Resources tab at runtime:
      - History window (seconds)
      - Plot update interval (ms)  [graphs]
      - Text update interval (ms) [legend numbers & labels]
      - Processes refresh interval (ms)
      - File systems refresh interval (ms)
      - CPU EMA alpha
      - Memory EMA alpha
      - Network EMA alpha
      - Show per-CPU frequencies
      - Show CPU temperature
      - Thread line width (px)
      - Toggle X grid / Y grid
      - Grid squares per axis
      - Smooth graphs (EMA filtering)
      - Extra smoothing (double-EMA) for CPU lines
      - Fill CPU graphs with transparency
      - Smooth network graph (EMA)
      - Enable/disable antialiasing
      - CPU view mode
      - Mini plot size/columns and mono color for Multi window mode
      - Theme selection
    """
    def __init__(
        self,
        resources_tab: ResourcesTab,
        processes_tab: ProcessesTab,
        filesystems_tab: FileSystemsTab,
        themes: Dict[str, QtGui.QPalette],
        current_theme: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resources_tab = resources_tab
        self.processes_tab = processes_tab
        self.filesystems_tab = filesystems_tab
        self.themes = themes

        def _set_tip(
            form: Optional[QtWidgets.QFormLayout], widget: QtWidgets.QWidget, tip: str
        ) -> None:
            """Assign a tooltip to *widget* and its associated label in *form*.

            Using a helper keeps the tooltip strings close to the widgets while
            ensuring both the field and its label (if any) share the same
            explanation text.
            """
            widget.setToolTip(tip)
            if form is not None:
                label = form.labelForField(widget)
                if label is not None:
                    label.setToolTip(tip)

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

        self.in_proc = QtWidgets.QSpinBox()
        self.in_proc.setRange(50, 10000)
        self.in_proc.setSingleStep(50)
        self.in_proc.setValue(processes_tab.update_ms)

        self.in_fs = QtWidgets.QSpinBox()
        self.in_fs.setRange(50, 10000)
        self.in_fs.setSingleStep(50)
        self.in_fs.setValue(filesystems_tab.update_ms)

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

        self.in_net_ema = QtWidgets.QDoubleSpinBox()
        self.in_net_ema.setDecimals(3)
        self.in_net_ema.setRange(0.0, 0.999)
        self.in_net_ema.setSingleStep(0.01)
        self.in_net_ema.setValue(resources_tab.NET_EMA_ALPHA)

        self.in_show_freq: Optional[QtWidgets.QCheckBox] = None
        if IS_LINUX or IS_WINDOWS:
            self.in_show_freq = QtWidgets.QCheckBox("Show per-CPU frequencies (and average)")
            self.in_show_freq.setChecked(resources_tab.SHOW_CPU_FREQ)

        self.in_show_temp: Optional[QtWidgets.QCheckBox] = None
        if not IS_WINDOWS:
            self.in_show_temp = QtWidgets.QCheckBox("Show CPU temperature")
            self.in_show_temp.setChecked(resources_tab.SHOW_CPU_TEMP)

        self.in_width = QtWidgets.QDoubleSpinBox()
        self.in_width.setRange(0.5, 8.0)
        self.in_width.setSingleStep(0.5)
        self.in_width.setValue(resources_tab.THREAD_LINE_WIDTH)

        self.in_grid_x = QtWidgets.QCheckBox("Show X grid")
        self.in_grid_x.setChecked(resources_tab.SHOW_GRID_X)
        self.in_grid_y = QtWidgets.QCheckBox("Show Y grid")
        self.in_grid_y.setChecked(resources_tab.SHOW_GRID_Y)

        self.in_grid_divs = QtWidgets.QSpinBox()
        self.in_grid_divs.setRange(1, 20)
        self.in_grid_divs.setValue(resources_tab.GRID_DIVS)

        self.in_smooth = QtWidgets.QCheckBox("Smooth graphs (EMA)")
        self.in_smooth.setChecked(resources_tab.SMOOTH_GRAPHS)

        self.in_extra = QtWidgets.QCheckBox("Extra smoothing for CPU lines (double-EMA)")
        self.in_extra.setChecked(resources_tab.EXTRA_SMOOTHING)
        self.in_extra.setEnabled(resources_tab.SMOOTH_GRAPHS)
        self.in_smooth.toggled.connect(self.in_extra.setEnabled)

        self.in_cpu_fill = QtWidgets.QCheckBox("Fill CPU graphs with transparency")
        self.in_cpu_fill.setChecked(resources_tab.FILL_CPU)

        self.in_net_smooth = QtWidgets.QCheckBox("Smooth network graph (EMA)")
        self.in_net_smooth.setChecked(resources_tab.SMOOTH_NET_GRAPH)

        self.in_antialias = QtWidgets.QCheckBox("Enable antialiasing (smooth curves)")
        self.in_antialias.setChecked(resources_tab.ANTIALIAS)
        self.in_cpu_mode = QtWidgets.QComboBox()
        for name in ResourcesTab.CPU_VIEW_MODES:
            self.in_cpu_mode.addItem(name)
        self.in_cpu_mode.setCurrentText(resources_tab.cpu_view_mode)

        self.in_mini_w = QtWidgets.QSpinBox()
        self.in_mini_w.setRange(20, 1000)
        self.in_mini_w.setValue(resources_tab.CPU_MINI_MIN_W)

        self.in_mini_h = QtWidgets.QSpinBox()
        self.in_mini_h.setRange(20, 1000)
        self.in_mini_h.setValue(resources_tab.CPU_MINI_MIN_H)

        self.in_multi_cols = QtWidgets.QSpinBox()
        self.in_multi_cols.setRange(1, 32)
        self.in_multi_cols.setValue(resources_tab.CPU_MULTI_COLS)

        self.in_mono_chk = QtWidgets.QCheckBox("Mono color for multi-window plots")
        self.in_mono_chk.setChecked(resources_tab.CPU_MULTI_MONO)
        self.mono_color = QtGui.QColor(resources_tab.cpu_mono_color)
        self.in_mono_btn = QtWidgets.QPushButton("Pick color")
        self.in_mono_btn.clicked.connect(self._choose_mono_color)
        self.in_mono_chk.toggled.connect(self.in_mono_btn.setEnabled)
        self.in_mono_btn.setEnabled(resources_tab.CPU_MULTI_MONO)
        self._update_mono_btn()

        self.in_multi_axes = QtWidgets.QCheckBox("Show axes in multi-window plots")
        self.in_multi_axes.setChecked(resources_tab.CPU_MULTI_AXES)

        self.in_label_mode = QtWidgets.QComboBox()
        self.in_label_mode.addItems(["Inside", "Above"])
        self.in_label_mode.setCurrentText(
            "Inside" if resources_tab.CPU_MULTI_LABEL_INSIDE else "Above"
        )
        self.label_color = QtGui.QColor(resources_tab.cpu_label_color)
        self.in_label_btn = QtWidgets.QPushButton("Pick color")
        self.in_label_btn.clicked.connect(self._choose_label_color)

        self.in_theme = QtWidgets.QComboBox()
        for name in themes.keys():
            self.in_theme.addItem(name)
        self.in_theme.setCurrentText(current_theme)

        self.general_color = QtGui.QColor(resources_tab.cpu_general_color)
        self.in_general_btn = QtWidgets.QPushButton("Pick color")
        self.in_general_btn.clicked.connect(self._choose_general_color)
        self._update_general_btn()

        self.in_label_match = QtWidgets.QCheckBox("Match label color to plot")
        self.in_label_match.setChecked(resources_tab.CPU_MULTI_LABEL_MATCH)
        self.in_label_match.toggled.connect(self._update_label_btn)
        self._update_label_btn()

        top_form = QtWidgets.QFormLayout()
        top_form.setLabelAlignment(QtCore.Qt.AlignRight)
        top_form.addRow("Theme:", self.in_theme)
        _set_tip(top_form, self.in_theme, "Select the colour theme for the application.")
        top_form.addRow("CPU view mode:", self.in_cpu_mode)
        _set_tip(top_form, self.in_cpu_mode, "Choose how CPU usage is displayed.")

        global_group = QtWidgets.QGroupBox("Global settings")
        global_form = QtWidgets.QFormLayout(global_group)
        global_form.setLabelAlignment(QtCore.Qt.AlignRight)
        global_form.addRow("History window (seconds):", self.in_history)
        _set_tip(
            global_form,
            self.in_history,
            "Amount of past data (in seconds) retained for graphs.",
        )
        global_form.addRow("Plot update interval (ms):", self.in_plot)
        _set_tip(
            global_form,
            self.in_plot,
            "Delay between graph redraws. Smaller values update more often.",
        )
        global_form.addRow("Text update interval (ms):", self.in_text)
        _set_tip(
            global_form,
            self.in_text,
            "How often labels and numbers are refreshed.",
        )
        global_form.addRow("Processes refresh interval (ms):", self.in_proc)
        _set_tip(
            global_form,
            self.in_proc,
            "Update frequency for the process list.",
        )
        global_form.addRow("File systems refresh interval (ms):", self.in_fs)
        _set_tip(
            global_form,
            self.in_fs,
            "Update frequency for mounted partitions and disk I/O tables.",
        )
        global_form.addRow("CPU EMA alpha (0–0.999):", self.in_ema)
        _set_tip(
            global_form,
            self.in_ema,
            "Smoothing factor for CPU usage graphs (higher = less smoothing).",
        )
        global_form.addRow("Memory EMA alpha (0–0.999):", self.in_mem_ema)
        _set_tip(
            global_form,
            self.in_mem_ema,
            "Smoothing factor for memory usage graphs.",
        )
        global_form.addRow("Network EMA alpha (0–0.999):", self.in_net_ema)
        _set_tip(
            global_form,
            self.in_net_ema,
            "Smoothing factor for network usage graphs.",
        )
        if self.in_show_freq is not None:
            global_form.addRow(self.in_show_freq)
            _set_tip(
                global_form,
                self.in_show_freq,
                "Display per-CPU frequency lines and their average.",
            )
        if self.in_show_temp is not None:
            global_form.addRow(self.in_show_temp)
            _set_tip(
                global_form,
                self.in_show_temp,
                "Display CPU temperature when available.",
            )
        self.in_grid_x.setToolTip("Toggle vertical grid lines on plots.")
        global_form.addRow(self.in_grid_x)
        self.in_grid_y.setToolTip("Toggle horizontal grid lines on plots.")
        global_form.addRow(self.in_grid_y)
        global_form.addRow("Grid squares per axis:", self.in_grid_divs)
        _set_tip(
            global_form,
            self.in_grid_divs,
            "Number of grid divisions along each axis.",
        )
        self.in_net_smooth.setToolTip("Smooth network graph using an EMA filter.")
        global_form.addRow(self.in_net_smooth)
        self.in_antialias.setToolTip(
            "Enable antialiasing for smoother but slower rendering."
        )
        global_form.addRow(self.in_antialias)
        # Allow toggling translucent fill for the average CPU curve
        self.in_cpu_fill.setToolTip(
            "Fill the average CPU graph with a translucent colour."
        )
        global_form.addRow(self.in_cpu_fill)

        thread_group = QtWidgets.QGroupBox("Multi-thread view")
        thread_form = QtWidgets.QFormLayout(thread_group)
        thread_form.setLabelAlignment(QtCore.Qt.AlignRight)
        thread_form.addRow("Thread line width (px):", self.in_width)
        _set_tip(
            thread_form,
            self.in_width,
            "Width of lines in the per-thread CPU view.",
        )
        self.in_smooth.setToolTip(
            "Apply EMA smoothing to per-thread CPU graphs."
        )
        thread_form.addRow(self.in_smooth)
        self.in_extra.setToolTip(
            "Apply a second EMA pass for even smoother CPU lines."
        )
        thread_form.addRow(self.in_extra)

        general_group = QtWidgets.QGroupBox("General view")
        general_form = QtWidgets.QFormLayout(general_group)
        general_form.setLabelAlignment(QtCore.Qt.AlignRight)
        # User-selectable color for the average CPU usage curve
        general_form.addRow("Curve color:", self.in_general_btn)
        _set_tip(
            general_form,
            self.in_general_btn,
            "Colour of the average CPU usage curve in the general view.",
        )

        multi_group = QtWidgets.QGroupBox("Multi window")
        multi_form = QtWidgets.QFormLayout(multi_group)
        multi_form.setLabelAlignment(QtCore.Qt.AlignRight)
        multi_form.addRow("Mini plot min width (px):", self.in_mini_w)
        _set_tip(
            multi_form,
            self.in_mini_w,
            "Minimum width for each plot in multi-window mode.",
        )
        multi_form.addRow("Mini plot min height (px):", self.in_mini_h)
        _set_tip(
            multi_form,
            self.in_mini_h,
            "Minimum height for each plot in multi-window mode.",
        )
        multi_form.addRow("Multi-window columns:", self.in_multi_cols)
        _set_tip(
            multi_form,
            self.in_multi_cols,
            "Number of columns in the multi-window layout.",
        )
        self.in_multi_axes.setToolTip(
            "Display axes on each multi-window plot."
        )
        multi_form.addRow("Show axes in multi-window:", self.in_multi_axes)
        multi_form.addRow(self.in_mono_chk, self.in_mono_btn)
        self.in_mono_chk.setToolTip(
            "Use a single colour for all CPU plots in multi-window mode."
        )
        self.in_mono_btn.setToolTip("Choose the colour used when mono colour is enabled.")
        multi_form.addRow("CPU label placement:", self.in_label_mode)
        _set_tip(
            multi_form,
            self.in_label_mode,
            "Position of CPU labels within multi-window plots.",
        )
        multi_form.addRow(self.in_label_match)
        self.in_label_match.setToolTip(
            "Automatically match CPU label colour to its plot colour."
        )
        multi_form.addRow("CPU label color:", self.in_label_btn)
        _set_tip(
            multi_form,
            self.in_label_btn,
            "Custom colour for CPU labels when not matched to plot colour.",
        )

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok
            | QtWidgets.QDialogButtonBox.Apply
            | QtWidgets.QDialogButtonBox.Cancel
            | QtWidgets.QDialogButtonBox.RestoreDefaults,
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self.apply)
        btns.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(
            self.restore_defaults
        )

        # Make the dialog scrollable to keep controls reachable on small screens
        content = QtWidgets.QWidget()
        content_lay = QtWidgets.QVBoxLayout(content)
        content_lay.addLayout(top_form)
        content_lay.addWidget(global_group)
        content_lay.addWidget(thread_group)
        content_lay.addWidget(general_group)
        content_lay.addWidget(multi_group)
        content_lay.addStretch()

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(scroll)
        lay.addWidget(btns)

    def _update_mono_btn(self):
        self.in_mono_btn.setStyleSheet(f"background-color: {self.mono_color.name()};")

    def _choose_mono_color(self):
        col = QtWidgets.QColorDialog.getColor(self.mono_color, self, "Select color")
        if col.isValid():
            self.mono_color = col
            self._update_mono_btn()

    def _update_label_btn(self):
        self.in_label_btn.setStyleSheet(
            f"background-color: {self.label_color.name()};"
        )
        self.in_label_btn.setEnabled(not self.in_label_match.isChecked())

    def _choose_label_color(self):
        col = QtWidgets.QColorDialog.getColor(
            self.label_color, self, "Select color"
        )
        if col.isValid():
            self.label_color = col
            self._update_label_btn()

    def _update_general_btn(self):
        self.in_general_btn.setStyleSheet(
            f"background-color: {self.general_color.name()};"
        )

    def _choose_general_color(self):
        col = QtWidgets.QColorDialog.getColor(
            self.general_color, self, "Select color"
        )
        if col.isValid():
            self.general_color = col
            self._update_general_btn()

    def _read_values(self):
        return (
            int(self.in_history.value()),
            int(self.in_plot.value()),
            int(self.in_text.value()),
            int(self.in_proc.value()),
            int(self.in_fs.value()),
            float(self.in_ema.value()),
            float(self.in_mem_ema.value()),
            float(self.in_net_ema.value()),
            bool(self.in_show_freq.isChecked()) if self.in_show_freq is not None else False,
            bool(self.in_show_temp.isChecked()) if self.in_show_temp is not None else False,
            float(self.in_width.value()),
            bool(self.in_grid_x.isChecked()),
            bool(self.in_grid_y.isChecked()),
            int(self.in_grid_divs.value()),
            bool(self.in_smooth.isChecked()),
            bool(self.in_extra.isChecked()),
            bool(self.in_antialias.isChecked()),
            self.in_cpu_mode.currentText(),
            bool(self.in_cpu_fill.isChecked()),
            bool(self.in_net_smooth.isChecked()),
            int(self.in_mini_w.value()),
            int(self.in_mini_h.value()),
            int(self.in_multi_cols.value()),
            bool(self.in_multi_axes.isChecked()),
            bool(self.in_mono_chk.isChecked()),
            self.mono_color.name(),
            self.in_label_mode.currentText(),
            bool(self.in_label_match.isChecked()),
            self.label_color.name(),
            self.general_color.name(),
            self.in_theme.currentText(),
        )

    def apply(self):
        (
            history,
            plot_ms,
            text_ms,
            proc_ms,
            fs_ms,
            ema,
            mem_ema,
            net_ema,
            show_freq,
            show_temp,
            width,
            grid_x,
            grid_y,
            grid_divs,
            smooth,
            extra,
            antialias,
            cpu_mode,
            fill_cpu,
            net_smooth,
            mini_w,
            mini_h,
            multi_cols,
            multi_axes,
            mono_chk,
            mono_color,
            label_pos,
            label_match,
            label_color,
            general_color,
            theme_name,
        ) = self._read_values()
        self.resources_tab.apply_settings(
            history_seconds=history,
            plot_update_ms=plot_ms,
            text_update_ms=text_ms,
            ema_alpha=ema,
            mem_ema_alpha=mem_ema,
            show_cpu_freq=show_freq,
            show_cpu_temp=show_temp,
            thread_line_width=width,
            show_grid_x=grid_x,
            show_grid_y=grid_y,
            grid_divs=grid_divs,
            smooth_graphs=smooth,
            extra_smoothing=extra,
            antialias=antialias,
            cpu_view_mode=cpu_mode,
            fill_cpu=fill_cpu,
            smooth_net_graph=net_smooth,
            net_ema_alpha=net_ema,
            mini_w=mini_w,
            mini_h=mini_h,
            multi_cols=multi_cols,
            multi_axes=multi_axes,
            multi_mono=mono_chk,
            mono_color=mono_color,
            general_color=general_color,
            label_pos=label_pos,
            label_match=label_match,
            label_color=label_color,
        )
        self.processes_tab.set_update_ms(proc_ms)
        self.filesystems_tab.set_update_ms(fs_ms)
        parent = self.parent()
        if parent is not None and hasattr(parent, "save_preferences"):
            parent.save_preferences(
                {
                    "history_seconds": history,
                    "plot_update_ms": plot_ms,
                    "text_update_ms": text_ms,
                    "proc_update_ms": proc_ms,
                    "fs_update_ms": fs_ms,
                    "ema_alpha": ema,
                    "mem_ema_alpha": mem_ema,
                    "net_ema_alpha": net_ema,
                    "show_cpu_freq": show_freq,
                    "show_cpu_temp": show_temp,
                    "thread_line_width": width,
                    "show_grid_x": grid_x,
                    "show_grid_y": grid_y,
                    "grid_divs": grid_divs,
                    "smooth_graphs": smooth,
                    "extra_smoothing": extra,
                    "antialias": antialias,
                    "cpu_view_mode": cpu_mode,
                    "fill_cpu": fill_cpu,
                    "smooth_net_graph": net_smooth,
                    "cpu_mini_min_w": mini_w,
                    "cpu_mini_min_h": mini_h,
                    "cpu_multi_cols": multi_cols,
                    "cpu_multi_axes": multi_axes,
                    "cpu_multi_mono": mono_chk,
                    "cpu_mono_color": mono_color,
                    "cpu_general_color": general_color,
                    "cpu_label_pos": label_pos,
                    "cpu_label_match": label_match,
                    "cpu_label_color": label_color,
                }
            )
        if parent is not None and hasattr(parent, "apply_theme"):
            parent.apply_theme(theme_name)

    def accept(self):
        self.apply()
        super().accept()

    def restore_defaults(self):
        self.in_history.setValue(ResourcesTab.HISTORY_SECONDS)
        self.in_plot.setValue(ResourcesTab.PLOT_UPDATE_MS)
        self.in_text.setValue(ResourcesTab.TEXT_UPDATE_MS)
        self.in_proc.setValue(ProcessesTab.UPDATE_MS)
        self.in_fs.setValue(FileSystemsTab.UPDATE_MS)
        self.in_ema.setValue(ResourcesTab.EMA_ALPHA)
        self.in_mem_ema.setValue(ResourcesTab.MEM_EMA_ALPHA)
        self.in_net_ema.setValue(ResourcesTab.NET_EMA_ALPHA)
        if self.in_show_freq is not None:
            self.in_show_freq.setChecked(ResourcesTab.SHOW_CPU_FREQ)
        if self.in_show_temp is not None:
            self.in_show_temp.setChecked(ResourcesTab.SHOW_CPU_TEMP)
        self.in_width.setValue(ResourcesTab.THREAD_LINE_WIDTH)
        self.in_grid_x.setChecked(ResourcesTab.SHOW_GRID_X)
        self.in_grid_y.setChecked(ResourcesTab.SHOW_GRID_Y)
        self.in_grid_divs.setValue(ResourcesTab.GRID_DIVS)
        self.in_smooth.setChecked(ResourcesTab.SMOOTH_GRAPHS)
        self.in_extra.setChecked(ResourcesTab.EXTRA_SMOOTHING)
        self.in_extra.setEnabled(ResourcesTab.SMOOTH_GRAPHS)
        self.in_cpu_fill.setChecked(ResourcesTab.FILL_CPU)
        self.in_net_smooth.setChecked(ResourcesTab.SMOOTH_NET_GRAPH)
        self.in_antialias.setChecked(ResourcesTab.ANTIALIAS)
        self.in_cpu_mode.setCurrentText(ResourcesTab.CPU_VIEW_MODE)
        self.in_mini_w.setValue(ResourcesTab.CPU_MINI_MIN_W)
        self.in_mini_h.setValue(ResourcesTab.CPU_MINI_MIN_H)
        self.in_multi_cols.setValue(ResourcesTab.CPU_MULTI_COLS)
        self.in_multi_axes.setChecked(ResourcesTab.CPU_MULTI_AXES)
        self.in_mono_chk.setChecked(ResourcesTab.CPU_MULTI_MONO)
        self.in_mono_btn.setEnabled(ResourcesTab.CPU_MULTI_MONO)
        self.mono_color = QtGui.QColor(self.resources_tab.cpu_colors[0])
        self._update_mono_btn()
        self.in_label_mode.setCurrentText(
            "Inside" if ResourcesTab.CPU_MULTI_LABEL_INSIDE else "Above"
        )
        self.in_label_match.setChecked(ResourcesTab.CPU_MULTI_LABEL_MATCH)
        self.label_color = QtGui.QColor(ResourcesTab.CPU_MULTI_LABEL_COLOR)
        self._update_label_btn()
        self.general_color = QtGui.QColor(self.resources_tab.cpu_colors[0])
        self._update_general_btn()
        self.in_theme.setCurrentText(DEFAULT_THEME)
        self.apply()


# ------------------------------- About dialog -------------------------------

class AboutDialog(QtWidgets.QDialog):
    """Simple scrollable dialog showing project information."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About KLV System Monitor")
        self.resize(680, 900)

        # Scroll area allows the text and images to exceed the dialog size.
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)

        content = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(content)
        vbox.setAlignment(QtCore.Qt.AlignTop)

        base_path = Path(__file__).resolve().parent / "miscellaneous" / "images"

        # Project logo at the top
        logo_lbl = QtWidgets.QLabel()
        logo_pix = QtGui.QPixmap(str(base_path / "icon.png"))
        if not logo_pix.isNull():
            logo_pix = logo_pix.scaled(128, 128, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            logo_lbl.setPixmap(logo_pix)
        logo_lbl.setAlignment(QtCore.Qt.AlignCenter)
        vbox.addWidget(logo_lbl)

        # Title under the logo
        title_lbl = QtWidgets.QLabel("KLV System Monitor")
        title_font = title_lbl.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setAlignment(QtCore.Qt.AlignCenter)
        vbox.addWidget(title_lbl)

        # Project description
        desc = (
            "This software has been developed with the objective of providing a "
            "lightweight, efficient, and cross-platform solution for system monitoring.\n"
            "KLV System Monitor enables users to keep track of CPU, memory, network, and "
            "filesystem usage in real time, with a focus on clarity, responsiveness, and "
            "extensibility. The intention is to create a tool that is both useful for "
            "everyday users and robust enough for developers and researchers who require "
            "precise resource tracking.\n\n"
            "The project is inspired by GNOME System Monitor, adapting its clarity and "
            "usability into a cross-platform environment. Since no comparable alternative "
            "existed for Windows or other systems, KLV System Monitor was designed to fill "
            "this gap."
        )
        desc_lbl = QtWidgets.QLabel(desc)
        desc_lbl.setWordWrap(True)
        vbox.addWidget(desc_lbl)

        # Author photograph
        photo_lbl = QtWidgets.QLabel()
        photo_pix = QtGui.QPixmap(str(base_path / "Karel.jpeg"))
        if not photo_pix.isNull():
            photo_pix = photo_pix.scaled(200, 200, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            photo_lbl.setPixmap(photo_pix)
        photo_lbl.setAlignment(QtCore.Qt.AlignCenter)
        vbox.addWidget(photo_lbl)

        # Author heading and name/role
        author_hdr = QtWidgets.QLabel("Author")
        author_font = author_hdr.font()
        author_font.setBold(True)
        author_hdr.setFont(author_font)
        author_hdr.setAlignment(QtCore.Qt.AlignCenter)
        vbox.addWidget(author_hdr)

        name_lbl = QtWidgets.QLabel("Dr. Karel López Vilaret\nKLV System Monitor Lead Developer")
        name_lbl.setAlignment(QtCore.Qt.AlignCenter)
        vbox.addWidget(name_lbl)

        # Author biography
        bio = (
            "I hold a PhD in Neuroscience and currently work as a scientific software "
            "developer. My research has always been closely tied to computational "
            "optimization, parallelization, and high-performance data analysis.\n"
            "Building on this experience, I created KLV System Monitor as a personal "
            "project to bring the same principles of efficiency and clarity into a system "
            "monitoring tool—combining performance insights with an intuitive interface."
        )
        bio_lbl = QtWidgets.QLabel(bio)
        bio_lbl.setWordWrap(True)
        vbox.addWidget(bio_lbl)

        # Connect links
        connect_hdr = QtWidgets.QLabel("Connect with me")
        connect_font = connect_hdr.font()
        connect_font.setBold(True)
        connect_hdr.setFont(connect_font)
        connect_hdr.setAlignment(QtCore.Qt.AlignCenter)
        vbox.addWidget(connect_hdr)

        linkedin_lbl = QtWidgets.QLabel(
            '🔗 <a href="https://www.linkedin.com/in/karel-l%C3%B3pez-vilaret/">LinkedIn</a>'
        )
        linkedin_lbl.setAlignment(QtCore.Qt.AlignCenter)
        linkedin_lbl.setOpenExternalLinks(True)
        vbox.addWidget(linkedin_lbl)

        github_lbl = QtWidgets.QLabel(
            '💻 <a href="https://github.com/karellopez/KLV-System-Monitor">GitHub</a>'
        )
        github_lbl.setAlignment(QtCore.Qt.AlignCenter)
        github_lbl.setOpenExternalLinks(True)
        vbox.addWidget(github_lbl)

        scroll.setWidget(content)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(scroll)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

# ------------------------------- Main window -------------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KLV System Monitor")
        # Load and apply the application icon so it shows in the window title
        # bar and in the taskbar/dock.  The icon lives inside the package so we
        # build its path relative to this file.
        icon_path = Path(__file__).resolve().parent / "miscellaneous" / "images" / "icon.png"
        self.setWindowIcon(QtGui.QIcon(str(icon_path)))
        self.resize(860, 950)

        # Centered tabs
        self.tabs = CenteredTabWidget()
        self.processes_tab   = ProcessesTab()
        self.resources_tab   = ResourcesTab()
        self.filesystems_tab = FileSystemsTab()
        # Show Resources first by default
        self.tabs.addTab(self.resources_tab,  "Resources")
        self.tabs.addTab(self.processes_tab,  "Processes")
        self.tabs.addTab(self.filesystems_tab,"File Systems")
        # Track tab changes so that timers for the Processes and File Systems
        # views only run while their tab is visible.
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Put centered tabs into the main area
        container = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(container)
        v.setContentsMargins(6, 6, 6, 6)
        v.addWidget(self.tabs)

        # About / Preferences buttons in the lower right corner
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        # About button shows information about the application and its author
        self.about_btn = QtWidgets.QPushButton("About")
        self.about_btn.clicked.connect(self.open_about)
        btn_layout.addWidget(self.about_btn)
        self.pref_btn = QtWidgets.QPushButton("Preferences")
        self.pref_btn.clicked.connect(self.open_preferences)
        btn_layout.addWidget(self.pref_btn)
        v.addLayout(btn_layout)
        self.setCentralWidget(container)

        # Preferences directory and theme support
        self.pref_dir = PREF_DIR
        try:
            self.pref_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.settings_file = self.pref_dir / "settings.json"
        self.theme_file = self.pref_dir / "theme.txt"
        self.themes = build_theme_dict()
        self.current_theme = None

        default_theme = DEFAULT_THEME
        if self.theme_file.exists():
            try:
                default_theme = self.theme_file.read_text().strip() or default_theme
            except Exception:
                pass
        self.apply_theme(default_theme)
        self._load_preferences()
        # Ensure only the active tab (Resources by default) has its refresh
        # timers running at startup.
        self._on_tab_changed(self.tabs.currentIndex())

    def open_preferences(self):
        dlg = PreferencesDialog(
            self.resources_tab,
            self.processes_tab,
            self.filesystems_tab,
            self.themes,
            self.current_theme,
            self,
        )
        dlg.exec_()

    def open_about(self):
        """Show the About dialog with project and author information."""
        dlg = AboutDialog(self)
        dlg.exec_()

    def _on_tab_changed(self, index: int) -> None:
        """Start or stop refresh timers when tabs are switched."""
        if index == 1:  # Processes tab
            self.processes_tab.refresh()
            self.processes_tab.timer.start(self.processes_tab.update_ms)
            self.filesystems_tab.timer.stop()
        elif index == 2:  # File Systems tab
            self.filesystems_tab.refresh()
            self.filesystems_tab.timer.start(self.filesystems_tab.update_ms)
            self.processes_tab.timer.stop()
        else:  # Resources tab
            self.processes_tab.timer.stop()
            self.filesystems_tab.timer.stop()

    def apply_theme(self, name: str):
        app = QtWidgets.QApplication.instance()
        palette = self.themes[name]
        app.setPalette(palette)
        self.setPalette(palette)
        for tab in (self.processes_tab, self.resources_tab, self.filesystems_tab):
            tab.setPalette(palette)
        pg.setConfigOption('background', palette.color(QtGui.QPalette.Window))
        pg.setConfigOption('foreground', palette.color(QtGui.QPalette.WindowText))
        self.resources_tab.apply_theme(palette)
        self.current_theme = name
        try:
            self.theme_file.write_text(name)
        except Exception:
            pass

    # --------- persistence helpers ---------
    def _load_preferences(self):
        if self.settings_file.exists():
            try:
                data = json.loads(self.settings_file.read_text())
            except Exception:
                return
            self.resources_tab.apply_settings(
                history_seconds=data.get("history_seconds", self.resources_tab.HISTORY_SECONDS),
                plot_update_ms=data.get("plot_update_ms", self.resources_tab.PLOT_UPDATE_MS),
                text_update_ms=data.get("text_update_ms", self.resources_tab.TEXT_UPDATE_MS),
                ema_alpha=data.get("ema_alpha", self.resources_tab.EMA_ALPHA),
                mem_ema_alpha=data.get("mem_ema_alpha", self.resources_tab.MEM_EMA_ALPHA),
                show_cpu_freq=data.get("show_cpu_freq", self.resources_tab.SHOW_CPU_FREQ),
                show_cpu_temp=data.get("show_cpu_temp", self.resources_tab.SHOW_CPU_TEMP),
                thread_line_width=data.get("thread_line_width", self.resources_tab.THREAD_LINE_WIDTH),
                show_grid_x=data.get("show_grid_x", self.resources_tab.SHOW_GRID_X),
                show_grid_y=data.get("show_grid_y", self.resources_tab.SHOW_GRID_Y),
                grid_divs=data.get("grid_divs", self.resources_tab.GRID_DIVS),
                smooth_graphs=data.get("smooth_graphs", self.resources_tab.SMOOTH_GRAPHS),
                extra_smoothing=data.get("extra_smoothing", self.resources_tab.EXTRA_SMOOTHING),
                antialias=data.get("antialias", self.resources_tab.ANTIALIAS),
                cpu_view_mode=data.get("cpu_view_mode", self.resources_tab.CPU_VIEW_MODE),
                fill_cpu=data.get("fill_cpu", self.resources_tab.FILL_CPU),
                smooth_net_graph=data.get("smooth_net_graph", self.resources_tab.SMOOTH_NET_GRAPH),
                net_ema_alpha=data.get("net_ema_alpha", self.resources_tab.NET_EMA_ALPHA),
                mini_w=data.get("cpu_mini_min_w", self.resources_tab.CPU_MINI_MIN_W),
                mini_h=data.get("cpu_mini_min_h", self.resources_tab.CPU_MINI_MIN_H),
                multi_cols=data.get("cpu_multi_cols", self.resources_tab.CPU_MULTI_COLS),
                multi_axes=data.get("cpu_multi_axes", self.resources_tab.CPU_MULTI_AXES),
                multi_mono=data.get("cpu_multi_mono", self.resources_tab.CPU_MULTI_MONO),
                mono_color=data.get("cpu_mono_color", self.resources_tab.cpu_mono_color.name()),
                general_color=data.get(
                    "cpu_general_color", self.resources_tab.cpu_general_color.name()
                ),
                label_pos=data.get(
                    "cpu_label_pos",
                    "Inside" if self.resources_tab.CPU_MULTI_LABEL_INSIDE else "Above",
                ),
                label_match=data.get(
                    "cpu_label_match", self.resources_tab.CPU_MULTI_LABEL_MATCH
                ),
                label_color=data.get(
                    "cpu_label_color", self.resources_tab.cpu_label_color.name()
                ),
            )
            self.processes_tab.set_update_ms(
                data.get("proc_update_ms", self.processes_tab.UPDATE_MS)
            )
            self.filesystems_tab.set_update_ms(
                data.get("fs_update_ms", self.filesystems_tab.UPDATE_MS)
            )

    def save_preferences(self, data: Dict[str, object]):
        try:
            self.settings_file.write_text(json.dumps(data, indent=2))
        except Exception:
            pass


def main():
    # On Windows, set an explicit AppUserModelID so the custom application icon
    # is used in the taskbar instead of the default python.exe icon.
    if sys.platform.startswith("win"):
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "klv.system.monitor"
        )

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")

    # Apply the application icon so it appears in the window title bar and the
    # taskbar/dock.
    icon_path = Path(__file__).resolve().parent / "miscellaneous" / "images" / "icon.png"
    app.setWindowIcon(QtGui.QIcon(str(icon_path)))

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
