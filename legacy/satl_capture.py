# satl_capture.py — invia capsule 24h e logga intervalli
import time, json, requests, random
from qso_layer import QSOClient, QSOServer
from satl_proto import Envelope
def run(minutes=60, out="satl.jsonl"):
    cli, srv = QSOClient(), QSOServer(); assert cli.finish(srv.respond(cli.hello()))
    with open(out,"w") as f:
        t0=time.time(); last=None
        while time.time()-t0<minutes*60:
            cap=cli.fte_pack(b"A"*random.randint(32*1024,256*1024), meta={"p":"blindato"})
            env=Envelope(["http://localhost:9000/ingress","http://localhost:9001/ingress"], cap)
            st=time.time(); requests.post(env.route[0], data=env.to_bytes(), timeout=10)
            now=time.time(); dt=(now-st); f.write(json.dumps({"t":int(now),"dt":dt})+"\n"); f.flush()
            time.sleep(random.uniform(0.05,0.2))
if __name__=="__main__": run(60)