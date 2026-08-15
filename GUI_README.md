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
