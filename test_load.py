"""
LOAD TEST - Test di carico per SATL 3.0 forwarder chain

Tests:
1. Light load: 100 packets, 10 concurrent
2. Medium load: 500 packets, 50 concurrent
3. Heavy load: 1000 packets, 100 concurrent

Success Criteria:
- Success rate >= 99%
- Average latency < 200ms
- P95 latency < 300ms

Usage:
    python test_load.py
    python test_load.py --packets 1000 --concurrent 100
"""
import asyncio
import httpx
import time
import statistics
import argparse
import sys
from typing import List, Dict

async def send_packet(client: httpx.AsyncClient, url: str, packet_id: int) -> Dict:
    """Send single packet and measure latency"""
    # Build 3-hop packet: [hop_count:1 byte][payload:~1200 bytes]
    packet = bytes([3]) + f"load_test_{packet_id:06d}".encode() + b"X" * 1200

    start = time.time()
    try:
        response = await client.post(
            url,
            content=packet,
            headers={"Content-Type": "application/octet-stream"},
            timeout=10.0
        )
        latency = (time.time() - start) * 1000  # ms

        return {
            "success": response.status_code == 200,
            "latency_ms": latency,
            "packet_id": packet_id,
            "status_code": response.status_code
        }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": "timeout",
            "packet_id": packet_id,
            "latency_ms": (time.time() - start) * 1000
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "packet_id": packet_id,
            "latency_ms": (time.time() - start) * 1000
        }


async def load_test(
    guard_url: str = "http://localhost:9000/ingress",
    total_packets: int = 1000,
    concurrent: int = 50,
    test_name: str = "Load Test"
):
    """
    Execute load test on forwarder chain

    Args:
        guard_url: Guard node ingress endpoint
        total_packets: Total packets to send
        concurrent: Max concurrent requests
        test_name: Name of test for reporting

    Returns:
        dict: Test results
    """
    print("\n" + "="*70)
    print(f"SATL 3.0 - {test_name.upper()}")
    print("="*70)
    print(f"  Target: {guard_url}")
    print(f"  Total packets: {total_packets}")
    print(f"  Concurrent: {concurrent}")
    print("="*70)

    results = []
    semaphore = asyncio.Semaphore(concurrent)

    async def send_with_semaphore(client, packet_id):
        async with semaphore:
            result = await send_packet(client, guard_url, packet_id)
            results.append(result)

            # Progress indicator
            if packet_id > 0 and packet_id % 100 == 0:
                elapsed = time.time() - start_time
                rate = packet_id / elapsed if elapsed > 0 else 0
                print(f"  Progress: {packet_id}/{total_packets} packets ({rate:.1f} pkt/s)")

            return result

    start_time = time.time()

    # Create HTTP client with connection pooling
    limits = httpx.Limits(max_keepalive_connections=concurrent, max_connections=concurrent*2)
    async with httpx.AsyncClient(limits=limits) as client:
        # Send all packets
        tasks = [
            send_with_semaphore(client, i)
            for i in range(total_packets)
        ]
        await asyncio.gather(*tasks)

    end_time = time.time()
    test_duration = end_time - start_time

    # Analyze results
    successes = [r for r in results if r.get("success")]
    failures = [r for r in results if not r.get("success")]
    latencies = [r["latency_ms"] for r in successes if "latency_ms" in r]

    # Count error types
    error_types = {}
    for r in failures:
        error = r.get("error", "unknown")
        error_types[error] = error_types.get(error, 0) + 1

    # Print results
    print("\n" + "="*70)
    print("LOAD TEST RESULTS")
    print("="*70)
    print(f"  Duration: {test_duration:.2f}s")
    print(f"  Total packets: {len(results)}")
    print(f"  Successes: {len(successes)} ({len(successes)/len(results)*100:.1f}%)")
    print(f"  Failures: {len(failures)} ({len(failures)/len(results)*100:.1f}%)")
    print(f"  Throughput: {len(results)/test_duration:.2f} packets/sec")

    if error_types:
        print("\n  Error breakdown:")
        for error, count in error_types.items():
            print(f"    - {error}: {count}")

    print()

    # Latency statistics
    if latencies:
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)

        print("LATENCY STATISTICS (ms):")
        print(f"  Min:    {min(latencies):.2f}")
        print(f"  Max:    {max(latencies):.2f}")
        print(f"  Mean:   {statistics.mean(latencies):.2f}")
        print(f"  Median: {statistics.median(latencies):.2f}")

        # Percentiles
        p50_idx = int(n * 0.50)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)

        p50 = latencies_sorted[min(p50_idx, n-1)]
        p95 = latencies_sorted[min(p95_idx, n-1)]
        p99 = latencies_sorted[min(p99_idx, n-1)]

        print(f"  P50:    {p50:.2f}")
        print(f"  P95:    {p95:.2f}")
        print(f"  P99:    {p99:.2f}")
    else:
        print("⚠️  No latency data (all packets failed)")
        p50 = p95 = p99 = float('inf')

    print("="*70)

    # Success criteria evaluation
    success_rate = len(successes) / len(results) if results else 0
    avg_latency = statistics.mean(latencies) if latencies else float('inf')

    print("\nSUCCESS CRITERIA:")

    criteria_results = []

    # Criterion 1: Success rate >= 99%
    pass_success_rate = success_rate >= 0.99
    criteria_results.append(pass_success_rate)
    status = "✅ PASS" if pass_success_rate else "❌ FAIL"
    print(f"  {status} - Success rate >= 99%: {success_rate*100:.2f}%")

    # Criterion 2: Average latency < 200ms
    pass_avg_latency = avg_latency < 200
    criteria_results.append(pass_avg_latency)
    status = "✅ PASS" if pass_avg_latency else "❌ FAIL"
    print(f"  {status} - Avg latency < 200ms: {avg_latency:.2f}ms")

    # Criterion 3: P95 latency < 300ms
    pass_p95_latency = p95 < 300
    criteria_results.append(pass_p95_latency)
    status = "✅ PASS" if pass_p95_latency else "❌ FAIL"
    print(f"  {status} - P95 latency < 300ms: {p95:.2f}ms")

    # Bonus: Throughput > 100 pkt/s
    throughput = len(results) / test_duration
    pass_throughput = throughput > 100
    status = "✅ PASS" if pass_throughput else "⚠️  WARNING"
    print(f"  {status} - Throughput > 100 pkt/s: {throughput:.2f} pkt/s (bonus)")

    print("="*70)

    all_passed = all(criteria_results)

    if all_passed:
        print("\n🎉 ALL CRITERIA PASSED")
    else:
        print("\n⚠️  SOME CRITERIA FAILED")

    print("="*70)

    return {
        "test_name": test_name,
        "duration": test_duration,
        "total": len(results),
        "successes": len(successes),
        "failures": len(failures),
        "success_rate": success_rate,
        "throughput": throughput,
        "latencies": {
            "mean": avg_latency,
            "p50": p50,
            "p95": p95,
            "p99": p99
        },
        "criteria_passed": all_passed,
        "error_types": error_types
    }


