@echo off
REM SATL 3.0 - Start Forwarders (TLS Mode)
REM Purpose: Start forwarders on backend ports (19000/19001/19002)
REM         Caddy will handle TLS termination on frontend (9000/9001/9002)

echo ======================================================================
echo SATL 3.0 - Starting Forwarders (TLS Backend Mode)
echo ======================================================================
echo.
echo Backend ports (HTTP - behind Caddy):
echo   Guard:  localhost:19000 (metrics: 10000)
echo   Middle: localhost:19001 (metrics: 10001)
echo   Exit:   localhost:19002 (metrics: 10002)
echo.
echo Frontend TLS endpoints (via Caddy):
echo   https://localhost:9000  (Guard)
echo   https://localhost:9001  (Middle)
echo   https://localhost:9002  (Exit)
echo.
echo IMPORTANT: Start Caddy FIRST with start_caddy.bat
echo ======================================================================
echo.

REM Environment configuration
set SATL_MODE=performance
set SATL_ALLOW_COMPAT=1
set SATL_TLS_MODE=backend

REM Start Guard node (backend port 19000)
start "SATL Guard (TLS Backend)" cmd /k "cd /d c:\Users\dacan\OneDrive\Desktop\SATL2.0 && python -m uvicorn forwarder_guard:app --host 0.0.0.0 --port 19000 --log-level warning"

REM Wait before starting next node
timeout /t 2 /nobreak > nul

REM Start Middle node (backend port 19001)
start "SATL Middle (TLS Backend)" cmd /k "cd /d c:\Users\dacan\OneDrive\Desktop\SATL2.0 && python -m uvicorn forwarder_middle:app --host 0.0.0.0 --port 19001 --log-level warning"

REM Wait before starting next node
timeout /t 2 /nobreak > nul

REM Start Exit node (backend port 19002)
start "SATL Exit (TLS Backend)" cmd /k "cd /d c:\Users\dacan\OneDrive\Desktop\SATL2.0 && python -m uvicorn forwarder_exit:app --host 0.0.0.0 --port 19002 --log-level warning"

echo.
echo ======================================================================
echo All forwarder backend nodes started!
echo.
echo Next steps:
echo   1. Ensure Caddy is running (start_caddy.bat)
echo   2. Test TLS: curl -vk https://localhost:9000/health
echo   3. Verify TLS 1.3: Look for "TLSv1.3" in curl output
echo ======================================================================
echo.

timeout /t 5 /nobreak
