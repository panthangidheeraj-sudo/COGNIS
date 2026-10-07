@echo off
rem One-click live check for Windows: sets up Python, runs the offline tests, the .env-dependent
rem live checks (register, Groq, Tavily, end-to-end research, API) and the 100-company live smoke test.
rem Results: out\live-check.md, out\smoke-live\smoke-report.md, logs in out\*.log. No secrets are written.
setlocal
cd /d "%~dp0"
if not exist out mkdir out
set PYTHONUTF8=1
set STATUS=out\run-status.txt
set VENV=%LOCALAPPDATA%\cognis\venv
set TEST_RC=not run
set LIVE_RC=not run
set SMOKE_RC=not run
echo [%date% %time%] started > "%STATUS%"

set PY=python
where py >nul 2>nul && set PY=py -3

if not exist "%VENV%\Scripts\python.exe" (
  echo [%time%] creating virtual environment in %VENV% >> "%STATUS%"
  %PY% -m venv "%VENV%" > out\venv.log 2>&1 || goto :fail_python
)
"%VENV%\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3, 11), sys.version" > out\python-version.log 2>&1 || goto :fail_version

echo [%time%] installing dependencies >> "%STATUS%"
echo Installing dependencies (first run takes a minute or two)...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-dev.txt > out\pip.log 2>&1 || goto :fail_pip

echo [%time%] checking .env configuration >> "%STATUS%"
"%VENV%\Scripts\python.exe" -c "import sys; sys.path.insert(0, 'scripts'); import _bootstrap; _bootstrap.bootstrap(quiet=True)" > out\preflight.log 2>&1 || goto :fail_config

echo [%time%] offline tests >> "%STATUS%"
echo Running offline tests...
"%VENV%\Scripts\python.exe" -m pytest -q -p no:cacheprovider > out\pytest.log 2>&1
set TEST_RC=%errorlevel%
echo [%time%] offline tests exit code %TEST_RC% >> "%STATUS%"

echo [%time%] live checks (register, LLM, search, research, API) >> "%STATUS%"
echo Running live checks (register, Groq, search, 3 companies, API) - a few minutes...
"%VENV%\Scripts\python.exe" scripts\live_check.py > out\live-check.log 2>&1
set LIVE_RC=%errorlevel%
echo [%time%] live checks exit code %LIVE_RC% >> "%STATUS%"

echo [%time%] 100-company live smoke test >> "%STATUS%"
echo Running the 100-company live smoke test - this can take 10-40 minutes...
"%VENV%\Scripts\python.exe" scripts\smoke_test.py --live > out\smoke-live.log 2>&1
set SMOKE_RC=%errorlevel%
echo [%time%] smoke test exit code %SMOKE_RC% >> "%STATUS%"

echo [%date% %time%] finished >> "%STATUS%"
echo.
echo ============================================================
echo  Offline tests : exit %TEST_RC%    (0 = all passed)
echo  Live checks   : exit %LIVE_RC%    (0 = ok)
echo  Smoke test    : exit %SMOKE_RC%    (0 = ok)
echo ============================================================
echo Reports: out\live-check.md and out\smoke-live\smoke-report.md
echo If anything is not 0, tell Claude "go check it" - the logs are in the out folder.
goto :eof

:fail_python
echo [%time%] FAILED: could not create a virtual environment - is Python 3.11+ installed? See out\venv.log >> "%STATUS%"
echo FAILED: could not create a virtual environment. Is Python 3.11 or newer installed? See out\venv.log
goto :eof
:fail_version
echo [%time%] FAILED: Python 3.11 or newer is required. See out\python-version.log >> "%STATUS%"
echo FAILED: Python 3.11 or newer is required. See out\python-version.log
goto :eof
:fail_pip
echo [%time%] FAILED: dependency installation failed. See out\pip.log >> "%STATUS%"
echo FAILED: dependency installation failed. See out\pip.log
goto :eof
:fail_config
echo [%time%] FAILED: .env configuration problem. See out\preflight.log >> "%STATUS%"
echo.
echo CONFIGURATION PROBLEM in backend\.env:
type out\preflight.log
echo.
echo Fix that line in backend\.env (notepad .env), save it, then run run_live_checks.cmd again.
goto :eof
