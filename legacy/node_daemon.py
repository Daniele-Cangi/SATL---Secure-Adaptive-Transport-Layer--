# node_daemon.py — PATCH MASSIVO (sostituisci il file)
import asyncio, time, os, json, base64, hashlib, random
from typing import Dict, Any, List, Optional
import aiohttp
from fastapi import FastAPI, Request, Header, HTTPException
import uvicorn

from qso_layer import QSOContext, QSOClient, QSOServer
from multipath_scheduler import MultiPath
from qkernel.qrand import qstream
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from satl_proto import Envelope
from authz import sign_node_header, verify_node_header
from mpc_entropy import mpc_seed

CP_URL   = os.getenv("SATL_CP_URL", "http://control-plane:8000")
NODE_ID  = os.getenv("SATL_NODE_ID", "node-A")
PUB_EP   = os.getenv("SATL_PUB_EP", "http://node-A:9000/ingress")
PROFILE  = os.getenv("SATL_PROFILE", "blindato")
UA       = os.getenv("SATL_UA", "Mozilla/5.0 SATL")
EXIT_URL = os.getenv("SATL_EXIT_URL", "https://httpbin.org/post")  # simulazione exit
METRICS_PORT = int(os.getenv("SATL_METRICS_PORT", "9101"))
HTTP_PORT    = int(os.getenv("SATL_HTTP_PORT", "9000"))
RATE_QPS     = float(os.getenv("SATL_RATE_QPS","8.0"))

# Prometheus
C_IN_PKTS   = Counter("satl_ingress_packets","Ingress packets")
C_OUT_PKTS  = Counter("satl_egress_packets","Egress packets")
H_DT        = Histogram("satl_send_delay_s","Send delay")
G_HEALTH    = Gauge("satl_node_health","Node health")
G_QUEUE     = Gauge("satl_queue_depth","Morph queue depth")
C_DROP_RATE = Counter("satl_rate_drops","Rate limited drops")
C_HEAL      = Counter("satl_circuit_heal","Circuit heals")

app = FastAPI()
rng = qstream(b"/node")

# stato runtime (rotation pack applicato)
RUNTIME = {
    "time_quantum_ms": 20 if PROFILE=="blindato" else 100,
    "chaff_base_pps":  50.0 if PROFILE=="blindato" else 20.0,
    "mix_base_hz":     6.0 if PROFILE=="blindato" else 5.0,
    "rotation_s":      15 if PROFILE=="blindato" else 20,
    "bins": None
}

# rate limiter semplice (token bucket per IP)
_BUCKETS: Dict[str, Dict[str,float]] = {}

def _allow(ip:str)->bool:
    b=_BUCKETS.setdefault(ip, {"tokens": RATE_QPS, "ts": time.time()})
    now=time.time(); regen=(now-b["ts"])*RATE_QPS
    b["tokens"]=min(RATE_QPS, b["tokens"]+regen); b["ts"]=now
    if b["tokens"]>=1.0: b["tokens"]-=1.0; return True
    return False

# audit log con hash chaining (tamper-evident)
_AUDIT_LAST=b"\x00"*32
def audit(event:str, **kv):
    global _AUDIT_LAST
    rec={"ts":int(time.time()),"node":NODE_ID,"ev":event,**kv}
    raw=json.dumps(rec,sort_keys=True).encode()
    h=hashlib.blake2b(_AUDIT_LAST+raw,digest_size=32).digest(); _AUDIT_LAST=h
    line=json.dumps({**rec,"chain":h.hex()})
    print(line, flush=True)

# snapshot nodi
NODES_SNAPSHOT: Dict[str,Any] = {"nodes":{}}
async def fetch_nodes_snapshot():
    global NODES_SNAPSHOT
    async with aiohttp.ClientSession() as s:
        while True:
            try:
                async with s.get(f"{CP_URL}/nodes/snapshot", timeout=10) as r:
                    NODES_SNAPSHOT = await r.json()
            except Exception:
                pass
            await asyncio.sleep(15)

async def self_register():
    reg={"node_id":NODE_ID,"asn":64512,"cc":"EU","pub_ep":PUB_EP,"attest":{"kind":"entropy","ok":True},"caps":["qso","mix","pqc"]}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{CP_URL}/node/register", json=reg, timeout=10) as r:
            if r.status//100==2:
                body=await r.json()
                os.environ["SATL_NODE_TOKEN"]=body.get("node_token","")
                return True
    return False

