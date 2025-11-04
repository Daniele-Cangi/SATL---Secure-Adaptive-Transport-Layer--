# multipath_scheduler.py
import hashlib, time, random
from typing import List, Dict
from qkernel.qrand import qstream
from qkernel.qdecoy import shamir_split

class MultiPath:
    def __init__(self, nodes: List[Dict], rotation_s: int=20, shards:int=4, label=b"/mpath"):
        self.nodes=nodes; self.rot=rotation_s; self.shards=shards
        self._rng=qstream(label)
    def _score(self, n:Dict)->float:
        return 0.5*n.get("health",0.5)+0.25*n.get("asn_div",0.5)+0.25*n.get("cc_div",0.5)
    def _weighted(self, k:int)->List[Dict]:
        w=[(self._score(n),n) for n in self.nodes if n.get("up",True)]
        if not w: return []
        tot=sum(max(x,1e-6) for x,_ in w); pick=[]
        for _ in range(min(k,len(w))):
            r=self._rng.u01()*tot; acc=0
            for x,n in w:
                acc+=max(x,1e-6)
                if acc>=r: pick.append(n); break
        return pick
    def assign(self, flow_id: bytes, decoys:int=0, threshold:int=0)->List[Dict]:
        epoch=int(time.time()//self.rot)
        random.seed(hashlib.blake2b(flow_id+epoch.to_bytes(8,"big"),digest_size=8).digest())
        k=max(1,self.shards); sel=self._weighted(k)
        random.shuffle(sel)
        if decoys>0 and threshold>0:
            _ = shamir_split(flow_id[:16] if len(flow_id)>=16 else flow_id.ljust(16,b"\x01"),
                             n=decoys, t=max(2,threshold))
            # shares come payload indistinguibile (mai header)
        return sel