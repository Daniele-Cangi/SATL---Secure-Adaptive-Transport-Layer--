# client_circuit.py — costruisce un percorso K hops e invia
import requests, json, time, random
from typing import List
from satl_proto import Envelope
from qso_layer import QSOClient, QSOServer

def build_route(nodes_snapshot:dict, k:int=3, avoid:str|None=None)->List[str]:
    eps=[meta["pub_ep"] for nid,meta in nodes_snapshot.get("nodes",{}).items() if meta.get("up",True)]
    if avoid: eps=[e for e in eps if e!=avoid]
    random.shuffle(eps); return eps[:max(1,min(k,len(eps)))]

def send_capsule(route:List[str], cap:dict):
    env=Envelope(route, cap, hop=0, meta={"ttl":60,"ts":int(time.time())})
    r=requests.post(route[0], data=env.to_bytes(), timeout=10)
    return r.status_code//100==2

if __name__=="__main__":
    snap=requests.get("http://localhost:8000/nodes/snapshot",timeout=5).json()
    cli, srv = QSOClient(), QSOServer()
    assert cli.finish(srv.respond(cli.hello()))
    cap=cli.fte_pack(b"A"*(256*1024), meta={"p":"blindato"})
    route=build_route(snap, k=3, avoid="http://node-A:9000/ingress")
    ok=send_capsule(route, cap)
    print("OK:",ok," route:",route)