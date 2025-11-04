import hmac, hashlib, time, json
from .qrand import qstream, min_entropy_bits

def entropy_attest(secret: bytes=b"ed_secret")->dict:
    seed = qstream(b"/att").bytes(64)
    rep  = {"ts": int(time.time()), "minH": int(min_entropy_bits(seed))}
    tag  = hmac.new(secret, json.dumps(rep, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    return {"rep": rep, "tag": tag}