# Cockpit Mapper GUI

`gui.py` is a desktop editor and launcher for the existing controller runtime.
It uses the same INI profiles as `main.py`, so profiles remain usable from the
command line.

## Start it

On Windows, install Python 3.10 or newer, then run:

```powershell
py -m pip install -r requirements.txt
py gui.py
```

You can also double-click `launch_gui.pyw`. To open a particular profile:

```powershell
py gui.py --config dcs_f16.ini
```

Tkinter is included with the standard Windows installer from python.org. If a
custom Python distribution omitted it, enable the optional “Tcl/Tk and IDLE”
component in the Python installer.

## Workflow

1. Pick an INI profile in the left sidebar.
2. Select **Refresh controllers** after connecting or reconnecting hardware.
3. Add or edit a binding. The device dropdown writes the controller GUID into
   the profile. **Listen for input** captures a pressed button or moved axis;
   **Capture key** records a keyboard shortcut. Output actions are presented as
   labeled options rather than raw colon-separated text.
4. If a device UUID/GUID has changed, open **Device repair**, select the stale
   reference and its connected replacement, then choose **Remap all
   references**.
5. Save, then choose **Start mapper**. Unsaved changes are saved first.

Every save is atomic and creates a sibling `.ini.bak` file before replacing the
profile. Comments and the syntax reference in existing profiles are retained.

The output editor provides tailored controls for keyboard keys, mouse buttons,
wheel acceleration, analog cursor axes, cursor centering, window focus, mouse
wiggle, and accelerated cursor increments. Each action includes a short
explanation. **Advanced / raw** remains available for hand-written action
strings.

## Build a standalone executable

Building must happen on Windows — PyInstaller cannot cross-compile. Install it
once, then build from `app.py`:

```powershell
py -m pip install pyinstaller
py -m PyInstaller --onefile --noconsole --name CockpitMapper --hidden-import main --hidden-import gui --noconfirm app.py
```

Inside a virtual environment, use `.venv\Scripts\pyinstaller.exe` with the same
arguments instead.

The result is a single `dist\CockpitMapper.exe`, roughly 20 MB. `app.py` is the
entry point because the executable contains both halves of the application: run
normally it opens the GUI, and the GUI re-launches the same executable with a
`--run-mapper` flag to start the runtime as a child process.

Copy the INI profiles next to the executable when distributing it:

```
CockpitMapper.exe
bms.ini
dcs_f16.ini
dcsf-18.ini
```

Profiles are deliberately not bundled into the executable, because the GUI has
to be able to save them. The executable reads `*.ini` from its own directory, so
the profile dropdown is empty if the exe is copied out on its own. Place it in a
writable location — not `Program Files` — since `log.log` is written alongside
it.

The command above regenerates `CockpitMapper.spec`. Passing that spec file to
PyInstaller instead of the arguments produces the same build:

```powershell
py -m PyInstaller CockpitMapper.spec --noconfirm
```

PyInstaller caches aggressively. If a source change does not take effect, delete
`build\` and `dist\` and build again, or add `--clean`.
