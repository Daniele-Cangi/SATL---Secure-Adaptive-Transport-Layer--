"""
SMOKE TEST - Quick verification that SATL 3.0 system is functional

Tests:
1. Forwarder health checks
2. Prometheus metrics availability
3. Basic packet forwarding
4. SPO rotation pack verification

Usage:
    python test_smoke.py
"""
import asyncio
import httpx
import sys
import time

async def test_forwarder_health():
    """Test that all forwarder nodes are healthy"""
    print("\n" + "="*70)
    print("1. FORWARDER HEALTH CHECKS")
    print("="*70)

    nodes = [
        ("Guard", "http://localhost:9000/health"),
        ("Middle", "http://localhost:9001/health"),
        ("Exit", "http://localhost:9002/health"),
    ]

    results = []
    async with httpx.AsyncClient() as client:
        for name, url in nodes:
            try:
                response = await client.get(url, timeout=3.0)
                if response.status_code == 200:
                    data = response.json()
                    print(f"  ✅ {name:10s} - Healthy (role: {data.get('role', 'unknown')})")
                    results.append(True)
                else:
                    print(f"  ❌ {name:10s} - Unhealthy (status: {response.status_code})")
                    results.append(False)
            except Exception as e:
                print(f"  ❌ {name:10s} - Not reachable ({e})")
                results.append(False)

    all_healthy = all(results)
    print(f"\n  Result: {'✅ ALL HEALTHY' if all_healthy else '❌ SOME NODES DOWN'}")
    return all_healthy


async def test_prometheus_metrics():
    """Test that Prometheus metrics are available"""
    print("\n" + "="*70)
    print("2. PROMETHEUS METRICS AVAILABILITY")
    print("="*70)

    metrics_urls = [
        ("Guard", "http://localhost:10000/metrics"),
        ("Middle", "http://localhost:10001/metrics"),
        ("Exit", "http://localhost:10002/metrics"),
    ]

    results = []
    async with httpx.AsyncClient() as client:
        for name, url in metrics_urls:
            try:
                response = await client.get(url, timeout=3.0)
                if response.status_code == 200:
                    # Count metrics
                    lines = [l for l in response.text.split('\n') if l.startswith('satl_')]
                    metric_count = len(lines)
                    print(f"  ✅ {name:10s} - {metric_count} metrics available")
                    results.append(True)
                else:
                    print(f"  ❌ {name:10s} - Not available (status: {response.status_code})")
                    results.append(False)
            except Exception as e:
                print(f"  ❌ {name:10s} - Not reachable ({e})")
                results.append(False)

    all_available = all(results)
    print(f"\n  Result: {'✅ METRICS AVAILABLE' if all_available else '❌ METRICS UNAVAILABLE'}")
    return all_available


async def test_packet_forwarding():
    """Test basic packet forwarding through 3-hop circuit"""
    print("\n" + "="*70)
    print("3. BASIC PACKET FORWARDING")
    print("="*70)

    test_cases = [
        (3, True, "3-hop packet (valid)"),
        (2, True, "2-hop packet (valid)"),
        (1, True, "1-hop packet (valid)"),
        (5, False, "5-hop packet (should reject)"),
    ]

    results = []
    async with httpx.AsyncClient() as client:
        for hop_count, should_succeed, description in test_cases:
            # Build packet: [hop_count:1 byte][payload]
            packet = bytes([hop_count]) + f"test_packet_{hop_count}".encode() + b"X" * 500

            try:
                response = await client.post(
                    "http://localhost:9000/ingress",
                    content=packet,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=5.0
                )

                success = response.status_code == 200
                passed = success == should_succeed

                if passed:
                    print(f"  ✅ {description}")
                    results.append(True)
                else:
                    print(f"  ❌ {description} - Expected {'success' if should_succeed else 'rejection'}, got {'success' if success else 'rejection'}")
                    results.append(False)

            except Exception as e:
                if not should_succeed:
                    print(f"  ✅ {description} - Rejected with error (expected)")
                    results.append(True)
                else:
                    print(f"  ❌ {description} - Error: {e}")
                    results.append(False)

    # Check guard stats
    try:
        stats_response = await client.get("http://localhost:9000/stats", timeout=3.0)
        stats = stats_response.json()
        rejected = stats.get('packets_rejected_non_3hop', 0)
        print(f"\n  Guard stats: {rejected} packets rejected (>3 hop)")
    except Exception as e:
        print(f"  ⚠️  Could not fetch stats: {e}")

    all_passed = all(results)
    print(f"\n  Result: {'✅ FORWARDING WORKS' if all_passed else '❌ FORWARDING ISSUES'}")
    return all_passed


def test_spo_rotation():
    """Test SPO rotation pack creation and verification"""
    print("\n" + "="*70)
    print("4. SPO ROTATION PACK")
    print("="*70)

    try:
        from spo_rotation_pack import RotationPack

        # Create rotation pack
        parameters = {
            "cover.idle_ratio": 0.60,
            "timing.deperiodize_max_shift_ms": 10
        }

        print("  Creating rotation pack...")
        pack = RotationPack.create(parameters)

        print("  ✅ Rotation pack created")

        # Verify signature
        print("  Verifying signature...")
        is_valid = pack.verify()

        if is_valid:
            print("  ✅ Signature valid")

            # Save and reload
            pack.save("smoke_test_rotation.json")
            print("  ✅ Saved to smoke_test_rotation.json")

            pack_loaded = RotationPack.load("smoke_test_rotation.json")
            is_valid_loaded = pack_loaded.verify()

            if is_valid_loaded:
                print("  ✅ Loaded and verified")
                print(f"\n  Result: ✅ SPO ROTATION WORKING")
                return True
            else:
                print("  ❌ Loaded pack verification failed")
                print(f"\n  Result: ❌ SPO ROTATION ISSUES")
                return False
        else:
            print("  ❌ Signature invalid")
            print(f"\n  Result: ❌ SPO ROTATION ISSUES")
            return False

    except Exception as e:
        print(f"  ❌ Error: {e}")
        print(f"\n  Result: ❌ SPO ROTATION FAILED")
        return False


async def run_smoke_tests():
    """Run all smoke tests"""
    print("="*70)
    print("SATL 3.0 - SMOKE TEST SUITE")
    print("="*70)
    print("Quick verification of system functionality")
    print("="*70)

    start_time = time.time()

    # Run tests
    results = {}

    results['health'] = await test_forwarder_health()
    results['metrics'] = await test_prometheus_metrics()
    results['forwarding'] = await test_packet_forwarding()
    results['spo'] = test_spo_rotation()

    # Summary
    duration = time.time() - start_time

    print("\n" + "="*70)
    print("SMOKE TEST SUMMARY")
    print("="*70)
    print(f"  Duration: {duration:.2f}s")
    print()
    print("  Test Results:")
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"    {status} - {test_name.upper()}")

    all_passed = all(results.values())

    print()
    if all_passed:
        print("  🎉 ALL SMOKE TESTS PASSED")
        print("  System is ready for load testing")
    else:
        print("  ⚠️  SOME TESTS FAILED")
        print("  Please fix issues before proceeding")

    print("="*70)

    return all_passed


if __name__ == "__main__":
    try:
        result = asyncio.run(run_smoke_tests())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
