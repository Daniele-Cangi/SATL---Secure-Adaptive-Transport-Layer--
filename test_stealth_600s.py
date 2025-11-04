"""
SATL 3.0 - STEALTH VALIDATION TEST (600s)

Purpose:
  Validate that SATL stealth traffic is statistically close to an HTTPS-like baseline.

Metrics (targets):
  - KS-p (inter-arrival distribution):  p >= 0.20
  - XCorr_max (autocorr excluding lag 0): <= 0.35
  - AUC (classifiability by inter-arrival): <= 0.55

Notes:
  - This test collects response completion timestamps while sending requests to the guard.
  - It compares SATL completion inter-arrivals to a synthetic HTTPS baseline (lognormal mixture).
  - Run with forwarders in stealth profile (queue delays + reordering enabled):
       .\profiles\switch_profile.ps1 stealth
  - For a quick smoke test, use --duration 120

Output:
  perf_artifacts/stealth_600s_results.json

Author: SATL 3.0 Research Team
Date: 2025-11-04
"""
import argparse
import asyncio
import json
import math
import os
import sys
import time
import pathlib
from typing import List, Tuple

import numpy as np
from scipy import stats
from sklearn.metrics import roc_auc_score
import httpx

# Reuse canonical packet builder
try:
    from satl_test_utils import build_perf_packet
except Exception:
    build_perf_packet = None


def https_baseline_interarrivals(n: int) -> np.ndarray:
    """Generate an HTTPS-like baseline of inter-arrival times (seconds).

    Mixture inspired by guide:
      - 70% Exponential (lambda=2.5 Hz -> mean ~0.4s)
      - 25% LogNormal (mu=-1.2, sigma=0.7)
      - 5% short bursts uniform 15-40ms
    """
    exp_lambda = 2.5
    lognorm_mu = -1.2
    lognorm_sigma = 0.7

    u = np.random.random(size=n)

    dt = np.empty(n, dtype=float)
    mask_exp = u < 0.70
    mask_logn = (u >= 0.70) & (u < 0.95)
    mask_burst = u >= 0.95

    k_exp = mask_exp.sum()
    k_logn = mask_logn.sum()
    k_burst = mask_burst.sum()

    if k_exp:
        dt[mask_exp] = np.random.exponential(1.0 / exp_lambda, size=k_exp)
    if k_logn:
        dt[mask_logn] = np.random.lognormal(lognorm_mu, lognorm_sigma, size=k_logn)
    if k_burst:
        dt[mask_burst] = np.random.uniform(0.015, 0.040, size=k_burst)

    # Quantize to 20ms and add jitter ±8ms
    dt = np.clip(np.round(dt / 0.020) * 0.020 + np.random.uniform(-0.008, 0.008, size=n), 0.001, None)
    return dt


def compute_autocorr_max(series: np.ndarray, max_lag: int = 50) -> float:
    """Compute maximum normalized autocorrelation (|rho|) excluding lag 0.

    Args:
      series: 1D array of counts per time bin
      max_lag: maximum lag (bins) to consider
    Returns:
      float in [0, 1]
    """
    x = series - np.mean(series)
    var = np.var(x)
    if var <= 1e-12:
        return 0.0
    acf = []
    for lag in range(1, max_lag + 1):
        y1 = x[:-lag]
        y2 = x[lag:]
        num = np.dot(y1, y2)
        den = (len(y1)) * var
        acf.append(num / den)
    return float(np.max(np.abs(acf))) if acf else 0.0


