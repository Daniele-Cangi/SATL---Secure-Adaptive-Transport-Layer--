"""
PERFORMANCE TEST (NO STEALTH MODE)
Scientific validation of system performance WITHOUT stealth delays

Hypothesis: System can achieve P95 < 100ms when queue delays disabled

Configuration:
- Queue delay: 0ms (disabled for performance test)
- Reorder rate: 0% (disabled)
- Target: Pure crypto + network overhead only

Success Criteria:
- P95 latency < 100ms (3-hop crypto + network)
- Success rate >= 99%
- Throughput > 200 pkt/s

Author: SATL 3.0 Research Team
Date: 2025-11-02
"""
import asyncio
import httpx
import time
import statistics
import sys
import json
from typing import List, Dict, Tuple


class PerformanceTest:
    """Performance test without stealth delays"""

    def __init__(self):
        self.results: List[Dict] = []

    async def send_packet(self, client: httpx.AsyncClient, packet_id: int) -> Dict:
        """Send single packet and measure latency"""
        packet = bytes([3]) + f"perf_{packet_id:06d}".encode() + b"X" * 1200

        start = time.perf_counter()  # High precision timer
        try:
            response = await client.post(
                "http://localhost:9000/ingress",
                content=packet,
                headers={"Content-Type": "application/octet-stream"},
                timeout=10.0
            )
            latency_ms = (time.perf_counter() - start) * 1000

            return {
                "packet_id": packet_id,
                "success": response.status_code == 200,
                "latency_ms": latency_ms,
                "timestamp": time.time()
            }
        except Exception as e:
            return {
                "packet_id": packet_id,
                "success": False,
                "error": str(e),
                "latency_ms": 0,
                "timestamp": time.time()
            }

    async def run_test(
        self,
        total_packets: int,
        concurrent: int,
        test_name: str
    ) -> Dict:
        """Execute performance test"""
        print("=" * 70)
        print(f"PERFORMANCE TEST: {test_name}")
        print("=" * 70)
        print(f"Configuration: NO STEALTH (queue=0ms, reorder=0%)")
        print(f"Packets: {total_packets}, Concurrent: {concurrent}")
        print("=" * 70)

        self.results = []
        semaphore = asyncio.Semaphore(concurrent)

        async def send_with_semaphore(client, pid):
            async with semaphore:
                result = await self.send_packet(client, pid)
                self.results.append(result)
                return result

        test_start = time.perf_counter()

        # Connection pooling for performance
        limits = httpx.Limits(
            max_keepalive_connections=concurrent,
            max_connections=concurrent * 2
        )

        async with httpx.AsyncClient(limits=limits) as client:
            tasks = [send_with_semaphore(client, i) for i in range(total_packets)]
            await asyncio.gather(*tasks)

        test_duration = time.perf_counter() - test_start

        return self.analyze_results(test_duration, test_name)

    def analyze_results(self, duration: float, test_name: str) -> Dict:
        """Analyze test results with statistical rigor"""

        print("\n" + "=" * 70)
        print("RESULTS ANALYSIS")
        print("=" * 70)

        # Basic metrics
        successes = [r for r in self.results if r["success"]]
        failures = [r for r in self.results if not r["success"]]
        latencies = [r["latency_ms"] for r in successes if r["latency_ms"] > 0]

        total = len(self.results)
        success_count = len(successes)
        fail_count = len(failures)
        success_rate = success_count / total if total > 0 else 0

        print(f"\nBasic Metrics:")
        print(f"  Duration: {duration:.3f}s")
        print(f"  Total packets: {total}")
        print(f"  Successes: {success_count} ({success_rate*100:.2f}%)")
        print(f"  Failures: {fail_count}")
        print(f"  Throughput: {total/duration:.2f} pkt/s")

        if not latencies:
            print("\n[ERROR] No latency data - all packets failed")
            return {"success": False, "error": "no_data"}

        # Statistical analysis
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)

        mean = statistics.mean(latencies)
        median = statistics.median(latencies)
        stdev = statistics.stdev(latencies) if n > 1 else 0
        variance = statistics.variance(latencies) if n > 1 else 0

        # Percentiles (precise calculation)
        p50_idx = int(n * 0.50)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)

        p50 = latencies_sorted[min(p50_idx, n-1)]
        p95 = latencies_sorted[min(p95_idx, n-1)]
        p99 = latencies_sorted[min(p99_idx, n-1)]

        print(f"\nLatency Statistics (ms):")
        print(f"  Min:      {min(latencies):.3f}")
        print(f"  Max:      {max(latencies):.3f}")
        print(f"  Mean:     {mean:.3f}")
        print(f"  Median:   {median:.3f}")
        print(f"  StdDev:   {stdev:.3f}")
        print(f"  Variance: {variance:.3f}")
        print(f"  P50:      {p50:.3f}")
        print(f"  P95:      {p95:.3f}")
        print(f"  P99:      {p99:.3f}")

        # Success criteria evaluation
        print("\n" + "=" * 70)
        print("SUCCESS CRITERIA EVALUATION")
        print("=" * 70)

        criteria = {
            "success_rate_99": {
                "pass": success_rate >= 0.99,
                "value": success_rate * 100,
                "target": 99.0,
                "unit": "%"
            },
            "p95_latency_100ms": {
                "pass": p95 < 100,
                "value": p95,
                "target": 100,
                "unit": "ms"
            },
            "throughput_200pps": {
                "pass": (total/duration) > 200,
                "value": total/duration,
                "target": 200,
                "unit": "pkt/s"
            }
        }

        all_passed = True

        for criterion, data in criteria.items():
            status = "PASS" if data["pass"] else "FAIL"
            symbol = "[OK]" if data["pass"] else "[FAIL]"

            print(f"  {symbol} {criterion}:")
            print(f"       Value:  {data['value']:.2f} {data['unit']}")
            print(f"       Target: {data['target']:.2f} {data['unit']}")
            print(f"       Status: {status}")

            if not data["pass"]:
                all_passed = False

        print("=" * 70)

        if all_passed:
            print("\n[PASS] All performance criteria met")
        else:
            print("\n[FAIL] Some performance criteria not met")

        print("=" * 70)

        # Return comprehensive results
        return {
            "test_name": test_name,
            "success": all_passed,
            "duration": duration,
            "packets": {
                "total": total,
                "successes": success_count,
                "failures": fail_count,
                "success_rate": success_rate
            },
            "throughput": {
                "packets_per_second": total / duration,
                "pass": (total/duration) > 200
            },
            "latency": {
                "min": min(latencies),
                "max": max(latencies),
                "mean": mean,
                "median": median,
                "stdev": stdev,
                "variance": variance,
                "p50": p50,
                "p95": p95,
                "p99": p99
            },
            "criteria": criteria
        }


