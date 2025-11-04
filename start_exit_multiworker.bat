@echo off
REM SATL Exit - Multi-worker mode (3 workers)
REM Use this for performance testing with memory backend
set SATL_MODE=performance
set SATL_WINDOW_BACKEND=memory
cd /d C:\Users\dacan\OneDrive\Desktop\SATL2.0
python -m uvicorn forwarder_exit:app --host 0.0.0.0 --port 9002 --workers 4 --http httptools --no-access-log
