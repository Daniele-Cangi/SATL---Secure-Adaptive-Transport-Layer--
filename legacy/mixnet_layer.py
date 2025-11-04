# mixnet_layer.py
import time, heapq
from typing import List
from qkernel.qrand import qstream
from qkernel.qpoisson import diurnal_rate, nhpp_thinning

class MixPacket:
    __slots__=("ts_due","payload","egress_hint","is_cover")
    def __init__(self, ts_due:float, payload:bytes, egress_hint:str, is_cover:bool):
        self.ts_due, self.payload, self.egress_hint, self.is_cover = ts_due,payload,egress_hint,is_cover
    def __lt__(self, other): return self.ts_due<other.ts_due

class PoissonMix:
    def __init__(self, base_rate_hz: float=5.0, cover_pps: float=20.0, label=b"/mix"):
        self._rng = qstream(label)
        self._Q: List[MixPacket]=[]
        self._base = max(base_rate_hz, 0.1)
        self._cover_base = max(cover_pps, 0.0)
        self._last_cover = time.time()

    def _draw_delay(self)->float:
        d = self._rng.exp(self._base)
        return max(d, 0.02)

    def ingest(self, payload: bytes, egress_hint: str="auto"):
        ts = time.time() + self._draw_delay()
        heapq.heappush(self._Q, MixPacket(ts, payload, egress_hint, False))

    def pump_cover(self):
        now = time.time()
        if self._cover_base<=0: return
        rate = diurnal_rate(self._cover_base, 0.35)
        dt = max(0.0, now - self._last_cover)
        cover_times = nhpp_thinning(lambda t: rate, T=dt, max_rate=rate or 1.0, label=b"/cover")
        for _ in cover_times:
            ts = now + self._draw_delay()
            pl = b"\x00" * 64
            heapq.heappush(self._Q, MixPacket(ts, pl, "auto", True))
        if cover_times: self._last_cover = now

    def due(self)->List[MixPacket]:
        now=time.time(); out=[]
        while self._Q and self._Q[0].ts_due <= now:
            out.append(heapq.heappop(self._Q))
        return out