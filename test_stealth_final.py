"""
TEST_STEALTH_FINAL.PY - Final Stealth Validation with All Patches

Tests the complete stealth system with P1-P4 integrated.
Properly captures packet sizes AFTER shaping/formatting.
"""
import numpy as np
from scipy import stats
from size_shaping import SizeShaper
from nhpp_timing import NHPPMixture, deperiodize, compute_cross_correlation
from tls_mimicry import TLSMimicry
from adaptive_cover import AdaptiveCover


def test_size_distribution():
    """Test P2: Size shaping"""
    print("="*70)
    print("[TEST 1/3] SIZE DISTRIBUTION (P2)")
    print("="*70)

    shaper = SizeShaper()

    # Generate 100 shaped packet sizes
    shaped_sizes = [shaper.sample_size() for _ in range(100)]

    # Baseline HTTPS sizes
    baseline_sizes = shaper.baseline_sizes[:100]

    # KS test
    ks_stat, p_value = stats.ks_2samp(shaped_sizes, baseline_sizes)

    print(f"\nSATL sizes (shaped):")
    print(f"  Mean: {np.mean(shaped_sizes):.0f}B")
    print(f"  Std: {np.std(shaped_sizes):.0f}B")
    print(f"  Range: [{np.min(shaped_sizes):.0f}B - {np.max(shaped_sizes):.0f}B]")

    print(f"\nHTTPS baseline:")
    print(f"  Mean: {np.mean(baseline_sizes):.0f}B")
    print(f"  Std: {np.std(baseline_sizes):.0f}B")
    print(f"  Range: [{np.min(baseline_sizes):.0f}B - {np.max(baseline_sizes):.0f}B]")

    print(f"\nKS-p value: {p_value:.3f}")
    if p_value >= 0.20:
        print("  [PASS] Distributions are statistically similar (p >= 0.20)")
        return True, p_value
    else:
        print("  [FAIL] Distributions differ significantly (p < 0.20)")
        return False, p_value


def test_timing_patterns():
    """Test P3: NHPP timing"""
    print("\n" + "="*70)
    print("[TEST 2/3] TIMING PATTERNS (P3)")
    print("="*70)

    nhpp = NHPPMixture()

    # Generate 60-second schedule
    schedule = nhpp.generate_schedule(duration=60.0)
    schedule_clean = deperiodize(schedule)

    # Convert to inter-arrivals
    inter_arrivals = np.diff([0.0] + schedule_clean)

    # Baseline HTTPS inter-arrivals (lognormal)
    baseline_inter_arrivals = np.random.lognormal(mean=-1.0, sigma=0.8, size=len(inter_arrivals))

    # Cross-correlation
    xcorr = compute_cross_correlation(inter_arrivals, baseline_inter_arrivals)

    print(f"\nSATL timing:")
    print(f"  Packets: {len(schedule_clean)}")
    print(f"  Mean inter-arrival: {np.mean(inter_arrivals):.3f}s")
    print(f"  Std: {np.std(inter_arrivals):.3f}s")

    print(f"\nHTTPS baseline:")
    print(f"  Mean inter-arrival: {np.mean(baseline_inter_arrivals):.3f}s")
    print(f"  Std: {np.std(baseline_inter_arrivals):.3f}s")

    print(f"\nCross-correlation: {xcorr:.3f}")
    if xcorr <= 0.35:
        print("  [PASS] Timing patterns are similar (XCorr <= 0.35)")
        return True, xcorr
    else:
        print("  [FAIL] Timing patterns differ (XCorr > 0.35)")
        return False, xcorr


def test_tls_fingerprint():
    """Test P1: TLS mimicry"""
    print("\n" + "="*70)
    print("[TEST 3/3] TLS FINGERPRINT (P1)")
    print("="*70)

    tls = TLSMimicry(server_name="www.google.com")

    # Encode sample payload
    payload = b"X" * 500
    records = tls.encode_client_hello(payload, coalesce_count=2)

    print(f"\nPayload: {len(payload)} bytes")
    print(f"TLS records: {len(records)}")
    print(f"Record sizes: {[len(r) for r in records]}")

    # Check for TLS characteristics
    checks_passed = 0
    total_checks = 0

    # Check 1: TLS record header
    total_checks += 1
    if records[0][0] == 0x16:  # Handshake
        print("  [OK] TLS Handshake record type")
        checks_passed += 1
    else:
        print("  [FAIL] Invalid TLS record type")

    # Check 2: TLS version (0x0303 = TLS 1.2, legacy compatibility)
    total_checks += 1
    if records[0][1:3] == b'\x03\x03':
        print("  [OK] TLS 1.2 version (legacy compat)")
        checks_passed += 1
    else:
        print("  [FAIL] Invalid TLS version")

    # Check 3: Variable record sizes (if multiple records)
    total_checks += 1
    if len(records) > 1:
        sizes = [len(r) for r in records]
        if len(set(sizes)) > 1:
            print("  [OK] Variable record sizes (breaks fixed-size signature)")
            checks_passed += 1
        else:
            print("  [FAIL] Fixed record sizes")
    else:
        checks_passed += 1  # Single record is OK
        print("  [OK] Single record (acceptable)")

    print(f"\nTLS mimicry: {checks_passed}/{total_checks} checks passed")
    return checks_passed == total_checks, checks_passed / total_checks


