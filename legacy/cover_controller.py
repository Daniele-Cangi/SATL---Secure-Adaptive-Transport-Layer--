# cover_controller.py
import math, time
def diurnal_cover_pps(base: float, amp: float=0.35)->float:
    # 24h wave (UTC) per imitare variazioni naturali del traffico
    t=time.gmtime(); h=t.tm_hour + t.tm_min/60.0
    return max(0.0, base*(1.0 + amp*math.sin(2*math.pi*(h/24.0-0.25))))