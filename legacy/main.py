"""
Runner CLI: reale (I/O adapter) o research (sim).
Esempi:
  python main.py --mode real --url https://cdn-front.example/upload --profile blindato
  python main.py --mode research --profile interactive
"""
import argparse, time, sys, json, asyncio, requests
from typing import List
from advanced_morphing import TrafficMorpher
from anti_correlation import AntiCorrelationEngine
from satl_config import STEALTH_PROFILES
from qso_layer import QSOClient, QSOServer
from io_adapters import AdaptiveSender
from decoy_engine import DecoyEngine

def synthetic_ingress(n_packets=800, mean_ms=60.0)->List[float]:
    from qkernel.qrand import qstream
    rng=qstream(b"/ingress"); t=0.0; ts=[]
    for _ in range(n_packets):
        t += rng.exp(1.0/(mean_ms/1000.0))
        ts.append(t)
    return ts

def run_research(profile="interactive"):
    print(f"\n=== PROFILE (RESEARCH): {profile} ===")
    payload = b"A"* (256*1024)
    cli, srv = QSOClient(), QSOServer()
    ch = cli.hello()
    resp = srv.respond(ch)
    ok = cli.finish(resp)
    capsule = cli.fte_pack(payload, meta={"p":profile})
    # encode → bytes stream
    wire = ("\n".join(capsule["b"])).encode()
    morpher = TrafficMorpher(profile=profile)
    chunks = morpher.morph(wire)
    egress_times=[]; t0=time.time()
    for item in chunks:
        dt = item[0] if isinstance(item, tuple) else max(0.0, item.ts_due - time.time())
        if not egress_times: egress_times.append(dt)
        else: egress_times.append(egress_times[-1]+dt)
    ingress_times = synthetic_ingress(n_packets=len(egress_times), mean_ms=60.0)
    ev = AntiCorrelationEngine(); m = ev.evaluate(ingress_times, egress_times)
    print("MI:", round(m["mi"] or 0.0, 4), "XCorr:", round(m["xcorr"] or 0.0, 4), "PSD:", m["psd_peaks"])

def run_real(url: str, profile="interactive", user_agent=None, decoy_cfg:str|None=None):
    print(f"\n=== PROFILE (REAL): {profile} -> {url} ===")
    cli, srv = QSOClient(), QSOServer()
    ch = cli.hello()
    resp = srv.respond(ch)
    ok = cli.finish(resp)
    if not ok: print("WARN: handshake fallback")
    # 2) Prepara capsule QSO e passa al morpher
    with open(__file__, "rb") as f:
        data = f.read(128*1024)  # esempio: blocco di bytes qualsiasi
    capsule = cli.fte_pack(data, meta={"p":profile})
    wire = ("\n".join(capsule["b"])).encode()
    morpher = TrafficMorpher(profile=profile)
    chunks = morpher.morph(wire)
    # 3) Adapter di rete reale (browser se disponibile)
    sender = AdaptiveSender(target_url=url, user_agent=user_agent)
    sent=0
    try:
        for item in chunks:
            if isinstance(item, tuple):
                dt, pl = item
                time.sleep(dt)
                ok = sender.send_chunk(pl)
            else:
                ok = sender.send_chunk(item.payload)
            sent += 1 if ok else 0
    finally:
        sender.close()
    print(f"SENT OK: {sent}/{len(chunks)}")
    # Decoy option (se specificato)
    if decoy_cfg:
        snap = requests.get("http://localhost:8000/nodes/snapshot", timeout=5).json()
        cfg  = json.load(open(decoy_cfg,"r"))
        d = DecoyEngine(snap, ratio=cfg["ratio"], nhpp_base=cfg["nhpp_base"], n=cfg["n"], t=cfg["t"])
        print("Running decoys burst...")
        asyncio.run(d.run_window(10.0))

if __name__=="__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["real","research"], default="research")
    ap.add_argument("--url",  type=str, default="https://httpbin.org/post")
    ap.add_argument("--profile", choices=["interactive","blindato"], default="interactive")
    ap.add_argument("--ua", type=str, default=None, help="custom User-Agent (opzionale)")
    ap.add_argument("--decoy", type=str, default=None, help="path decoy_profile.json")
    args = ap.parse_args()
    if args.mode=="research":
        run_research(profile=args.profile)
    else:
        run_real(url=args.url, profile=args.profile, user_agent=args.ua, decoy_cfg=args.decoy)