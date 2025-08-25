# KLV-System-Monitor

KLV System Monitor is a lightweight, cross-platform system monitoring tool
written in Python with PyQt5 and psutil. It provides a modern, customizable
interface inspired by the Ubuntu system monitor, while adding advanced features
for efficiency, flexibility, and user control.

CPU usage can be visualized in three modes—**Multi thread**, **General view**, and
**Multi window**—selectable from the Preferences dialog.

Plots adapt to the selected theme. "Multi window" graphs show axes without tick
labels and overlay each core's usage, number, and optional frequency atop its
panel. The Preferences dialog exposes controls for mini-plot size, column
count, a single-color option for all cores, and separate EMA alphas for CPU,
memory, and network graphs. CPU plots can optionally be filled with translucent
color, and network smoothing can be toggled independently.

Recent updates further reduce the monitor's own CPU usage by batching
per-process information retrieval, decoupling plot and text refresh rates,
and refreshing the file system view only on demand. Graph antialiasing is
enabled again for crisp rendering and can now be toggled in Preferences.
The Processes tab now updates only when visible, and its refresh interval is
configurable via the Preferences dialog.

The Processes tab also includes buttons to clear the current selection so the
view stops following a particular process and to kill selected processes.

## Requirements

| Software  | Minimum Version | Notes                                                   |
|----------|-----------------|---------------------------------------------------------|
| **Python** | 3.10            | Installed automatically if you use the one-click installers |

---

## Installation

You can install KLV System Monitor in two ways:

### 1. One-click installers <sup>(recommended)</sup>

1. **Download** the ZIP package:  
   **[📦 One-click Installers](https://github.com/karellopez/KLV-System-Monitor/raw/main/Installers/Installers.zip
)**
2. **Extract** the ZIP file and run the script for your operating system:

| OS               | Script                           | How to Run                                                                                                                                                                                                         | Duration |
|------------------|----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------|
| **Windows 10/11**| `install_klv_system_monitor.bat` | Double-click. This will open a terminal and the installation will start.<br/>If you are not familiar to terminals, please, do not be afraid. <br/>This script do not have any permission to make undesired things. | ≈ 5 min |
| **Linux**        | `install_klv_system_monitor.sh`        | Open a terminal in the path fo the installer and type: <br/>`./klv_system_monitor.sh`                                                                                                                              | ≈ 5 min |

3. After the installation finishes, you will find two shortcuts on your desktop:

| OS          | Launch                            | Uninstall                       |
|-------------|-----------------------------------|---------------------------------|
| **Windows** | `run_KLVSystemMonitor.bat`             | `uninstall_KLVSystemMonitor.bat`     |
| **Linux**   | **KLV System Monitor** (launcher) | `Uninstall KLV System Monitor`  |

---

### 2. Install in a virtual environment (advanced)

```bash
# 1. Create a virtual environment
python3 -m venv <env_name>

# 2. Activate it
source <env_name>/bin/activate          # On Windows: <env_name>\Scripts\activate

# 3. Install BIDS Manager from GitHub
pip install klv-system-monitor
```
The package declares all dependencies, so installation
pulls everything required to run the GUI and helper scripts.
All core requirements are version pinned in `pyproject.toml` to ensure
consistent installations.

After installation the following commands become available:

- `klvtop` – main GUI containing all KLV System Monitor functionalities