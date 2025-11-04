"""
SATL 3.0 - PERFORMANCE TEST (BARE METAL)

MODE: performance
SPO: logic-secure
PQC: design-level

Configuration (NO STEALTH):
- Queue delay: 0ms (disabled)
- Reorder rate: 0.0 (disabled)
- Padding: minimal
- Max hops: 3 (enforced)

Success Criteria:
- P95 latency < 100ms (3-hop crypto + network only)
- Success rate >= 99%
- Test duration: 60s sustained load

Author: SATL 3.0 Research Team
Date: 2025-11-02
"""
import asyncio
import httpx
import time
import statistics
import sys
import json
from typing import List, Dict
from collections import deque

# Use canonical packet builder
from satl_test_utils import build_perf_packet


class PerformanceTestBare:
    """Performance test - bare metal (no stealth delays)"""

    def __init__(self):
        self.results: List[Dict] = []
        self.start_time: float = 0
        self.packet_count: int = 0

    async def send_packet(self, client: httpx.AsyncClient, packet_id: int) -> Dict:
        """Send single packet and measure latency"""
        # Use canonical packet builder (shared across all tests)
        packet = build_perf_packet(packet_id, hops=3, payload_size=1200)

        start = time.perf_counter()
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

    async def sustained_load_test(
        self,
        duration_seconds: int,
        concurrent: int,
        test_name: str
    ) -> Dict:
        """
        Execute sustained load test (continuous for N seconds)

        Args:
            duration_seconds: Test duration
            concurrent: Number of concurrent requests
            test_name: Test identifier
        """
        print("="*70)
        print(f"PERFORMANCE TEST (BARE METAL): {test_name}")
        print("="*70)
        print(f"MODE: performance")
        print(f"SPO: logic-secure")
        print(f"PQC: design-level")
        print("="*70)
        print(f"Configuration:")
        print(f"  Queue delay: 0ms")
        print(f"  Reorder rate: 0.0")
        print(f"  Padding: minimal")
        print(f"  Max hops: 3")
        print(f"  Duration: {duration_seconds}s")
        print(f"  Concurrency: {concurrent}")
        print("="*70)

        self.results = []
        self.packet_count = 0
        semaphore = asyncio.Semaphore(concurrent)

        async def send_with_semaphore(client, pid):
            async with semaphore:
                result = await self.send_packet(client, pid)
                self.results.append(result)
                return result

        # Connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=concurrent,
            max_connections=concurrent * 2
        )

        test_start = time.perf_counter()
        self.start_time = test_start

        async with httpx.AsyncClient(limits=limits) as client:
            tasks = []

            # Send packets continuously for duration_seconds
            while (time.perf_counter() - test_start) < duration_seconds:
                # Create batch of packets
                batch_size = concurrent
                batch_tasks = [
                    send_with_semaphore(client, self.packet_count + i)
                    for i in range(batch_size)
                ]
                self.packet_count += batch_size

                tasks.extend(batch_tasks)

                # Wait for batch to complete
                await asyncio.gather(*batch_tasks)

                # Small delay to prevent CPU saturation
                await asyncio.sleep(0.01)

        test_duration = time.perf_counter() - test_start

        return self.analyze_results(test_duration, test_name)

    def analyze_results(self, duration: float, test_name: str) -> Dict:
        """Analyze test results with statistical rigor"""

        print("\n" + "="*70)
        print("RESULTS ANALYSIS")
        print("="*70)

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

        # Check if all packets failed
        if fail_count == total:
            print("\n[ERROR] All packets failed")
            return {
                "success": False,
                "reason": "all_failed",
                "test_name": test_name,
                "duration": duration,
                "packets": {
                    "total": total,
                    "successes": success_count,
                    "failures": fail_count,
                    "success_rate": success_rate
                }
            }

        if not latencies:
            print("\n[ERROR] No latency data - all packets failed")
            return {
                "success": False,
                "error": "no_data",
                "test_name": test_name
            }

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
        print("\n" + "="*70)
        print("SUCCESS CRITERIA EVALUATION (BARE METAL)")
        print("="*70)

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

        print("="*70)

        if all_passed:
            print("\n[PASS] All performance criteria met (bare metal)")
        else:
            print("\n[FAIL] Some performance criteria not met")
            print("\nNOTE: This test requires forwarders with queue_delay_ms = 0")
            print("Current forwarders may be running with stealth delays.")

        print("="*70)

        # Return comprehensive results
        return {
            "mode": "performance",
            "spo": "logic-secure",
            "pqc": "design-level",
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
                "packets_per_second": total / duration
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

    print("\n" + "="*70)
    print("SATL 3.0 - PERFORMANCE TEST SUITE (BARE METAL)")
    print("="*70)
    print("\nMODE: performance")
    print("SPO: logic-secure")
    print("PQC: design-level")
    print("\n" + "="*70)
    print("\nIMPORTANT: This test requires forwarders with NO stealth delays")
    print("\nRequired configuration in testnet_beta_policy.py:")
    print("  per_hop_queue_delay_ms = (0, 0)  # Currently (50, 150)")
    print("  reorder_rate = 0.0                # Currently 0.1")
    print("\nIf forwarders are running with stealth delays, results will show")
    print("HIGH latency (expected). This serves as BASELINE comparison.")
    print("\nTo run TRUE bare metal test:")
    print("1. Stop forwarders (Ctrl+C)")
    print("2. Modify testnet_beta_policy.py as shown above")
    print("3. Restart forwarders")
    print("4. Run this test again")
    print("="*70)

    input("\nPress ENTER to start test...")

    tester = PerformanceTestBare()

    # Test 1: 60s sustained load, 10 concurrent
    print("\n\n[TEST 1/2] Sustained Load - 60s, 10 concurrent")
    result1 = await tester.sustained_load_test(
        duration_seconds=60,
        concurrent=10,
        test_name="Sustained 60s - 10 concurrent"
    )

    await asyncio.sleep(2)

    # Test 2: 60s sustained load, 50 concurrent
    print("\n\n[TEST 2/2] Sustained Load - 60s, 50 concurrent")
    result2 = await tester.sustained_load_test(
        duration_seconds=60,
        concurrent=50,
        test_name="Sustained 60s - 50 concurrent"
    )

    # Final summary
    print("\n\n" + "="*70)
    print("TEST SUITE SUMMARY (BARE METAL)")
    print("="*70)

    all_results = [result1, result2]

    for i, result in enumerate(all_results, 1):
        status = "PASS" if result.get("success") else "FAIL"
        symbol = "[OK]" if result.get("success") else "[FAIL]"

        print(f"\nTest {i}: {symbol} {result['test_name']}")
        print(f"  Success rate: {result['packets']['success_rate']*100:.2f}%")
        print(f"  Throughput:   {result['throughput']['packets_per_second']:.2f} pkt/s")
        print(f"  Latency P95:  {result['latency']['p95']:.2f}ms")

    all_passed = all(r.get("success") for r in all_results)

    print("\n" + "="*70)
    if all_passed:
        print("FINAL VERDICT: [PASS] All bare metal tests passed")
        print("P95 < 100ms achieved (pure crypto + network overhead)")
    else:
        print("FINAL VERDICT: [FAIL] Some tests failed")
        print("Check forwarder configuration (queue delays must be 0ms)")
    print("="*70)

    # Save results to JSON
    output = {
        "mode": "performance",
        "spo": "logic-secure",
        "pqc": "design-level",
        "test_date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "configuration": {
            "queue_delay_ms": 0,
            "reorder_rate": 0.0,
            "padding": "minimal",
            "max_hops": 3
        },
        "results": all_results
    }

    with open("performance_bare_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to: performance_bare_results.json")

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
