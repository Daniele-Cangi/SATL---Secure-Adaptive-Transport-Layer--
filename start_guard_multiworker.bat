@echo off
REM SATL Guard - Multi-worker mode (3 workers)
REM Use this for performance testing with memory backend
set SATL_MODE=performance
set SATL_WINDOW_BACKEND=memory
cd /d C:\Users\dacan\OneDrive\Desktop\SATL2.0
python -m uvicorn forwarder_guard:app --host 0.0.0.0 --port 9000 --workers 3 --http httptools --no-access-log
