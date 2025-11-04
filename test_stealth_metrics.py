"""
TEST_STEALTH_METRICS.PY - Stealth Validation
Measures KS-p, XCorr, AUC against baseline HTTPS traffic
"""
import asyncio
import time
import numpy as np
from typing import List, Tuple
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
from satl3_core import SATL3Core, SATL3Config


def capture_traffic_pattern(packets: List[Tuple[float, int]]) -> dict:
    """Extract statistical features from traffic"""
    timestamps = [t for t, _ in packets]
    sizes = [s for _, s in packets]

    # Inter-arrival times
    if len(timestamps) > 1:
        inter_arrivals = np.diff(timestamps)
    else:
        inter_arrivals = np.array([0.0])

    return {
        "sizes": np.array(sizes),
        "inter_arrivals": inter_arrivals,
        "burst_count": sum(1 for dt in inter_arrivals if dt < 0.05),  # Bursts < 50ms
        "avg_size": np.mean(sizes),
        "std_size": np.std(sizes),
        "avg_inter_arrival": np.mean(inter_arrivals) if len(inter_arrivals) > 0 else 0.0,
        "std_inter_arrival": np.std(inter_arrivals) if len(inter_arrivals) > 0 else 0.0,
    }


def kolmogorov_smirnov_test(satl_sizes: np.ndarray, https_sizes: np.ndarray) -> float:
    """
    KS test: measures if two distributions are statistically indistinguishable

    Returns: KS-p value (higher = more similar, >0.20 = good stealth)
    """
    ks_stat, p_value = stats.ks_2samp(satl_sizes, https_sizes)
    return p_value


def cross_correlation(satl_timing: np.ndarray, https_timing: np.ndarray) -> float:
    """
    Cross-correlation: measures timing pattern similarity

    Returns: XCorr value (lower = more similar, <0.35 = good stealth)
    """
    # Normalize
    satl_norm = (satl_timing - np.mean(satl_timing)) / (np.std(satl_timing) + 1e-9)
    https_norm = (https_timing - np.mean(https_timing)) / (np.std(https_timing) + 1e-9)

    # Max cross-correlation
    corr = np.correlate(satl_norm, https_norm, mode='full')
    max_corr = np.max(np.abs(corr)) / len(satl_timing)

    return max_corr


def classifier_auc(satl_features: List[dict], https_features: List[dict]) -> float:
    """
    Train classifier to distinguish SATL from HTTPS

    Returns: AUC (Area Under Curve)
    - 0.5 = random guess (perfect stealth)
    - 1.0 = perfect classification (no stealth)
    - Target: <0.55 (only 5% better than random)
    """
    # Extract feature vectors
    def featurize(f):
        return [
            f["avg_size"],
            f["std_size"],
            f["avg_inter_arrival"],
            f["std_inter_arrival"],
            f["burst_count"]
        ]

    X = []
    y = []

    for f in satl_features:
        X.append(featurize(f))
        y.append(0)  # SATL

    for f in https_features:
        X.append(featurize(f))
        y.append(1)  # HTTPS

    X = np.array(X)
    y = np.array(y)

    # Train RandomForest classifier
    clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    scores = cross_val_score(clf, X, y, cv=5, scoring='roc_auc')

    return np.mean(scores)


async def generate_satl_traffic(duration: float = 120.0) -> List[Tuple[float, int]]:
    """Generate SATL traffic for analysis"""
    config = SATL3Config(
        dht_enabled=False,
        ai_cover_traffic=True,
        cover_traffic_ratio=0.30,
        multiprocessing=False,
        fte_format="tls"  # Use TLS mimicry (P1)
    )

    core = SATL3Core(config)
    await core.initialize()

    packets = []
    start_time = time.time()

    # Generate traffic
    for i in range(20):
        circuit_id = await core.create_circuit()
        if circuit_id:
            send_time = time.time() - start_time
            data = f"Test packet {i}".encode() * 100
            success = await core.send_data(data, circuit_id, use_fte=True, use_ai_mixing=True)
            if success:
                packets.append((send_time, len(data)))

        await asyncio.sleep(0.5)  # 0.5s between sends

    await core.shutdown()

    return packets


