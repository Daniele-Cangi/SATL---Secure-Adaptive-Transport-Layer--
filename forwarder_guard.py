import os
import uvicorn

# Force performance mode for guard (for test_performance_bare.py)
os.environ.setdefault('SATL_MODE', 'performance')

from prometheus_exporter import get_exporter
import satl_forwarder_daemon as core
from satl_forwarder_daemon import app

# bind guard to the REAL module globals
if core.forwarder is None:
    core.forwarder = core.SATLForwarder(role="guard", port=9000)

if core.prom is None:
    core.prom = get_exporter(port=10000, role="guard")
    core.prom.start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")
