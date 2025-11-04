@echo off
REM USARE SOLO PER DEMO. Per test usare i 3 .bat separati.
REM Start all 3 SATL forwarder nodes in separate windows

echo ======================================================================
echo SATL 3.0 - Starting Forwarder Nodes
echo ======================================================================
echo.
echo Starting 3 forwarder nodes in separate windows:
echo   - Guard:  localhost:9000 (metrics: 10000)
echo   - Middle: localhost:9001 (metrics: 10001)
echo   - Exit:   localhost:9002 (metrics: 10002)
echo.
echo Close windows or press Ctrl+C in each to stop.
echo ======================================================================
echo.

REM Start Guard node
start "SATL Guard Node" cmd /k "python satl_forwarder_daemon.py --role guard --port 9000"

REM Wait a bit before starting next node
timeout /t 2 /nobreak > nul

REM Start Middle node
start "SATL Middle Node" cmd /k "python satl_forwarder_daemon.py --role middle --port 9001"

REM Wait a bit before starting next node
timeout /t 2 /nobreak > nul

REM Start Exit node
start "SATL Exit Node" cmd /k "python satl_forwarder_daemon.py --role exit --port 9002"

echo.
echo ======================================================================
echo All forwarder nodes started!
echo.
echo Wait 5 seconds for nodes to initialize, then run tests:
echo   python test_smoke.py
echo   python test_load.py
echo ======================================================================
echo.

timeout /t 5 /nobreak
