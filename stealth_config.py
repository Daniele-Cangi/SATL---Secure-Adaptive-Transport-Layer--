"""
STEALTH_CONFIG.PY - Stealth Reshape Configuration
Patch v1 per passare validazione stealth (KS-p≥0.20, XCorr≤0.35, AUC≤0.55)
"""
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class FTEConfig:
    """FTE Configuration - Switch to TLS mimicry"""
    format: str = "tls"  # Was: http_post → Now: TLS 1.3

    # JA3 fingerprint (Chrome 120 stable)
    ja3: str = "chrome-stable-120"
    alpn: List[str] = None  # ["h2", "http/1.1"]

    # Record shaping
    coalescing_writes: Tuple[int, int] = (1, 3)  # Random 1-3 app writes per TLS record
    max_record_bytes: int = 1200  # Variable record size

    def __post_init__(self):
        if self.alpn is None:
            self.alpn = ["h2", "http/1.1"]


@dataclass
class SizeShapingConfig:
    """Packet size distribution shaping"""
    mode: str = "inv_cdf"  # Inverse CDF sampling from baseline
    bin_count: int = 64
    max_bytes: int = 2000

    # Target distribution (matched to HTTPS baseline)
    mean_bytes: int = 950
    iqr_range: Tuple[int, int] = (300, 600)  # Interquartile range
    tail_prob: float = 0.05  # 5% packets in 1500-2000 range

    # Padding jitter
    pad_jitter_range: Tuple[int, int] = (10, 60)


@dataclass
class TimingConfig:
    """Traffic timing configuration - NHPP mixture"""
    model: str = "mixture"

    # Exponential component (70%)
    exp_lambda: float = 2.5  # 2-3 Hz
    exp_weight: float = 0.70

    # LogNormal component (25%)
    lognorm_mu: float = -1.2
    lognorm_sigma: float = 0.7
    lognorm_weight: float = 0.25

    # Burst component (5%)
    burst_count_range: Tuple[int, int] = (5, 9)
    burst_gap_ms_range: Tuple[int, int] = (15, 40)
    burst_weight: float = 0.05

    # Quantization + deperiodization
    quantum_ms: int = 20
    deperiodize_enabled: bool = True
    deperiodize_max_shift_ms: int = 8


@dataclass
class CoverTrafficConfig:
    """Adaptive cover traffic"""
    base_ratio: float = 0.30
    idle_ratio: float = 0.50
    on_send_range: Tuple[float, float] = (0.15, 0.25)

    # Diurnal micro-variation
    diurnal_micro_enabled: bool = True
    diurnal_micro_amplitude: float = 0.15  # ±15%
    diurnal_micro_period_s_range: Tuple[int, int] = (90, 150)


@dataclass
class ForwarderConfig:
    """Real forwarder network config"""
    queue_delay_ms_range: Tuple[int, int] = (50, 150)
    reorder_rate: float = 0.10  # 10% packet reordering


@dataclass
class StealthConfig:
    """Master stealth configuration"""
    fte: FTEConfig = None
    size_shaping: SizeShapingConfig = None
    timing: TimingConfig = None
    cover: CoverTrafficConfig = None
    forwarder: ForwarderConfig = None

    # PSD sanitizer
    psd_sanitizer_enabled: bool = True
    psd_max_shift_ms: int = 8

    def __post_init__(self):
        if self.fte is None:
            self.fte = FTEConfig()
        if self.size_shaping is None:
            self.size_shaping = SizeShapingConfig()
        if self.timing is None:
            self.timing = TimingConfig()
        if self.cover is None:
            self.cover = CoverTrafficConfig()
        if self.forwarder is None:
            self.forwarder = ForwarderConfig()


# Default production config
PRODUCTION_STEALTH_CONFIG = StealthConfig()


if __name__ == "__main__":
    import json
    config = PRODUCTION_STEALTH_CONFIG

    print("STEALTH CONFIGURATION - Patch v1")
    print("="*60)
    print("\n1. FTE Configuration:")
    print(f"   Format: {config.fte.format} (was: http_post)")
    print(f"   JA3: {config.fte.ja3}")
    print(f"   ALPN: {config.fte.alpn}")
    print(f"   Record coalescing: {config.fte.coalescing_writes} writes/record")

    print("\n2. Size Shaping:")
    print(f"   Mode: {config.size_shaping.mode}")
    print(f"   Target mean: {config.size_shaping.mean_bytes}B")
    print(f"   IQR: {config.size_shaping.iqr_range}")
    print(f"   Pad jitter: {config.size_shaping.pad_jitter_range}B")

    print("\n3. Timing (NHPP Mixture):")
    print(f"   Exponential: λ={config.timing.exp_lambda} Hz ({config.timing.exp_weight:.0%})")
    print(f"   LogNormal: μ={config.timing.lognorm_mu}, σ={config.timing.lognorm_sigma} ({config.timing.lognorm_weight:.0%})")
    print(f"   Burst: {config.timing.burst_count_range} pkts @ {config.timing.burst_gap_ms_range}ms ({config.timing.burst_weight:.0%})")
    print(f"   Deperiodize: {config.timing.deperiodize_max_shift_ms}ms max shift")

    print("\n4. Cover Traffic:")
    print(f"   Base: {config.cover.base_ratio:.0%}")
    print(f"   Idle: {config.cover.idle_ratio:.0%}")
    print(f"   On-send: {config.cover.on_send_range}")
    print(f"   Diurnal micro: ±{config.cover.diurnal_micro_amplitude:.0%} every {config.cover.diurnal_micro_period_s_range}s")

    print("\n5. Forwarder:")
    print(f"   Queue delay: {config.forwarder.queue_delay_ms_range}ms")
    print(f"   Reorder rate: {config.forwarder.reorder_rate:.0%}")

    print("\n" + "="*60)
    print("TARGET METRICS:")
    print("  KS-p (size) ≥ 0.20")
    print("  XCorr (timing) ≤ 0.35")
    print("  AUC (classifier) ≤ 0.55")
    print("="*60)
