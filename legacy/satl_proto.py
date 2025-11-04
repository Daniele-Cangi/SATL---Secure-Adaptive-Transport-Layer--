# satl_proto.py  — envelope onion-lite per hop-by-hop
import json, base64, time
from typing import List, Dict, Any

class Envelope:
    """
    route: lista di endpoint 'http(s)://host:port/ingress'
    hop: indice hop corrente
    cap: capsule QSO (fte_pack)
    meta: opz. {"flow":"id","ttl":45,"ts":epoch}
    """
    def __init__(self, route: List[str], cap: Dict[str,Any], hop:int=0, meta:Dict[str,Any]|None=None):
        self.route, self.cap, self.hop = route, cap, hop
        self.meta = meta or {"ttl": 45, "ts": int(time.time())}
    def to_bytes(self)->bytes:
        return json.dumps({"r":self.route,"h":self.hop,"c":self.cap,"m":self.meta}, separators=(",",":")).encode()
    @staticmethod
    def from_bytes(b: bytes)->"Envelope":
        o=json.loads(b.decode()); e=Envelope(o["r"], o["c"], o["h"], o.get("m",{})); return e