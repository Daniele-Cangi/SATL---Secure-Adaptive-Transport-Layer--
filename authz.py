# authz.py — HMAC node<->node firmato dal CP (semplice, veloce)
import hmac, hashlib, time, os
CP_SECRET = os.getenv("SATL_CP_SHARED","ed_secret").encode()

def sign_node_header(node_id:str)->str:
    ts=str(int(time.time()))
    sig=hmac.new(CP_SECRET, f"{node_id}|{ts}".encode(), hashlib.sha256).hexdigest()
    return f"{node_id}:{ts}:{sig}"

def verify_node_header(h:str, skew_s:int=90)->bool:
    try:
        nid,ts,sig=h.split(":"); ts=int(ts)
        if abs(time.time()-ts)>skew_s: return False
        exp=hmac.new(CP_SECRET, f"{nid}|{ts}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(exp, sig)
    except Exception:
        return False