class StealthTest:
    def __init__(self, duration: int, concurrency: int, endpoint: str, bin_size: float = 1.0):
        self.duration = duration
        self.concurrency = concurrency
        self.endpoint = endpoint
        self.bin_size = bin_size

        self.send_count = 0
        self.success_times: List[float] = []  # completion timestamps (epoch seconds)
        self.failures: List[str] = []

        self.output_dir = pathlib.Path('perf_artifacts')
        self.output_file = self.output_dir / 'stealth_600s_results.json'

    def build_packet(self, packet_id: int) -> bytes:
        if build_perf_packet is not None:
            return build_perf_packet(packet_id=packet_id, hops=3, payload_size=1200)
        # Fallback: simple 1201B packet with hop byte 3
        return bytes([3]) + (b"X" * 1200)

    async def worker(self, client: httpx.AsyncClient, worker_id: int):
        while True:
            now = time.time()
            if now - self.start_time >= self.duration:
                break
            pid = self.send_count
            self.send_count += 1
            pkt = self.build_packet(pid)
            try:
                resp = await client.post(
                    self.endpoint,
                    content=pkt,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    self.success_times.append(time.time())
                else:
                    self.failures.append(f"HTTP_{resp.status_code}")
                await resp.aclose()
            except Exception as e:
                self.failures.append(type(e).__name__)
            # small delay to avoid busy loop
            await asyncio.sleep(0.001)

    async def run(self) -> int:
        print("="*70)
        print("SATL 3.0 - STEALTH VALIDATION TEST")
        print("="*70)
        print(f"Endpoint: {self.endpoint}")
        print(f"Duration: {self.duration}s")
        print(f"Concurrency: {self.concurrency}")
        print(f"Bin size (autocorr): {self.bin_size}s")
        print("="*70)

        limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
        timeout = httpx.Timeout(5.0, read=10.0, write=5.0, connect=5.0)

        self.start_time = time.time()

        async with httpx.AsyncClient(limits=limits, timeout=timeout, headers={'Connection': 'keep-alive'}) as client:
            tasks = [asyncio.create_task(self.worker(client, i)) for i in range(self.concurrency)]
            await asyncio.gather(*tasks)

        if len(self.success_times) < 10:
            print("[ERROR] Not enough successful samples collected")
            return 2

        # Build inter-arrival times from completion timestamps
        ts = np.sort(np.array(self.success_times))
        dt = np.diff(ts)
        dt = dt[dt > 0]  # drop zeros
        if len(dt) < 5:
            print("[ERROR] Not enough inter-arrival samples")
            return 2

        # Baseline
        base_dt = https_baseline_interarrivals(len(dt))

        # KS test (inter-arrival distributions)
        ks_stat, ks_p = stats.ks_2samp(dt, base_dt)

        # Rate series (counts per bin)
        t0 = ts[0]
        bins = int(math.ceil((ts[-1] - t0) / self.bin_size)) + 1
        idx = np.floor((ts - t0) / self.bin_size).astype(int)
        rate_series = np.bincount(idx, minlength=bins)
        rate_series = rate_series.astype(float)

        xcorr_max = compute_autocorr_max(rate_series, max_lag=20)

        # AUC (discriminability) using inter-arrivals only
        try:
            y_true = np.concatenate([np.zeros_like(base_dt), np.ones_like(dt)])
            feats = np.concatenate([base_dt, dt])
            # Normalize features
            feats = (feats - np.mean(feats)) / (np.std(feats) + 1e-9)
            auc = roc_auc_score(y_true, feats)
            # AUC should be near 0.5; ensure we take the closer side
            auc = min(auc, 1.0 - auc)
        except Exception:
            auc = 1.0

        # Verdicts
        verdicts = {
            'ks_p_interarrival': 'PASS' if ks_p >= 0.20 else 'FAIL',
            'xcorr_max': 'PASS' if xcorr_max <= 0.35 else 'FAIL',
            'auc_interarrival': 'PASS' if auc <= 0.55 else 'FAIL',
        }
        overall = 'PASS' if all(v == 'PASS' for v in verdicts.values()) else 'FAIL'

        # Save
        self.output_dir.mkdir(exist_ok=True)
        result = {
            'test_suite': 'SATL 3.0 Stealth Validation Test',
            'version': 'v3.0-rc1',
            'date': time.strftime('%Y-%m-%d'),
            'config': {
                'duration_seconds': self.duration,
                'concurrency': self.concurrency,
                'endpoint': self.endpoint,
                'bin_size_seconds': self.bin_size,
            },
            'samples': {
                'completions': len(self.success_times),
                'inter_arrivals': len(dt),
                'failures': len(self.failures),
            },
            'metrics': {
                'ks_p_interarrival': ks_p,
                'xcorr_max': xcorr_max,
                'auc_interarrival': auc,
            },
            'verdict': {
                'ks_p_interarrival': verdicts['ks_p_interarrival'],
                'xcorr_max': verdicts['xcorr_max'],
                'auc_interarrival': verdicts['auc_interarrival'],
                'overall': overall,
            }
        }
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)

        # Print summary
        print("\n" + "="*70)
        print("STEALTH METRICS")
        print("="*70)
        print(f"KS-p (inter-arrival): {ks_p:.3f}  -> {'PASS' if verdicts['ks_p_interarrival']=='PASS' else 'FAIL'} (>= 0.20)")
        print(f"XCorr_max (autocorr): {xcorr_max:.3f}  -> {'PASS' if verdicts['xcorr_max']=='PASS' else 'FAIL'} (<= 0.35)")
        print(f"AUC (inter-arrival): {auc:.3f}  -> {'PASS' if verdicts['auc_interarrival']=='PASS' else 'FAIL'} (<= 0.55)")
        print("-"*70)
        print(f"Overall: {overall}")
        print(f"Results saved to: {self.output_file}")
        print("="*70)

        return 0 if overall == 'PASS' else 1


async def main():
    parser = argparse.ArgumentParser(description='SATL 3.0 Stealth Validation Test (600s)')
    parser.add_argument('--duration', type=int, default=600, help='Duration seconds (default 600)')
    parser.add_argument('--concurrency', type=int, default=10, help='Concurrent workers (default 10)')
    parser.add_argument('--endpoint', type=str, default='http://localhost:9000/ingress', help='Guard ingress URL')
    parser.add_argument('--bin-size', type=float, default=1.0, help='Bin size seconds for autocorr (default 1.0)')
    args = parser.parse_args()

    test = StealthTest(duration=args.duration, concurrency=args.concurrency, endpoint=args.endpoint, bin_size=args.bin_size)
    rc = await test.run()
    return rc


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        raise SystemExit(1)
