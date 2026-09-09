@echo off
rem ---------------------------------------------------------------------------
rem  AcordBank - workstation readiness check
rem
rem  Just double-click this file. It opens a window, runs the check and keeps
rem  the window open at the end so you can read the result.
rem
rem  Nothing is installed and nothing is changed on this machine.
rem ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

if not exist "%~dp0AcordBank-EnvCheck.ps1" (
    echo.
    echo   ERROR: AcordBank-EnvCheck.ps1 was not found next to this file.
    echo   Please keep both files in the same folder and try again.
    echo.
    pause
    exit /b 1
)

powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0AcordBank-EnvCheck.ps1" %*

if errorlevel 1 (
    echo.
    echo   The check did not finish cleanly.
    echo.
    echo   If the message above mentions "running scripts is disabled" or
    echo   execution policy, then script execution is enforced by group policy
    echo   on this machine. That is a decision for your IT team - please ask
    echo   them to run the check, or tell us and we will send the same checks
    echo   as individual commands you can paste one by one.
    echo.
    echo   Otherwise, please send us the text above.
)

echo.
echo   Press any key to close this window.
pause > nul
endlocal
