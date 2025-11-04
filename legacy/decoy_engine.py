# ===================================
# decoy_engine.py  (NUOVO)
# Genera circuiti "decoy" coordinati (NHPP) con Shamir tag
# ===================================
import time, asyncio, aiohttp, base64, os
from typing import List, Dict, Any
from qkernel.qpoisson import nhpp_thinning
from qkernel.qrand import qstream
from qkernel.qdecoy import shamir_split

class DecoyEngine:
    def __init__(self, nodes_snapshot: Dict[str,Any], ratio: float=0.5, nhpp_base: float=15.0, t:int=2, n:int=3):
        self.nodes = [ {"id":nid, **meta} for nid,meta in nodes_snapshot.get("nodes",{}).items() if meta.get("up",True) ]
        self.ratio = max(0.0,min(0.95, ratio))
        self.base  = max(0.1, nhpp_base)
        self.n, self.t = n, max(2, t)
        self.rng   = qstream(b"/decoy")

    async def run_window(self, seconds: float=10.0):
        if not self.nodes: return 0
        # numero shot in finestra
        times = nhpp_thinning(lambda t: self.base, T=seconds, max_rate=self.base, label=b"/decoy/nhpp")
        payload = os.urandom(2048)  # random blob
        total=0
        async with aiohttp.ClientSession() as s:
            for _ in times:
                if self.rng.u01() > self.ratio:  # skip in base al ratio
                    continue
                shares = shamir_split(payload[:64], n=self.n, t=self.t, label=b"/decoy/shamir")
                # invia shares a n nodi diversi
                for i in range(min(self.n, len(self.nodes))):
                    url = self.nodes[i]["pub_ep"]
                    blob = base64.urlsafe_b64encode(shares[i][1]).decode().encode()
                    try:
                        await s.post(url, data=blob, timeout=5)
                        total += 1
                    except Exception:
                        pass
        return total