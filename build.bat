@echo off
setlocal EnableExtensions

rem ---------------------------------------------------------------------------
rem build.bat - check or create the project .venv, then build CockpitMapper.exe
rem
rem Usage:  build.bat [--recreate] [--clean] [--no-pause]
rem
rem Exit codes:
rem   0 success                    5 recreate needed but not consented
rem   1 usage error                6 PyInstaller failed / exe not produced
rem   2 no usable base Python      7 CockpitMapper.spec or app.py missing
rem   3 venv creation failed       8 could not enter the project directory
rem   4 dependency install failed  9 .venv could not be fully removed
rem
rem Deliberately avoids delayed expansion and parenthesised if-blocks: both
rem make %ERRORLEVEL% stale, and delayed expansion eats "!" in paths.
rem ---------------------------------------------------------------------------

set "RC=1"
set "ROOT=%~dp0"
set "VENV_DIR=%ROOT%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "PYGAME_HIDE_SUPPORT_PROMPT=hide"

set "OPT_RECREATE="
set "OPT_NOPAUSE="
set "PI_CLEAN="

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--recreate" goto :arg_recreate
if /i "%~1"=="--clean" goto :arg_clean
if /i "%~1"=="--no-pause" goto :arg_nopause
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
if "%~1"=="/?" goto :usage
echo [build] ERROR: unknown argument "%~1"
echo [build] run "build.bat --help" for usage.
set "RC=1"
goto :end_nopop

:arg_recreate
set "OPT_RECREATE=1"
shift
goto :parse_args

:arg_clean
set "PI_CLEAN=--clean"
shift
goto :parse_args

:arg_nopause
set "OPT_NOPAUSE=1"
shift
goto :parse_args

:usage
echo Usage: build.bat [--recreate] [--clean] [--no-pause]
echo.
echo   --recreate   Delete and rebuild .venv from scratch. Without this flag a
echo                broken .venv prompts before anything is deleted.
echo   --clean      Pass --clean to PyInstaller. Use when a source change does
echo                not seem to take effect.
echo   --no-pause   Do not wait for a keypress at the end. Implied when CI or
echo                COCKPITMAPPER_NOPAUSE is set in the environment.
echo   -h, --help   This message.
echo.
echo Set COCKPITMAPPER_PYTHON to a python.exe to override base interpreter
echo detection when the "py" launcher is unavailable.
set "RC=0"
goto :end_nopop

:args_done
if defined CI set "OPT_NOPAUSE=1"
if defined COCKPITMAPPER_NOPAUSE set "OPT_NOPAUSE=1"

pushd "%ROOT%"
if errorlevel 1 goto :fail_pushd

echo [build] project: %ROOT%

if not exist "CockpitMapper.spec" goto :fail_spec
if not exist "app.py" goto :fail_spec

if defined OPT_RECREATE goto :recreate_requested
if not exist "%VENV_PY%" goto :venv_absent

echo [build] checking .venv interpreter
"%VENV_PY%" -c "import os,sys; sys.exit(0 if os.path.normcase(os.path.realpath(sys.prefix))==os.path.normcase(os.path.realpath(sys.argv[1])) else 1)" "%VENV_DIR%"
if errorlevel 1 goto :venv_broken

echo [build] checking .venv packages
"%VENV_PY%" -c "import importlib;[importlib.import_module(m) for m in ['PyInstaller','colorama','win32api','tkinter','pygame']]"
if errorlevel 1 goto :venv_incomplete

echo [build] .venv OK
goto :build

rem --- venv states ----------------------------------------------------------

:venv_absent
echo [build] no .venv found at %VENV_DIR%
goto :create

:venv_incomplete
echo [build] .venv cannot load one or more required packages, see the traceback
echo [build] above. Repairing in place - nothing will be deleted.
goto :install

:venv_broken
echo [build] .venv exists but its interpreter will not run, or does not belong
echo [build] to this directory. Usual causes: the repo was moved, or the base
echo [build] Python was removed or upgraded.
goto :confirm_delete

:recreate_requested
if not exist "%VENV_DIR%" goto :create
echo [build] --recreate given.
goto :do_delete

:confirm_delete
echo [build] Rebuilding it means deleting:
echo [build]     %VENV_DIR%
echo [build] Close PyCharm / VS Code first - an IDE holding python.exe open
echo [build] leaves a half-deleted directory behind.
choice /c yn /m "[build] Delete and rebuild this .venv"
if errorlevel 255 goto :fail_noconsent
if errorlevel 2 goto :fail_noconsent
if errorlevel 1 goto :do_delete
goto :fail_noconsent

:do_delete
rem Three guards before the only destructive command in this script.
if /i not "%VENV_DIR:~-6%"=="\.venv" goto :fail_guard
if not exist "%VENV_DIR%\pyvenv.cfg" goto :fail_guard
echo [build] removing %VENV_DIR%
rmdir /s /q "%VENV_DIR%"
if exist "%VENV_DIR%" goto :fail_rmdir
goto :create

rem --- create and populate --------------------------------------------------

:create
call :find_base_python
if errorlevel 1 goto :fail_basepy
echo [build] creating venv using "%BASE_PY_EXE%" %BASE_PY_ARG%
"%BASE_PY_EXE%" %BASE_PY_ARG% -m venv "%VENV_DIR%"
if errorlevel 1 goto :fail_create
if not exist "%VENV_PY%" goto :fail_create
"%VENV_PY%" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :fail_install
goto :install