async def run_load_test_suite():
    """Run complete load test suite"""
    print("="*70)
    print("SATL 3.0 - LOAD TEST SUITE")
    print("="*70)
    print("Testing forwarder chain under various loads")
    print("="*70)

    suite_start = time.time()
    suite_results = []

    # Test 1: Light load (warmup)
    print("\n🔥 TEST 1: LIGHT LOAD")
    result1 = await load_test(
        total_packets=100,
        concurrent=10,
        test_name="Light Load (100 pkt, 10 concurrent)"
    )
    suite_results.append(result1)

    await asyncio.sleep(2)  # Cooldown

    # Test 2: Medium load
    print("\n🔥 TEST 2: MEDIUM LOAD")
    result2 = await load_test(
        total_packets=500,
        concurrent=50,
        test_name="Medium Load (500 pkt, 50 concurrent)"
    )
    suite_results.append(result2)

    await asyncio.sleep(2)  # Cooldown

    # Test 3: Heavy load
    print("\n🔥 TEST 3: HEAVY LOAD")
    result3 = await load_test(
        total_packets=1000,
        concurrent=100,
        test_name="Heavy Load (1000 pkt, 100 concurrent)"
    )
    suite_results.append(result3)

    suite_duration = time.time() - suite_start

    # Suite summary
    print("\n" + "="*70)
    print("LOAD TEST SUITE SUMMARY")
    print("="*70)
    print(f"  Total duration: {suite_duration:.2f}s")
    print()

    for i, result in enumerate(suite_results, 1):
        status = "✅ PASS" if result['criteria_passed'] else "❌ FAIL"
        print(f"  Test {i}: {status} - {result['test_name']}")
        print(f"    Success rate: {result['success_rate']*100:.1f}%")
        print(f"    Avg latency: {result['latencies']['mean']:.2f}ms")
        print(f"    P95 latency: {result['latencies']['p95']:.2f}ms")
        print(f"    Throughput: {result['throughput']:.2f} pkt/s")
        print()

    all_passed = all(r['criteria_passed'] for r in suite_results)

    if all_passed:
        print("  🎉 ALL LOAD TESTS PASSED")
        print("  System performance is acceptable for production")
    else:
        print("  ⚠️  SOME LOAD TESTS FAILED")
        print("  System may need optimization before production")

    print("="*70)

    return all_passed


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="SATL 3.0 Load Test")
    parser.add_argument("--packets", type=int, default=None,
                        help="Number of packets (default: run suite)")
    parser.add_argument("--concurrent", type=int, default=50,
                        help="Concurrent requests (default: 50)")
    parser.add_argument("--url", default="http://localhost:9000/ingress",
                        help="Guard node URL (default: http://localhost:9000/ingress)")

    args = parser.parse_args()

    try:
        if args.packets:
            # Single test
            result = await load_test(
                guard_url=args.url,
                total_packets=args.packets,
                concurrent=args.concurrent,
                test_name=f"Custom Load Test ({args.packets} pkt, {args.concurrent} concurrent)"
            )
            return 0 if result['criteria_passed'] else 1
        else:
            # Full suite
            all_passed = await run_load_test_suite()
            return 0 if all_passed else 1

    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
