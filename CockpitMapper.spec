# -*- mode: python ; coding: utf-8 -*-
"""
CockpitMapper.spec - one-file build of the GUI plus the mapper runtime.

The entry point is app.py, which dispatches to gui.main() or main.main()
depending on the --run-mapper sentinel. Both halves are imported lazily,
inside functions, so PyInstaller's static analysis never sees them. They
are listed in hiddenimports below.

utils/ has no __init__.py files, so it is a PEP 420 namespace package and
is not walked automatically either. Rather than rely on it being
importable at analysis time, the submodule list is built from the files
on disk - one less thing that can silently come up empty.

The .ini profiles are deliberately NOT bundled: app_paths.app_dir()
resolves them next to the .exe so they stay editable after the build.
"""

import os

# app.py, gui.py, main.py and utils/ all live beside this spec file.
# PyInstaller does not put the spec's directory on sys.path by itself.
PROJECT_DIR = SPECPATH


def _package_modules(package):
    """Dotted module names for every .py file under `package`."""
    found = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(PROJECT_DIR, package)):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for filename in filenames:
            if not filename.endswith('.py'):
                continue
            relative = os.path.relpath(os.path.join(dirpath, filename), PROJECT_DIR)
            found.append(relative[:-3].replace(os.sep, '.'))
    return found


hiddenimports = ['gui', 'main', 'win32api'] + _package_modules('utils')

a = Analysis(
    ['app.py'],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CockpitMapper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX off on purpose. build.bat's own :fail_noexe message names
    # AV quarantine of a freshly UPX-packed exe as the usual reason a
    # build "succeeds" with no exe in dist\. Not packing avoids it.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windowed: app.py calls AllocConsole() itself when it runs the
    # mapper, so mapper mode still gets a console for getch() and prints.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
