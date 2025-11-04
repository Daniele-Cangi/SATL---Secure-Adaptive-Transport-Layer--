import os, hmac, hashlib, time, math, struct
from typing import Tuple, Dict

def _hkdf(seed: bytes, info: bytes, outlen=32) -> bytes:
    prk = hmac.new(b"\x00"*32, seed, hashlib.sha256).digest()
    return hmac.new(prk, info, hashlib.sha256).digest()[:outlen]

def min_entropy_bits(bs: bytes) -> float:
    from collections import Counter
    c=Counter(bs); m=max(c.values())/max(1,len(bs))
    return -math.log2(m+1e-12)

def _gather() -> bytes:
    pools=[os.urandom(64), struct.pack(">Q", time.time_ns())]
    # Hook opzionale per hardware QRNG: setta SATL_QRNG_HOOK="mod.fn" che restituisce bytes
    hook=os.getenv("SATL_QRNG_HOOK","")
    if hook:
        try:
            mod,fn=hook.rsplit(".",1); h=getattr(__import__(mod,fromlist=[fn]), fn)
            extra=h()
            if isinstance(extra,(bytes,bytearray)) and len(extra)>=32: pools.append(extra)
        except Exception:
            pass
    raw=b"".join(pools)
    salt=hashlib.sha256(raw).digest()
    return hmac.new(salt, b"Q-LAMBDA-SEED", hashlib.sha256).digest()

class HmacDRBG:
    def __init__(self, seed: bytes):
        self.K=b"\x00"*32; self.V=b"\x01"*32
        self._upd(seed)
    def _h(self,k,d): return hmac.new(k,d,hashlib.sha256).digest()
    def _upd(self, pd=b""):
        self.K=self._h(self.K, self.V+b"\x00"+pd); self.V=self._h(self.K,self.V)
        if pd:
            self.K=self._h(self.K, self.V+b"\x01"+pd); self.V=self._h(self.K,self.V)
    def bytes(self,n:int)->bytes:
        out=b""
        while len(out)<n:
            self.V=self._h(self.K,self.V); out+=self.V
        return out[:n]
    def u01(self)->float:
        x=int.from_bytes(self.bytes(8),"big")
        return (x+1)/(2**64+1)
    def exp(self, rate: float)->float:
        u=max(self.u01(),1e-12); return -math.log(u)/max(rate,1e-9)
    def normal(self, mu=0.0, sigma=1.0)->float:
        # Box-Muller
        u1=max(self.u01(),1e-12); u2=self.u01()
        z=math.sqrt(-2.0*math.log(u1))*math.cos(2*math.pi*u2)
        return mu + sigma*z
    def discrete_gaussian(self, sigma: float)->int:
        return int(round(self.normal(0.0, sigma)))

def qstream(label: bytes=b"") -> HmacDRBG:
    seed=_hkdf(_gather(), label or b"Q-LAMBDA")
    return HmacDRBG(seed)