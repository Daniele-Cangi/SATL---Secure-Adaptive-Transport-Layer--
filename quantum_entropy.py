# quantum_entropy.py
import os, hmac, hashlib, time, struct, math
from typing import Dict, Tuple

def _approx_min_entropy(bs: bytes) -> float:
    from collections import Counter
    c = Counter(bs); maxp = max(c.values())/len(bs)
    return -math.log2(maxp+1e-12)

def _hkdf(seed: bytes, info: bytes, outlen=32) -> bytes:
    prk = hmac.new(b"\x00"*32, seed, hashlib.sha256).digest()
    return hmac.new(prk, info, hashlib.sha256).digest()[:outlen]

def get_seed(n_bytes: int = 32) -> Tuple[bytes, Dict]:
    pools = [os.urandom(64)]
    # TODO (opzionale): append QRNG hardware/remoto qui
    raw  = b"".join(pools) + struct.pack(">Q", time.time_ns())
    salt = hashlib.sha256(raw).digest()
    seed = hmac.new(salt, b"SATL-QRNG-SEED", hashlib.sha256).digest()[:n_bytes]
    rep  = {"min_entropy_bits": _approx_min_entropy(raw),
            "len_raw": len(raw), "seed_len": len(seed), "ts": time.time()}
    return seed, rep

class HmacDRBG:
    def __init__(self, seed: bytes):
        self.K = b"\x00"*32; self.V = b"\x01"*32
        self._update(seed)
    def _h(self, k,d): return hmac.new(k,d,hashlib.sha256).digest()
    def _update(self, pd=b""):
        self.K=self._h(self.K, self.V+b"\x00"+pd); self.V=self._h(self.K,self.V)
        if pd: self.K=self._h(self.K,self.V+b"\x01"+pd); self.V=self._h(self.K,self.V)
    def bytes(self, n): 
        out=b""
        # noqa
        while len(out)<n: 
            self.V=self._h(self.K,self.V); 
            out+=self.V
        return out[:n]
    def u01(self)->float:
        x=int.from_bytes(self.bytes(8),"big"); return (x+1)/(2**64+1)
    def exp(self, rate: float)->float:
        u=max(self.u01(),1e-12); return -math.log(u)/max(rate,1e-9)

def qrng_stream(label: bytes=b"")->HmacDRBG:
    seed,_=get_seed(32); return HmacDRBG(_hkdf(seed,label or b"SATL"))