# mpc_entropy.py — colletta da peer multipli e fonde
import aiohttp, asyncio, os, hashlib
from typing import List
from qkernel.qrand import _hkdf

PEERS = [p for p in os.getenv("SATL_MPC_PEERS","").split(",") if p]

async def _fetch(url:str, timeout=3):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=timeout) as r:
                return await r.read()
    except Exception:
        return b""

async def mpc_seed(nbytes:int=32)->bytes:
    if not PEERS:  # fallback
        return os.urandom(nbytes)
    outs = await asyncio.gather(*[_fetch(p.strip()) for p in PEERS])
    mix=b""
    for blob in outs:
        if not blob: continue
        mix = hashlib.blake2b((mix+blob), digest_size=32).digest()
    if not mix: mix=os.urandom(32)
    return _hkdf(mix, b"/mpc-seed", outlen=nbytes)