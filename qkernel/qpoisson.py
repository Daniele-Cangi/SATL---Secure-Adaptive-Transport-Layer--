import math, time
from typing import Callable, List
from .qrand import qstream

def diurnal_rate(base: float, amp: float=0.35) -> float:
    t=time.gmtime(); h=t.tm_hour + t.tm_min/60.0
    return max(0.0, base*(1.0 + amp*math.sin(2*math.pi*(h/24.0-0.25))))

def nhpp_thinning(rate_fn: Callable[[float], float], T: float, max_rate: float=None, label=b"/nhpp") -> List[float]:
    """ Non-homogeneous Poisson via thinning su finestra [0,T] (secondi). """
    rng=qstream(label); t=0.0; times=[]
    M = max_rate if max_rate is not None else max(rate_fn(0.0), 1.0)
    while t < T:
        t += rng.exp(M)  # proposta da Exp(M)
        if t>T: break
        if rng.u01() < rate_fn(t)/max(M,1e-9): times.append(t)
    return times