def generate_https_baseline(count: int = 20) -> List[Tuple[float, int]]:
    """Generate baseline HTTPS traffic pattern"""
    # Simulate typical HTTPS GET/POST patterns
    packets = []
    t = 0.0

    for i in range(count):
        # Inter-arrival: lognormal distribution (typical web)
        dt = np.random.lognormal(mean=-1.0, sigma=0.8)  # Mean ~0.5s
        t += dt

        # Size: mix of small (GET) and large (POST)
        if np.random.random() < 0.7:
            size = int(np.random.normal(800, 200))  # GET response
        else:
            size = int(np.random.normal(1500, 400))  # POST request/response

        packets.append((t, max(100, size)))

    return packets


async def main():
    print("="*70)
    print("SATL 3.0 - STEALTH METRICS VALIDATION")
    print("="*70)

    print("\n[1/4] Generating SATL traffic (2 min)...")
    satl_packets = await generate_satl_traffic(duration=120.0)
    satl_pattern = capture_traffic_pattern(satl_packets)
    print(f"  SATL: {len(satl_packets)} packets")
    print(f"  Avg size: {satl_pattern['avg_size']:.0f} bytes")
    print(f"  Avg inter-arrival: {satl_pattern['avg_inter_arrival']:.3f}s")

    print("\n[2/4] Generating HTTPS baseline...")
    https_packets = generate_https_baseline(count=20)
    https_pattern = capture_traffic_pattern(https_packets)
    print(f"  HTTPS: {len(https_packets)} packets")
    print(f"  Avg size: {https_pattern['avg_size']:.0f} bytes")
    print(f"  Avg inter-arrival: {https_pattern['avg_inter_arrival']:.3f}s")

    print("\n[3/4] Computing stealth metrics...")

    # KS test (size distribution)
    ks_p = kolmogorov_smirnov_test(satl_pattern["sizes"], https_pattern["sizes"])
    print(f"\n  KS-p (size): {ks_p:.3f}")
    if ks_p >= 0.20:
        print(f"    [PASS] (>=0.20) - Indistinguishable size distribution")
    else:
        print(f"    [FAIL] (<0.20) - Size distribution detectable")

    # Cross-correlation (timing)
    xcorr = cross_correlation(satl_pattern["inter_arrivals"], https_pattern["inter_arrivals"])
    print(f"\n  XCorr (timing): {xcorr:.3f}")
    if xcorr <= 0.35:
        print(f"    [PASS] (<=0.35) - Similar timing patterns")
    else:
        print(f"    [FAIL] (>0.35) - Timing pattern detectable")

    # Classifier AUC
    satl_features = [satl_pattern for _ in range(10)]  # Simulate multiple sessions
    https_features = [https_pattern for _ in range(10)]

    auc = classifier_auc(satl_features, https_features)
    print(f"\n  AUC (classifier): {auc:.3f}")
    if auc <= 0.55:
        print(f"    [PASS] (<=0.55) - Classifier only 5% better than random")
    else:
        print(f"    [FAIL] (>0.55) - Traffic easily classified")

    print("\n[4/4] Final verdict...")
    print("="*70)

    if ks_p >= 0.20 and xcorr <= 0.35 and auc <= 0.55:
        print("[SUCCESS] STEALTH VALIDATION PASSED")
        print("  SATL traffic is statistically indistinguishable from HTTPS")
        print("  -> GO for production deployment")
    else:
        print("[FAIL] STEALTH VALIDATION FAILED")
        print("  Recommendations:")
        if ks_p < 0.20:
            print("    - Adjust packet size distribution (target: 800±200 bytes)")
        if xcorr > 0.35:
            print("    - Increase cover_traffic_ratio to 0.5")
            print("    - Add diurnal timing variation")
        if auc > 0.55:
            print("    - Improve AI traffic generation (more human-like bursts)")

    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