async def apply_rotation():
    async with aiohttp.ClientSession() as s:
        while True:
            try:
                req={"client_nonce": base64.urlsafe_b64encode(await mpc_seed(16)).decode(),"profile":PROFILE,"want":["stealth_bins_v1"]}
                async with s.post(f"{CP_URL}/rotate", json=req, timeout=10) as r:
                    pack=await r.json()
                    RUNTIME["time_quantum_ms"]=pack.get("time_quantum_ms",RUNTIME["time_quantum_ms"])
                    RUNTIME["chaff_base_pps"]=pack.get("chaff_base_pps",RUNTIME["chaff_base_pps"])
                    RUNTIME["mix_base_hz"]=pack.get("mix_base_hz",RUNTIME["mix_base_hz"])
                    RUNTIME["rotation_s"]=pack.get("rotation_s",RUNTIME["rotation_s"])
                    RUNTIME["bins"]=pack.get("bins", RUNTIME["bins"])
                    audit("rotation.apply", pack_ver=pack.get("ver",0))
            except Exception:
                pass
            await asyncio.sleep(30)

async def _post(session:aiohttp.ClientSession, url:str, payload:bytes, hdr:Dict[str,str], timeout=8):
    try:
        async with session.post(url, data=payload, headers=hdr, timeout=timeout) as r:
            return r.status//100 == 2
    except Exception:
        return False

async def forward_next(env:Envelope, session:aiohttp.ClientSession)->bool:
    """ Hop → hop: firma header, ritenta e risana circuito se serve. """
    route, hop = env.route, env.hop
    if hop+1 < len(route):
        next_url = route[hop+1]
        hdr={"User-Agent":UA, "X-SATL-Auth": sign_node_header(NODE_ID)}
        ok = await _post(session, next_url, env.__class__.to_bytes(env.__class__(route, env.cap, hop+1, env.meta)), hdr)
        if ok: return True
        # healing: sostituisci next con altro nodo e ritenta
        C_HEAL.inc(); audit("circuit.heal", failed=next_url)
        candidates=[meta["pub_ep"] for nid,meta in NODES_SNAPSHOT.get("nodes",{}).items() if meta.get("up",True) and meta.get("pub_ep")!=PUB_EP]
        if candidates:
            alt=random.choice(candidates)
            env.hop=hop; env.route[hop+1]=alt
            return await _post(session, alt, env.to_bytes(), hdr)
        return False
    else:
        # EXIT: simula destinazione finale
        hdr={"User-Agent":UA}
        return await _post(session, EXIT_URL, json.dumps(env.cap).encode(), hdr)

@app.post("/ingress")
async def ingress(request: Request, x_satl_auth: Optional[str]=Header(None)):
    ip=request.client.host if request.client else "0.0.0.0"
    if not _allow(ip):
        C_DROP_RATE.inc(); raise HTTPException(429,"rate limited")
    if not x_satl_auth or not verify_node_header(x_satl_auth):
        # prima hop dal client non ha header → consenti ma logga
        audit("ingress.noauth", ip=ip)
    body = await request.body(); C_IN_PKTS.inc(); G_QUEUE.set(1)
    try:
        # prova come Envelope; se fallisce, accetta raw (compat)
        try:
            env = Envelope.from_bytes(body)
        except Exception:
            # raw client chunk: crea env 1-hop -> EXIT
            cap = {"b":[base64.urlsafe_b64encode(body).decode()],"iv":base64.urlsafe_b64encode(os.urandom(16)).decode()}
            env = Envelope([PUB_EP], cap, hop=0, meta={"ttl":30,"ts":int(time.time())})
        async with aiohttp.ClientSession() as s:
            t0=time.time()
            ok = await forward_next(env, s)
            H_DT.observe(max(0.0, time.time()-t0))
            if ok: C_OUT_PKTS.inc(); return {"ok":True}
            raise HTTPException(502,"forward failed")
    finally:
        G_QUEUE.set(0)

async def main():
    start_http_server(METRICS_PORT); G_HEALTH.set(0.85)
    await self_register()
    asyncio.create_task(fetch_nodes_snapshot())
    asyncio.create_task(apply_rotation())
    config = uvicorn.Config(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())