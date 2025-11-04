@echo off
REM SATL 3.0 - Start Caddy TLS Reverse Proxy
REM Purpose: Terminate TLS 1.3 for forwarder endpoints
REM Requires: Caddy installed (https://caddyserver.com/download)

echo ======================================================================
echo SATL 3.0 - Starting Caddy TLS Reverse Proxy
echo ======================================================================
echo.
echo TLS endpoints (frontend):
echo   https://localhost:9000  (Guard)
echo   https://localhost:9001  (Middle)
echo   https://localhost:9002  (Exit)
echo.
echo Backend targets (uvicorn HTTP):
echo   http://localhost:19000  (Guard backend)
echo   http://localhost:19001  (Middle backend)
echo   http://localhost:19002  (Exit backend)
echo.
echo Configuration: caddy\Caddyfile
echo ======================================================================
echo.

REM Check if Caddy is installed
where caddy >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Caddy not found in PATH
    echo.
    echo Download Caddy from: https://caddyserver.com/download
    echo Or install via: winget install Caddy.Caddy
    echo.
    pause
    exit /b 1
)

REM Create log directory
if not exist "c:\Users\dacan\OneDrive\Desktop\SATL2.0\logs\caddy" (
    mkdir "c:\Users\dacan\OneDrive\Desktop\SATL2.0\logs\caddy"
)

REM Start Caddy with Caddyfile
cd /d "c:\Users\dacan\OneDrive\Desktop\SATL2.0"

echo [INFO] Starting Caddy server...
echo [INFO] Press Ctrl+C to stop
echo.

caddy run --config caddy\Caddyfile --adapter caddyfile

REM If Caddy exits
echo.
echo [INFO] Caddy stopped
pause
