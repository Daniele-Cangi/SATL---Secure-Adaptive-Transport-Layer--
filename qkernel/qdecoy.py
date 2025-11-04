from typing import List, Tuple
from .qrand import qstream

_PRIM = 0x11b  # AES poly per GF(2^8)

def _gf_mul(a,b):
    p=0
    for _ in range(8):
        if b & 1: p ^= a
        hi = a & 0x80
        a = ((a<<1) & 0xFF)
        if hi: a ^= _PRIM
        b >>= 1
    return p

def _poly_eval(coeffs: List[int], x: int) -> int:
    y=0
    for c in reversed(coeffs):
        y=_gf_mul(y,x) ^ c
    return y

def shamir_split(secret: bytes, n: int, t: int, label=b"/shamir") -> List[Tuple[int, bytes]]:
    """ t-of-n sharing byte-wise su GF(2^8). """
    assert 1 < t <= n <= 255
    rng=qstream(label)
    shares=[bytearray() for _ in range(n)]
    for sb in secret:
        coeffs=[sb] + [int(rng.u01()*255) for _ in range(t-1)]
        for i in range(1, n+1):
            shares[i-1].append(_poly_eval(coeffs, i))
    return [(i+1, bytes(sh)) for i,sh in enumerate(shares)]

def shamir_join(shares: List[Tuple[int, bytes]], t: int) -> bytes:
    """ Ricomposizione t-of-n (Lagrange) """
    assert len(shares)>=t
    xs=[x for x,_ in shares[:t]]
    L=[]
    for j,xj in enumerate(xs):
        num=1; den=1
        for m,xm in enumerate(xs):
            if m==j: continue
            num=_gf_mul(num, xm)
            den=_gf_mul(den, xm ^ xj)
        L.append(_gf_mul(num, den))
    out=bytearray(len(shares[0][1]))
    for bpos in range(len(out)):
        acc=0
        for j,(xj,buf) in enumerate(shares[:t]):
            acc ^= _gf_mul(L[j], buf[bpos])
        out[bpos]=acc
    return bytes(out)