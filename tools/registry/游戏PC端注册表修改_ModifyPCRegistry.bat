@echo off
setlocal

REM Check for administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    set "ARGS=%*"
    if defined ARGS (
        powershell.exe -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    ) else (
        powershell.exe -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    )
    exit /b %errorlevel%
)

REM Locate the PowerShell script in the same directory as this BAT.
set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%ModifyPCRegistry.ps1"

if not exist "%PS_SCRIPT%" (
    echo PowerShell script not found: %PS_SCRIPT%
    exit /b 1
)

REM Pass all user-provided arguments to the PowerShell script.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo PowerShell script execution failed with exit code: %EXIT_CODE%
) else (
    echo PowerShell script execution completed successfully.
)

exit /b %EXIT_CODE%

