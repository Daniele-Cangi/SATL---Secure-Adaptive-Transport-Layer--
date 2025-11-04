# control_plane.py
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import time, hmac, hashlib, json, os
from qkernel.qrand import qstream
from pqc_agility import hybrid_sign

app = FastAPI()

ED_SECRET = os.getenv("SATL_CP_ED_SECRET","ed_secret").encode()
CP_SHARED = os.getenv("SATL_CP_SHARED","ed_secret").encode()

class NodeReg(BaseModel):
    node_id: str
    asn: int
    cc: str
    pub_ep: str
    attest: Dict[str, Any]
    caps: List[str]

class RotationReq(BaseModel):
    client_nonce: str
    profile: str
    want: List[str]

DB_NODES: Dict[str, Dict[str, Any]] = {}

POLICY = {
    "ver": 1,
    "profiles": ["interactive", "blindato"]
}

def entropy_attest(secret: bytes) -> str:
    rng = qstream(b"/attest")
    challenge = rng.bytes(32)
    return hmac.new(secret, challenge, hashlib.sha256).hexdigest()

# add: issue node token at registration
@app.post("/node/register")
def node_register(n: NodeReg):
    DB_NODES[n.node_id] = {
        "asn": n.asn, "cc": n.cc, "pub_ep": n.pub_ep,
        "caps": set(n.caps), "attest": n.attest, "up": True, "health": 0.8,
        "asn_div": 1.0, "cc_div": 1.0
    }
    tok = hmac.new(CP_SHARED, f"{n.node_id}".encode(), hashlib.sha256).hexdigest()
    return {"ok": True, "ts": int(time.time()), "node_token": tok}

# nuovi bin per histogram fitter + profili dinamici
STEALTH_BINS_V1 = {"bins":[300,450,600,800,1000,1200,1500,1800,2048], "cdf":[0.06,0.12,0.22,0.38,0.58,0.77,0.90,0.97,1.0]}

@app.post("/rotate")
def rotate(r: RotationReq):
    pack = {
        "policy": r.profile if r.profile in POLICY["profiles"] else "blindato",
        "ver": POLICY["ver"],
        "bins": STEALTH_BINS_V1 if "stealth_bins_v1" in r.want else None,
        "time_quantum_ms": 20 if r.profile=="blindato" else 100,
        "chaff_base_pps": 50.0 if r.profile=="blindato" else 20.0,
        "mix_base_hz":    6.0 if r.profile=="blindato" else 5.0,
        "rotation_s":     15 if r.profile=="blindato" else 20
    }
    pack["entropy_attestation"] = entropy_attest(ED_SECRET)
    pack["signature"] = hybrid_sign(json.dumps(pack, sort_keys=True).encode(), ed25519_sk=ED_SECRET, pqc_sk=None)
    return pack

@app.get("/nodes/snapshot")
def nodes_snapshot():
    return {"nodes": DB_NODES}