:install
echo [build] installing runtime dependencies
"%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail_install
if not exist "requirements-dev.txt" goto :install_pyinstaller
echo [build] installing build dependencies
"%VENV_PY%" -m pip install --disable-pip-version-check -r requirements-dev.txt
if errorlevel 1 goto :fail_install
goto :recheck

:install_pyinstaller
echo [build] requirements-dev.txt not found, installing PyInstaller directly
"%VENV_PY%" -m pip install --disable-pip-version-check "pyinstaller>=6.22,<7"
if errorlevel 1 goto :fail_install
goto :recheck

:recheck
"%VENV_PY%" -c "import importlib;[importlib.import_module(m) for m in ['PyInstaller','colorama','win32api','tkinter','pygame']]"
if errorlevel 1 goto :fail_probe
echo [build] .venv ready
goto :build

rem --- build ----------------------------------------------------------------

:build
echo [build] running PyInstaller on CockpitMapper.spec
"%VENV_PY%" -m PyInstaller CockpitMapper.spec --noconfirm %PI_CLEAN%
if errorlevel 1 goto :fail_build
if not exist "dist\CockpitMapper.exe" goto :fail_noexe
for %%F in ("dist\CockpitMapper.exe") do echo [build] OK  %%~fF  %%~zF bytes  %%~tF
echo [build] the .ini profiles are not bundled - keep them beside the exe.
set "RC=0"
goto :end

rem --- base interpreter lookup ----------------------------------------------

:find_base_python
set "BASE_PY_EXE="
set "BASE_PY_ARG="
if not defined COCKPITMAPPER_PYTHON goto :try_py314
set "BASE_PY_EXE=%COCKPITMAPPER_PYTHON%"
"%BASE_PY_EXE%" -c "import sys" >nul 2>&1
if errorlevel 1 goto :base_env_bad
exit /b 0

:base_env_bad
echo [build] COCKPITMAPPER_PYTHON is set but will not run: %COCKPITMAPPER_PYTHON%
set "BASE_PY_EXE="
exit /b 1

:try_py314
py -3.14 -c "import sys" >nul 2>&1
if errorlevel 1 goto :try_py3
set "BASE_PY_EXE=py"
set "BASE_PY_ARG=-3.14"
exit /b 0

:try_py3
py -3 -c "import sys" >nul 2>&1
if errorlevel 1 goto :base_none
set "BASE_PY_EXE=py"
set "BASE_PY_ARG=-3"
echo [build] WARNING: Python 3.14 not found, falling back to:
py -3 -c "import sys; print('[build] WARNING: ' + sys.version.replace(chr(10), ' '))"
echo [build] WARNING: pygame-ce and PyInstaller wheels are only verified on 3.14.
exit /b 0

:base_none
echo [build] ERROR: no usable Python found. Tried, in order:
echo [build]   1. COCKPITMAPPER_PYTHON  - not set
echo [build]   2. py -3.14              - not available
echo [build]   3. py -3                 - not available
echo [build] Install Python 3.14 with the py launcher, or set
echo [build] COCKPITMAPPER_PYTHON to a python.exe.
exit /b 1

rem --- failure funnel -------------------------------------------------------

:fail_pushd
echo [build] ERROR: cannot enter the project directory: %ROOT%
set "RC=8"
goto :end_nopop

:fail_spec
echo [build] ERROR: CockpitMapper.spec or app.py not found in %ROOT%
echo [build] run this script from inside the project checkout.
set "RC=7"
goto :end

:fail_noconsent
echo [build] aborted, nothing was deleted. Re-run with --recreate to confirm.
set "RC=5"
goto :end

:fail_guard
echo [build] ERROR: refusing to delete "%VENV_DIR%" - it does not look like a
echo [build] virtualenv. Remove it by hand if that is really what you want.
set "RC=9"
goto :end

:fail_rmdir
echo [build] ERROR: "%VENV_DIR%" still exists after deletion. Something is
echo [build] holding a file open - close your IDE and any python.exe, then retry.
set "RC=9"
goto :end

:fail_basepy
set "RC=2"
goto :end

:fail_create
echo [build] ERROR: could not create the venv at %VENV_DIR%
set "RC=3"
goto :end

:fail_install
echo [build] ERROR: dependency install failed, see pip output above.
set "RC=4"
goto :end

:fail_probe
echo [build] ERROR: a required package still will not import after installing.
echo [build] If tkinter is the one named, the base Python was installed without
echo [build] the tcl/tk component - re-run the Python installer and enable it.
set "RC=4"
goto :end

:fail_build
echo [build] ERROR: PyInstaller failed, see its output above.
set "RC=6"
goto :end

:fail_noexe
echo [build] ERROR: PyInstaller reported success but dist\CockpitMapper.exe is
echo [build] not there. Antivirus quarantining the fresh UPX-packed exe is the
echo [build] usual cause - check your AV quarantine log.
set "RC=6"
goto :end

:end
popd

:end_nopop
if defined OPT_NOPAUSE goto :end_quiet
pause

:end_quiet
exit /b %RC%
