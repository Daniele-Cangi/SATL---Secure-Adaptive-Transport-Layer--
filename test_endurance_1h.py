"""
SATL 3.0 - ENDURANCE TEST - Robust Edition

Configurable duration with smoke/1h modes
Reliable success/failure counting
Early-fail detection for misconfiguration

Usage:
  python test_endurance_1h.py                    # 1 hour (3600s)
  python test_endurance_1h.py --duration 120     # 2 minutes (smoke test)
  python test_endurance_1h.py --concurrency 20   # 20 concurrent workers
  python test_endurance_1h.py --endpoint http://localhost:9000/ingress

Environment variables:
  SATL_ENDURANCE_SECS=600       # Duration in seconds
  SATL_ENDURANCE_CONC=10        # Concurrency
  SATL_INGRESS_URL=http://...   # Endpoint URL

Author: SATL 3.0 Research Team
Date: 2025-11-04
"""
import argparse
import os
import sys
import json
import time
import asyncio
import pathlib
import gc
import httpx
import psutil
from typing import List


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description='SATL 3.0 Endurance Test')
    parser.add_argument(
        '--duration',
        type=int,
        default=int(os.getenv('SATL_ENDURANCE_SECS', '3600')),
        help='Test duration in seconds (default: 3600, env: SATL_ENDURANCE_SECS)'
    )
    parser.add_argument(
        '--concurrency',
        type=int,
        default=int(os.getenv('SATL_ENDURANCE_CONC', '10')),
        help='Number of concurrent workers (default: 10, env: SATL_ENDURANCE_CONC)'
    )
    parser.add_argument(
        '--endpoint',
        default=os.getenv('SATL_INGRESS_URL', 'http://localhost:9000/ingress'),
        help='Ingress endpoint URL (default: http://localhost:9000/ingress, env: SATL_INGRESS_URL)'
    )
    parser.add_argument(
        '--checkpoint',
        type=int,
        default=300,
        help='Checkpoint interval in seconds (default: 300, auto: 60 if duration<900)'
    )
    return parser.parse_args()


