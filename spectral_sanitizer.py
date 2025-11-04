# spectral_sanitizer.py
try:
    import numpy as _np
except Exception:
    _np=None

def deperiodize_intervals(intervals, max_shift_ms=8.0, rng_u01=lambda:0.5):
    if _np is None or len(intervals)<8:  # fallback no-op
        return intervals
    x = _np.asarray(intervals, dtype=float)
    mu, sig = _np.mean(x), _np.std(x)+1e-9
    z = (x-mu)/sig
    shift = (rng_u01()-0.5) * (max_shift_ms/1000.0) * _np.tanh(z)
    y = x + shift
    y[y<=0.0005]=0.0005
    return y.tolist()