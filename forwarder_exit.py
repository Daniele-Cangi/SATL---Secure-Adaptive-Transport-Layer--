import uvicorn
from prometheus_exporter import get_exporter
import satl_forwarder_daemon as core
from satl_forwarder_daemon import app

# bind exit to the REAL module globals
if core.forwarder is None:
    core.forwarder = core.SATLForwarder(role="exit", port=9002)

if core.prom is None:
    core.prom = get_exporter(port=10002, role="exit")
    core.prom.start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9002, log_level="info")