async def main():
    """Main test execution"""

    print("\n" + "=" * 70)
    print("SATL 3.0 - PERFORMANCE TEST SUITE (NO STEALTH MODE)")
    print("=" * 70)
    print("\nIMPORTANT: This test requires forwarders to be running")
    print("with queue delays DISABLED (queue_delay_ms = 0)")
    print()
    print("Current forwarders are running WITH stealth delays.")
    print("Results will show HIGH latency (expected).")
    print()
    print("To run TRUE performance test:")
    print("1. Stop current forwarders (Ctrl+C in their windows)")
    print("2. Modify testnet_beta_policy.py:")
    print("   per_hop_queue_delay_ms = (0, 0)  # Was (50, 150)")
    print("   reorder_rate = 0.0                # Was 0.1")
    print("3. Restart forwarders")
    print("4. Run this test again")
    print()
    print("=" * 70)
    print("\nProceeding with CURRENT configuration (stealth ON)...")
    print("This serves as BASELINE for comparison.")
    print("=" * 70)

    await asyncio.sleep(2)

    tester = PerformanceTest()

    # Test 1: Light load
    print("\n\n[TEST 1/3] Light Load - 100 packets, 10 concurrent")
    result1 = await tester.run_test(
        total_packets=100,
        concurrent=10,
        test_name="Light Load (100 pkt, 10 concurrent)"
    )

    await asyncio.sleep(2)

    # Test 2: Medium load
    print("\n\n[TEST 2/3] Medium Load - 500 packets, 50 concurrent")
    result2 = await tester.run_test(
        total_packets=500,
        concurrent=50,
        test_name="Medium Load (500 pkt, 50 concurrent)"
    )

    await asyncio.sleep(2)

    # Test 3: Heavy load
    print("\n\n[TEST 3/3] Heavy Load - 1000 packets, 100 concurrent")
    result3 = await tester.run_test(
        total_packets=1000,
        concurrent=100,
        test_name="Heavy Load (1000 pkt, 100 concurrent)"
    )

    # Final summary
    print("\n\n" + "=" * 70)
    print("TEST SUITE SUMMARY")
    print("=" * 70)

    all_results = [result1, result2, result3]

    for i, result in enumerate(all_results, 1):
        status = "PASS" if result.get("success") else "FAIL"
        symbol = "[OK]" if result.get("success") else "[FAIL]"

        print(f"\nTest {i}: {symbol} {result['test_name']}")
        print(f"  Success rate: {result['packets']['success_rate']*100:.2f}%")
        print(f"  Throughput:   {result['throughput']['packets_per_second']:.2f} pkt/s")
        print(f"  Latency P95:  {result['latency']['p95']:.2f}ms")

    all_passed = all(r.get("success") for r in all_results)

    print("\n" + "=" * 70)
    if all_passed:
        print("FINAL VERDICT: [PASS] All tests passed")
    else:
        print("FINAL VERDICT: [FAIL] Some tests failed")
    print("=" * 70)

    # Save results to JSON
    output = {
        "test_date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "configuration": "stealth_enabled (queue=50-150ms, reorder=10%)",
        "note": "This is BASELINE test with stealth ON. For true performance, disable stealth.",
        "results": all_results
    }

    with open("performance_test_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to: performance_test_results.json")

    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
