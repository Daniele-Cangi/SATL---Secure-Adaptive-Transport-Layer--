"""Inspect raw inter-arrival arrays saved by test_stealth_600s.py
Prints summary statistics, percentiles, KS test and Wasserstein distance.
"""
import glob
import os
import numpy as np
from scipy import stats

def summarize(name, arr):
    print(f"\n-- {name} --")
    arr = np.asarray(arr)
    print(f"count: {arr.size}")
    print(f"mean: {arr.mean():.6f} s, median: {np.median(arr):.6f} s, std: {arr.std():.6f}")
    for p in (1,5,10,25,50,75,90,95,99):
        print(f"P{p}: {np.percentile(arr, p):.6f} s")


def main():
    files = glob.glob(os.path.join('perf_artifacts', 'stealth_600s_raw_*.npz'))
    if not files:
        print('No raw .npz files found in perf_artifacts. Run with --save-raw first.')
        return 2
    # pick the newest
    files.sort(key=os.path.getmtime)
    fpath = files[-1]
    print(f"Loading: {fpath}")
    data = np.load(fpath)
    send_dt = data['send_dt']
    comp_dt = data['comp_dt']
    base_dt = data['base_dt']

    summarize('send_dt', send_dt)
    summarize('comp_dt', comp_dt)
    summarize('base_dt', base_dt)

    # KS on raw (not normalized)
    try:
        ks_stat_raw, ks_p_raw = stats.ks_2samp(send_dt, base_dt)
    except Exception as e:
        ks_stat_raw, ks_p_raw = None, None
    print(f"\nKS 2-sample (send_dt vs base_dt): stat={ks_stat_raw}, p={ks_p_raw}")

    # KS on normalized (scale invariant)
    try:
        s_norm = send_dt / np.mean(send_dt)
        b_norm = base_dt / np.mean(base_dt)
        ks_stat_norm, ks_p_norm = stats.ks_2samp(s_norm, b_norm)
    except Exception as e:
        ks_stat_norm, ks_p_norm = None, None
    print(f"KS 2-sample normalized: stat={ks_stat_norm}, p={ks_p_norm}")

    try:
        from scipy.stats import wasserstein_distance
        wd = wasserstein_distance(send_dt, base_dt)
    except Exception:
        wd = None
    print(f"Wasserstein distance (L1) between send_dt and base_dt: {wd}")

    # simple tail ratio: fraction of intervals > 1s
    thr = 1.0
    frac_send_tail = np.mean(send_dt > thr)
    frac_base_tail = np.mean(base_dt > thr)
    print(f"Fraction > {thr}s: send={frac_send_tail:.6f}, base={frac_base_tail:.6f}")

    return 0

if __name__ == '__main__':
    import sys
    rc = main()
    sys.exit(rc)