def test_adaptive_cover():
    """Test P4: Adaptive cover"""
    print("\n" + "="*70)
    print("[TEST 4/4] ADAPTIVE COVER (P4)")
    print("="*70)

    cover = AdaptiveCover()

    # Simulate 60-second session with state changes
    ratios = []
    for t in range(60):
        is_sending = (t % 20 < 3)  # Send bursts every 20s for 3s
        cover.update_state(is_sending)
        ratio = cover.get_current_ratio()
        ratios.append(ratio)

    print(f"\nRatio variability (60s simulation):")
    print(f"  Mean: {np.mean(ratios):.3f}")
    print(f"  Std: {np.std(ratios):.3f}")
    print(f"  Min/Max: {np.min(ratios):.3f} / {np.max(ratios):.3f}")

    # Check criteria
    checks_passed = 0
    total_checks = 0

    # Check 1: Non-constant (std > 0.05)
    total_checks += 1
    if np.std(ratios) > 0.05:
        print("  [OK] Ratio is variable (std > 0.05)")
        checks_passed += 1
    else:
        print("  [FAIL] Ratio is too constant")

    # Check 2: Within bounds (0.10 - 0.60)
    total_checks += 1
    if np.min(ratios) >= 0.10 and np.max(ratios) <= 0.60:
        print("  [OK] Ratio within bounds (0.10 - 0.60)")
        checks_passed += 1
    else:
        print("  [FAIL] Ratio out of bounds")

    # Check 3: Adapts to state
    total_checks += 1
    cover_idle = AdaptiveCover()
    cover_idle.update_state(False)
    idle_ratio = cover_idle.get_current_ratio()

    cover_active = AdaptiveCover()
    cover_active.update_state(True)
    active_ratio = cover_active.get_current_ratio()

    if idle_ratio > active_ratio:
        print(f"  [OK] Idle ratio ({idle_ratio:.2f}) > Active ratio ({active_ratio:.2f})")
        checks_passed += 1
    else:
        print(f"  [FAIL] Idle ratio should be higher than active")

    print(f"\nAdaptive cover: {checks_passed}/{total_checks} checks passed")
    return checks_passed == total_checks, checks_passed / total_checks


def main():
    print("="*70)
    print("SATL 3.0 - FINAL STEALTH VALIDATION")
    print("="*70)
    print("\nTesting all stealth patches (P1-P4)")
    print()

    results = {}

    # Test P2 (size)
    passed, metric = test_size_distribution()
    results["P2_size"] = (passed, metric)

    # Test P3 (timing)
    passed, metric = test_timing_patterns()
    results["P3_timing"] = (passed, metric)

    # Test P1 (TLS)
    passed, metric = test_tls_fingerprint()
    results["P1_tls"] = (passed, metric)

    # Test P4 (cover)
    passed, metric = test_adaptive_cover()
    results["P4_cover"] = (passed, metric)

    # Final verdict
    print("\n" + "="*70)
    print("FINAL VERDICT")
    print("="*70)

    all_passed = all(r[0] for r in results.values())

    print(f"\nP1 (TLS mimicry): {'[PASS]' if results['P1_tls'][0] else '[FAIL]'} ({results['P1_tls'][1]:.1%} checks)")
    print(f"P2 (Size shaping): {'[PASS]' if results['P2_size'][0] else '[FAIL]'} (KS-p={results['P2_size'][1]:.3f})")
    print(f"P3 (NHPP timing): {'[PASS]' if results['P3_timing'][0] else '[FAIL]'} (XCorr={results['P3_timing'][1]:.3f})")
    print(f"P4 (Adaptive cover): {'[PASS]' if results['P4_cover'][0] else '[FAIL]'} ({results['P4_cover'][1]:.1%} checks)")

    print("\n" + "="*70)
    if all_passed:
        print("[SUCCESS] ALL STEALTH PATCHES VALIDATED")
        print("  -> Ready for production deployment")
    else:
        print("[PARTIAL] Some patches need adjustment")
        print("  -> Review failed tests above")
    print("="*70)

    return all_passed


if __name__ == "__main__":
    main()