class EnduranceTest:
    """Robust endurance test with early-fail detection"""

    def __init__(self, args):
        self.args = args
        self.duration = args.duration
        self.concurrency = args.concurrency
        self.endpoint = args.endpoint

        # Auto-adjust checkpoint for short tests
        self.checkpoint_interval = 60 if args.duration < 900 else args.checkpoint

        # Determine test mode
        self.mode = 'smoke' if args.duration < 1800 else '1h'

        # Statistics
        self.latencies: List[float] = []
        self.success_count = 0
        self.failure_count = 0
        self.error_codes: List[str] = []
        self.errors_printed = 0

        # Timing
        self.start_time = 0.0
        self.next_checkpoint = 0.0

        # Output
        self.output_dir = pathlib.Path('perf_artifacts')
        self.output_file = self.output_dir / 'endurance_1h_results.json'

        # Precomputed packet
        self.PACKET = self.build_packet()

    def build_packet(self) -> bytes:
        """Build test packet (simple format for compatibility)"""
        # Format: [hops=3][payload]
        hops = bytes([3])
        payload = b'X' * 1200
        return hops + payload

    def print_banner(self):
        """Print test configuration banner"""
        print("=" * 70)
        print("SATL 3.0 - ENDURANCE TEST (Robust Edition)")
        print("=" * 70)
        print(f"Mode: {self.mode.upper()}")
        print(f"Endpoint: {self.endpoint}")
        print(f"Duration: {self.duration}s ({self.duration // 60} minutes)")
        print(f"Concurrency: {self.concurrency} workers")
        print(f"Checkpoint: every {self.checkpoint_interval}s")
        print(f"Output: {self.output_file}")
        print("=" * 70)
        print()

    async def worker(self, worker_id: int, client: httpx.AsyncClient):
        """Worker coroutine - sends packets and records results"""
        while True:
            elapsed = time.time() - self.start_time
            if elapsed >= self.duration:
                break

            t0 = time.perf_counter()
            try:
                response = await client.post(
                    self.endpoint,
                    content=self.PACKET,
                    headers={"Content-Type": "application/octet-stream"}
                )

                latency_ms = (time.perf_counter() - t0) * 1000.0

                if response.status_code == 200:
                    self.success_count += 1
                    self.latencies.append(latency_ms)
                else:
                    self.failure_count += 1
                    self.error_codes.append(f"HTTP_{response.status_code}")

                # Force close (async)
                await response.aclose()
                del response

            except Exception as e:
                self.failure_count += 1
                error_msg = f"{type(e).__name__}: {str(e)[:100]}"
                self.error_codes.append(error_msg)

                # Print first 5 errors for debugging
                if self.errors_printed < 5:
                    print(f"[ERROR {self.errors_printed + 1}] {error_msg}")
                    self.errors_printed += 1

            # Small delay to prevent spinning
            await asyncio.sleep(0.001)

    async def checkpoint_monitor(self):
        """Monitor progress and log checkpoints"""
        last_success = 0
        last_failure = 0

        while True:
            elapsed = time.time() - self.start_time
            if elapsed >= self.duration:
                break

            # Wait until next checkpoint
            sleep_duration = max(0.1, self.next_checkpoint - time.time())
            await asyncio.sleep(sleep_duration)

            if time.time() < self.next_checkpoint:
                continue

            # Collect stats
            rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            window_success = self.success_count - last_success
            window_failure = self.failure_count - last_failure
            window_total = window_success + window_failure

            last_success = self.success_count
            last_failure = self.failure_count

            avg_latency = (sum(self.latencies) / len(self.latencies)) if self.latencies else 0.0
            success_rate = (window_success / window_total * 100) if window_total > 0 else 0.0

            remaining_sec = int(self.duration - elapsed)
            elapsed_min = int(elapsed // 60)
            remaining_min = int(remaining_sec // 60)

            print(f"\n[CHECKPOINT @ {elapsed_min}m | Remaining: {remaining_min}m]")
            print(f"  Packets (window): {window_total}")
            print(f"  Success: {window_success} ({success_rate:.2f}%)")
            print(f"  Failures: {window_failure}")
            print(f"  Avg Latency: {avg_latency:.2f}ms")
            print(f"  Memory (tester): {rss_mb:.2f} MB")
            print(f"  Total packets sent: {self.success_count + self.failure_count}")

            # Update next checkpoint
            self.next_checkpoint = time.time() + self.checkpoint_interval

    async def early_fail_guard(self):
        """Detect early failure and abort with helpful message"""
        await asyncio.sleep(60)

        if self.success_count == 0:
            print()
            print("=" * 70)
            print("[EARLY-FAIL] Zero successful packets in first 60 seconds")
            print("=" * 70)
            print()
            print("Possible causes:")
            print("  1. Forwarders not running - check: curl http://localhost:9000/health")
            print("  2. Wrong endpoint URL - current: " + self.endpoint)
            print("  3. Wrong profile mode - ensure: SATL_MODE=performance")
            print("  4. Packet format mismatch")
            print()
            print("Troubleshooting:")
            print("  # Check forwarder health")
            print("  curl http://localhost:9000/health")
            print()
            print("  # Start forwarders with performance profile")
            print("  .\\profiles\\switch_profile.ps1 perf")
            print()
            print("  # Check metrics")
            print("  curl http://localhost:10000/metrics | grep satl_window_backend_mode")
            print()
            print("Aborting test...")
            print("=" * 70)
            return 2

        return 0

    def calculate_percentile(self, values: List[float], percentile: float) -> float:
        """Calculate percentile safely"""
        if not values:
            return 0.0

        sorted_values = sorted(values)
        idx = int(max(0, min(len(sorted_values) - 1, round((percentile / 100.0) * (len(sorted_values) - 1)))))
        return sorted_values[idx]

    def save_results(self):
        """Save test results to JSON"""
        total_packets = self.success_count + self.failure_count
        success_rate = (self.success_count / total_packets) if total_packets > 0 else 0.0

        # Calculate latency stats
        latency_stats = {
            'p50': self.calculate_percentile(self.latencies, 50),
            'p95': self.calculate_percentile(self.latencies, 95),
            'p99': self.calculate_percentile(self.latencies, 99),
            'mean': (sum(self.latencies) / len(self.latencies)) if self.latencies else 0.0,
            'min': min(self.latencies) if self.latencies else 0.0,
            'max': max(self.latencies) if self.latencies else 0.0
        }

        results = {
            'test_suite': 'SATL 3.0 Endurance Test (Robust Edition)',
            'version': 'v3.0-rc1',
            'date': time.strftime('%Y-%m-%d'),
            'mode': self.mode,
            'configuration': {
                'duration_seconds': self.duration,
                'concurrency': self.concurrency,
                'endpoint': self.endpoint,
                'checkpoint_interval': self.checkpoint_interval
            },
            'results': {
                'packets': {
                    'total': total_packets,
                    'success': self.success_count,
                    'failure': self.failure_count,
                    'success_rate': round(success_rate * 100, 2)
                },
                'latency_ms': {
                    'p50': round(latency_stats['p50'], 2),
                    'p95': round(latency_stats['p95'], 2),
                    'p99': round(latency_stats['p99'], 2),
                    'mean': round(latency_stats['mean'], 2),
                    'min': round(latency_stats['min'], 2),
                    'max': round(latency_stats['max'], 2)
                },
                'errors_sample': self.error_codes[:10]
            },
            'acceptance_criteria': {
                'success_rate_target': '99%',
                'rss_drift_target': '< 100 MB/hour',
                'p95_degradation_target': '< 10%'
            },
            'verdict': {
                'success_rate': 'PASS' if success_rate >= 0.99 else 'FAIL',
                'overall': 'PASS' if success_rate >= 0.99 else 'FAIL'
            }
        }

        # Ensure output directory exists
        self.output_dir.mkdir(exist_ok=True)

        # Write JSON
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
            f.flush()

        return results

    def print_summary(self, results: dict):
        """Print test summary"""
        print()
        print("=" * 70)
        print("TEST COMPLETE")
        print("=" * 70)
        print(f"Duration: {self.duration}s ({self.duration // 60} minutes)")
        print(f"Total packets: {results['results']['packets']['total']}")
        print(f"Success: {results['results']['packets']['success']}")
        print(f"Failures: {results['results']['packets']['failure']}")
        print(f"Success rate: {results['results']['packets']['success_rate']:.2f}%")
        print()
        print(f"Latency (successful packets):")
        print(f"  P50: {results['results']['latency_ms']['p50']:.2f}ms")
        print(f"  P95: {results['results']['latency_ms']['p95']:.2f}ms")
        print(f"  P99: {results['results']['latency_ms']['p99']:.2f}ms")
        print(f"  Mean: {results['results']['latency_ms']['mean']:.2f}ms")
        print()
        print(f"Verdict: {results['verdict']['overall']}")
        print(f"  Success rate: {results['verdict']['success_rate']}")
        print()
        print(f"Results saved to: {self.output_file}")
        print("=" * 70)

    async def run(self):
        """Run endurance test"""
        self.print_banner()

        self.start_time = time.time()
        self.next_checkpoint = self.start_time + self.checkpoint_interval

        # Create HTTP client with connection pooling
        limits = httpx.Limits(
            max_connections=200,
            max_keepalive_connections=200,
            keepalive_expiry=30.0
        )
        timeout = httpx.Timeout(5.0, read=10.0, write=5.0, connect=5.0)

        async with httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            http2=False,
            headers={'Connection': 'keep-alive'}
        ) as client:

            # Create worker tasks
            worker_tasks = [
                asyncio.create_task(self.worker(i, client))
                for i in range(self.concurrency)
            ]

            # Create monitoring tasks
            checkpoint_task = asyncio.create_task(self.checkpoint_monitor())
            early_fail_task = asyncio.create_task(self.early_fail_guard())

            # Wait for completion
            await asyncio.gather(*worker_tasks, checkpoint_task, return_exceptions=True)

            # Check early fail
            if not early_fail_task.done():
                early_fail_task.cancel()
            else:
                return_code = await early_fail_task
                if return_code == 2 and self.success_count == 0:
                    print("\nTest aborted due to early failure.")
                    return 2

        # Force garbage collection
        gc.collect()

        # Save and print results
        results = self.save_results()
        self.print_summary(results)

        return 0 if results['verdict']['overall'] == 'PASS' else 1


async def main():
    """Main entry point"""
    args = parse_args()
    test = EnduranceTest(args)
    return await test.run()


if __name__ == '__main__':
    try:
        exit_code = asyncio.run(main())
        raise SystemExit(exit_code)
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Test interrupted by user")
        raise SystemExit(1)
    except Exception as e:
        print(f"\n\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
