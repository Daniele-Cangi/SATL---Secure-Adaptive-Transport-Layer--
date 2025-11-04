"""
PROMETHEUS_EXPORTER.PY - Metrics Exporter for SATL 3.0

Exports production metrics:
- circuit_build_time_ms
- pps_cover (packets per second - cover traffic)
- queue_depth
- error_rate
- pow_solve_ms
- handshake_fail_closed_count

Usage:
    # In satl3_core.py or forwarder daemon
    from prometheus_exporter import SATLPrometheusExporter

    exporter = SATLPrometheusExporter(port=9090)
    exporter.start()

    # Record metrics
    exporter.record_circuit_build(duration_ms=15.3)
    exporter.record_cover_packet()
    exporter.record_error("circuit_creation_failed")
"""
import time
import threading
from typing import Dict, List
from collections import defaultdict, deque
from dataclasses import dataclass
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging

# Try to import psutil for RSS tracking
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger("PROMETHEUS")


@dataclass
class MetricValue:
    """Single metric value with timestamp"""
    value: float
    timestamp: float


class SATLPrometheusExporter:
    """Prometheus-compatible metrics exporter"""

    def __init__(self, port: int = 9090, retention_seconds: int = 3600, role: str = "unknown"):
        """
        Initialize exporter

        Args:
            port: HTTP server port for /metrics endpoint
            retention_seconds: How long to keep metrics history
            role: Forwarder role (guard/middle/exit) for RSS labeling
        """
        self.port = port
        self.retention_seconds = retention_seconds
        self.role = role

        # Metrics storage
        self.circuit_build_times = deque(maxlen=1000)  # Last 1000 builds
        self.cover_packet_times = deque(maxlen=10000)  # Last 10k cover packets
        self.queue_depths = deque(maxlen=1000)
        self.errors = defaultdict(int)  # Error type -> count
        self.pow_solve_times = deque(maxlen=1000)
        self.handshake_fail_closed = 0

        # Additional metrics
        self.packets_forwarded = 0
        self.packets_reordered = 0
        self.circuits_active = 0

        # RSS tracking
        self.process_rss_bytes = 0
        self._rss_update_thread = None

        # Window store metrics (Task C2)
        self.window_backend_mode = "unknown"  # Set by store integration
        self.window_store_ops = defaultdict(lambda: deque(maxlen=1000))  # op_name -> [duration_ms, ...]

        # HTTP server
        self.server = None
        self.server_thread = None

        logger.info(f"Prometheus exporter initialized on port {port} (role={role})")

    def record_circuit_build(self, duration_ms: float):
        """Record circuit build time"""
        self.circuit_build_times.append(MetricValue(duration_ms, time.time()))

    def record_cover_packet(self):
        """Record cover packet sent"""
        self.cover_packet_times.append(MetricValue(1.0, time.time()))

    def record_queue_depth(self, depth: int):
        """Record current queue depth"""
        self.queue_depths.append(MetricValue(depth, time.time()))

    def record_error(self, error_type: str):
        """Record error occurrence"""
        self.errors[error_type] += 1

    def record_pow_solve(self, duration_ms: float):
        """Record PoW solve time"""
        self.pow_solve_times.append(MetricValue(duration_ms, time.time()))

    def record_handshake_fail_closed(self):
        """Record fail-closed handshake"""
        self.handshake_fail_closed += 1

    def record_packet_forwarded(self):
        """Record packet forwarded"""
        self.packets_forwarded += 1

    def record_packet_reordered(self):
        """Record packet reordered"""
        self.packets_reordered += 1

    def set_circuits_active(self, count: int):
        """Set current active circuits count"""
        self.circuits_active = count

    def set_window_backend(self, mode: str):
        """Set window store backend mode (memory/sqlite)"""
        self.window_backend_mode = mode

    def record_window_store_op(self, op_name: str, duration_ms: float):
        """Record window store operation timing"""
        self.window_store_ops[op_name].append(MetricValue(duration_ms, time.time()))

    def _update_rss_loop(self):
        """Background thread to update RSS every 5 seconds"""
        while True:
            try:
                if HAS_PSUTIL:
                    process = psutil.Process()
                    self.process_rss_bytes = process.memory_info().rss
            except Exception as e:
                logger.warning(f"Failed to update RSS: {e}")

            time.sleep(5)

    def _start_rss_tracking(self):
        """Start background RSS tracking thread"""
        if HAS_PSUTIL and self._rss_update_thread is None:
            self._rss_update_thread = threading.Thread(target=self._update_rss_loop, daemon=True)
            self._rss_update_thread.start()
            logger.info("[RSS] Background tracking started (5s interval)")
        elif not HAS_PSUTIL:
            logger.warning("[RSS] psutil not available - RSS tracking disabled")

    def _compute_pps_cover(self, window_seconds: float = 60.0) -> float:
        """Compute cover packets per second over window"""
        now = time.time()
        cutoff = now - window_seconds

        count = sum(1 for m in self.cover_packet_times if m.timestamp >= cutoff)
        return count / window_seconds

    def _compute_avg(self, values: deque, window_seconds: float = 300.0) -> float:
        """Compute average over time window"""
        if not values:
            return 0.0

        now = time.time()
        cutoff = now - window_seconds

        recent = [m.value for m in values if m.timestamp >= cutoff]
        return sum(recent) / len(recent) if recent else 0.0

    def _compute_percentile(self, values: deque, percentile: float, window_seconds: float = 300.0) -> float:
        """Compute percentile over time window"""
        if not values:
            return 0.0

        now = time.time()
        cutoff = now - window_seconds

        recent = sorted([m.value for m in values if m.timestamp >= cutoff])
        if not recent:
            return 0.0

        idx = int(len(recent) * percentile / 100.0)
        return recent[min(idx, len(recent) - 1)]

    def get_metrics_text(self) -> str:
        """
        Generate Prometheus-compatible metrics text

        Returns:
            Metrics in Prometheus text format
        """
        lines = []

        # Circuit build time
        avg_build = self._compute_avg(self.circuit_build_times, window_seconds=300.0)
        p50_build = self._compute_percentile(self.circuit_build_times, 50, window_seconds=300.0)
        p95_build = self._compute_percentile(self.circuit_build_times, 95, window_seconds=300.0)

        lines.append("# HELP satl_circuit_build_time_ms Circuit build time in milliseconds")
        lines.append("# TYPE satl_circuit_build_time_ms gauge")
        lines.append(f"satl_circuit_build_time_ms{{stat=\"avg\"}} {avg_build:.2f}")
        lines.append(f"satl_circuit_build_time_ms{{stat=\"p50\"}} {p50_build:.2f}")
        lines.append(f"satl_circuit_build_time_ms{{stat=\"p95\"}} {p95_build:.2f}")

        # Cover traffic PPS
        pps_cover = self._compute_pps_cover(window_seconds=60.0)
        lines.append("# HELP satl_pps_cover Cover traffic packets per second (60s window)")
        lines.append("# TYPE satl_pps_cover gauge")
        lines.append(f"satl_pps_cover {pps_cover:.2f}")

        # Queue depth
        avg_queue = self._compute_avg(self.queue_depths, window_seconds=60.0)
        lines.append("# HELP satl_queue_depth Average queue depth")
        lines.append("# TYPE satl_queue_depth gauge")
        lines.append(f"satl_queue_depth {avg_queue:.2f}")

        # Error rate (errors per minute over last 5 min)
        total_errors = sum(self.errors.values())
        error_rate = total_errors / 5.0  # Assuming 5-minute window
        lines.append("# HELP satl_error_rate Errors per minute (5min window)")
        lines.append("# TYPE satl_error_rate gauge")
        lines.append(f"satl_error_rate {error_rate:.2f}")

        # Error breakdown
        lines.append("# HELP satl_errors_total Total errors by type")
        lines.append("# TYPE satl_errors_total counter")
        for error_type, count in self.errors.items():
            lines.append(f"satl_errors_total{{type=\"{error_type}\"}} {count}")

        # PoW solve time
        avg_pow = self._compute_avg(self.pow_solve_times, window_seconds=300.0)
        p95_pow = self._compute_percentile(self.pow_solve_times, 95, window_seconds=300.0)
        lines.append("# HELP satl_pow_solve_ms PoW solve time in milliseconds")
        lines.append("# TYPE satl_pow_solve_ms gauge")
        lines.append(f"satl_pow_solve_ms{{stat=\"avg\"}} {avg_pow:.2f}")
        lines.append(f"satl_pow_solve_ms{{stat=\"p95\"}} {p95_pow:.2f}")

        # Handshake fail-closed count
        lines.append("# HELP satl_handshake_fail_closed_total Fail-closed handshake count")
        lines.append("# TYPE satl_handshake_fail_closed_total counter")
        lines.append(f"satl_handshake_fail_closed_total {self.handshake_fail_closed}")

        # Additional metrics
        lines.append("# HELP satl_packets_forwarded_total Packets forwarded")
        lines.append("# TYPE satl_packets_forwarded_total counter")
        lines.append(f"satl_packets_forwarded_total {self.packets_forwarded}")

        lines.append("# HELP satl_packets_reordered_total Packets reordered")
        lines.append("# TYPE satl_packets_reordered_total counter")
        lines.append(f"satl_packets_reordered_total {self.packets_reordered}")

        lines.append("# HELP satl_circuits_active Currently active circuits")
        lines.append("# TYPE satl_circuits_active gauge")
        lines.append(f"satl_circuits_active {self.circuits_active}")

        # Process RSS (Task F)
        lines.append("# HELP satl_process_rss_bytes Process RSS memory in bytes")
        lines.append("# TYPE satl_process_rss_bytes gauge")
        lines.append(f"satl_process_rss_bytes{{role=\"{self.role}\"}} {self.process_rss_bytes}")

        # Window store backend (Task C2)
        lines.append("# HELP satl_window_backend_mode Window store backend mode")
        lines.append("# TYPE satl_window_backend_mode gauge")
        backend_value = 1 if self.window_backend_mode == "memory" else 2 if self.window_backend_mode == "sqlite" else 0
        lines.append(f"satl_window_backend_mode{{mode=\"{self.window_backend_mode}\"}} {backend_value}")

        # Window store operation timings (Task C2)
        for op_name, values in self.window_store_ops.items():
            if values:
                avg_duration = self._compute_avg(values, window_seconds=60.0)
                p95_duration = self._compute_percentile(values, 95, window_seconds=60.0)

                lines.append(f"# HELP satl_window_store_op_ms Window store operation duration in milliseconds")
                lines.append(f"# TYPE satl_window_store_op_ms gauge")
                lines.append(f"satl_window_store_op_ms{{op=\"{op_name}\",stat=\"avg\"}} {avg_duration:.2f}")
                lines.append(f"satl_window_store_op_ms{{op=\"{op_name}\",stat=\"p95\"}} {p95_duration:.2f}")

        return "\n".join(lines) + "\n"

    def start(self):
        """Start HTTP server for /metrics endpoint"""

        # Start RSS tracking (Task F)
        self._start_rss_tracking()

        exporter = self

        class MetricsHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/metrics":
                    metrics_text = exporter.get_metrics_text()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; version=0.0.4")
                    self.end_headers()
                    self.wfile.write(metrics_text.encode("utf-8"))
                elif self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status": "healthy"}')
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                # Suppress default HTTP logging
                pass

        try:
            self.server = HTTPServer(("0.0.0.0", self.port), MetricsHandler)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            logger.info(f"Prometheus metrics available at http://0.0.0.0:{self.port}/metrics")
        except Exception as e:
            logger.error(f"Failed to start Prometheus server: {e}")

    def stop(self):
        """Stop HTTP server"""
        if self.server:
            self.server.shutdown()
            logger.info("Prometheus exporter stopped")


# Global exporter instance
_global_exporter = None


def get_exporter(port: int = 9090, role: str = "unknown") -> SATLPrometheusExporter:
    """Get global exporter instance (singleton)"""
    global _global_exporter
    if _global_exporter is None:
        _global_exporter = SATLPrometheusExporter(port=port, role=role)
    return _global_exporter
