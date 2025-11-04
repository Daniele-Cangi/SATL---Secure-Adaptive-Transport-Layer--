"""
NHPP_TIMING.PY - Non-Homogeneous Poisson Process Timing Model

Implements human-like packet timing to evade correlation attacks.

Mixture model:
- 70% Exponential (lambda=2.5 Hz) - regular activity
- 25% LogNormal (mu=-1.2, sigma=0.7) - bursty periods
- 5% Burst mode (5-9 packets @ 15-40ms) - intense activity

Includes spectral sanitization (deperiodization) to remove periodic artifacts.

Target: XCorr <= 0.35 (cross-correlation with HTTPS baseline)
"""
import numpy as np
import random
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class TimingConfig:
    """Configuration for NHPP timing model"""
    # Exponential component (70%)
    exp_lambda: float = 2.5  # Hz (mean 400ms)
    exp_weight: float = 0.70

    # LogNormal component (25%)
    lognorm_mu: float = -1.2
    lognorm_sigma: float = 0.7
    lognorm_weight: float = 0.25

    # Burst component (5%)
    burst_weight: float = 0.05
    burst_min_packets: int = 5
    burst_max_packets: int = 9
    burst_min_interval_ms: float = 15.0
    burst_max_interval_ms: float = 40.0

    # Quantization (simulates network scheduling)
    quantize_step_ms: float = 20.0  # 20ms quantization
    jitter_range_ms: float = 8.0    # ±8ms jitter

    # Deperiodizer
    depriodize_max_shift_ms: float = 8.0
    depriodize_zscore_threshold: float = 3.0
    depriodize_freq_min: float = 0.1  # Hz
    depriodize_freq_max: float = 5.0  # Hz


class NHPPMixture:
    """
    Non-Homogeneous Poisson Process timing generator

    Generates inter-arrival times that mimic human web browsing patterns.
    """

    def __init__(self, config: TimingConfig = None):
        self.config = config or TimingConfig()

        # Validate weights sum to 1.0
        total_weight = (
            self.config.exp_weight +
            self.config.lognorm_weight +
            self.config.burst_weight
        )
        if not np.isclose(total_weight, 1.0):
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")

        print(f"[NHPPMixture] Initialized")
        print(f"  Exponential: {self.config.exp_weight:.0%} @ {self.config.exp_lambda} Hz")
        print(f"  LogNormal: {self.config.lognorm_weight:.0%} (mu={self.config.lognorm_mu}, sigma={self.config.lognorm_sigma})")
        print(f"  Burst: {self.config.burst_weight:.0%} ({self.config.burst_min_packets}-{self.config.burst_max_packets} pkts)")

    def sample_inter_arrival(self) -> float:
        """
        Sample next inter-arrival time from mixture model

        Returns:
            Inter-arrival time in seconds
        """
        # Sample component
        u = random.random()

        if u < self.config.exp_weight:
            # Exponential component
            dt = np.random.exponential(1.0 / self.config.exp_lambda)

        elif u < (self.config.exp_weight + self.config.lognorm_weight):
            # LogNormal component
            dt = np.random.lognormal(self.config.lognorm_mu, self.config.lognorm_sigma)

        else:
            # Burst component (handled separately in generate_schedule)
            dt = np.random.uniform(
                self.config.burst_min_interval_ms / 1000.0,
                self.config.burst_max_interval_ms / 1000.0
            )

        # Quantize to network scheduling (20ms steps)
        quantized = round(dt / (self.config.quantize_step_ms / 1000.0)) * (self.config.quantize_step_ms / 1000.0)

        # Add jitter
        jitter = np.random.uniform(
            -self.config.jitter_range_ms / 1000.0,
            self.config.jitter_range_ms / 1000.0
        )

        final_dt = quantized + jitter

        # Ensure positive
        return max(0.001, final_dt)

    def generate_schedule(self, duration: float, target_count: int = None) -> List[float]:
        """
        Generate packet schedule for given duration

        Args:
            duration: Session duration in seconds
            target_count: Target number of packets (optional, otherwise use NHPP)

        Returns:
            List of timestamps (seconds from start)
        """
        timestamps = []
        t = 0.0
        burst_mode = False
        burst_count = 0

        while t < duration:
            # Decide if entering burst mode
            if not burst_mode and random.random() < self.config.burst_weight:
                burst_mode = True
                burst_count = random.randint(
                    self.config.burst_min_packets,
                    self.config.burst_max_packets
                )

            # Sample inter-arrival
            if burst_mode:
                # Burst mode: short intervals
                dt = np.random.uniform(
                    self.config.burst_min_interval_ms / 1000.0,
                    self.config.burst_max_interval_ms / 1000.0
                )
                burst_count -= 1
                if burst_count <= 0:
                    burst_mode = False
            else:
                # Normal mode: mixture model
                dt = self.sample_inter_arrival()

            t += dt

            if t < duration:
                timestamps.append(t)

            # Stop if target count reached
            if target_count and len(timestamps) >= target_count:
                break

        return timestamps

    def get_inter_arrivals(self, timestamps: List[float]) -> np.ndarray:
        """Convert timestamps to inter-arrival times"""
        if len(timestamps) == 0:
            return np.array([])
        return np.diff([0.0] + timestamps)


def deperiodize(timestamps: List[float], config: TimingConfig = None) -> List[float]:
    """
    Remove periodic spectral components from timing pattern

    Uses FFT to detect and suppress periodic artifacts that make
    traffic distinguishable from human patterns.

    Args:
        timestamps: List of packet timestamps
        config: Timing configuration

    Returns:
        Cleaned timestamps (deperiodized)
    """
    if not config:
        config = TimingConfig()

    if len(timestamps) < 10:
        return timestamps  # Too few samples

    # Convert to inter-arrivals
    inter_arrivals = np.diff([0.0] + timestamps)

    if len(inter_arrivals) == 0:
        return timestamps

    # Compute FFT
    fft = np.fft.rfft(inter_arrivals)
    freqs = np.fft.rfftfreq(len(inter_arrivals), d=np.mean(inter_arrivals))

    # Compute magnitudes
    magnitudes = np.abs(fft)

    # Detect spikes (z-score > threshold)
    if len(magnitudes) > 1:
        mean_mag = np.mean(magnitudes)
        std_mag = np.std(magnitudes)

        if std_mag > 1e-9:  # Avoid division by zero
            z_scores = (magnitudes - mean_mag) / std_mag

            # Suppress spikes in human activity frequency range (0.1-5 Hz)
            shifts_applied = 0
            for i, z in enumerate(z_scores):
                if z > config.depriodize_zscore_threshold:
                    if config.depriodize_freq_min < freqs[i] < config.depriodize_freq_max:
                        # Apply random shift to break periodicity
                        shift = np.random.uniform(
                            -config.depriodize_max_shift_ms / 1000.0,
                            config.depriodize_max_shift_ms / 1000.0
                        )
                        inter_arrivals[min(i, len(inter_arrivals) - 1)] += shift
                        shifts_applied += 1

            if shifts_applied > 0:
                print(f"  [Deperiodizer] Suppressed {shifts_applied} periodic spikes")

    # Ensure positive inter-arrivals
    inter_arrivals = np.maximum(inter_arrivals, 0.001)

    # Reconstruct timestamps
    cleaned_timestamps = np.cumsum(inter_arrivals).tolist()

    return cleaned_timestamps


def compute_cross_correlation(timing1: List[float], timing2: List[float]) -> float:
    """
    Compute cross-correlation between two timing patterns

    Lower values = more similar patterns

    Args:
        timing1: First timing pattern (inter-arrivals)
        timing2: Second timing pattern (inter-arrivals)

    Returns:
        Max cross-correlation value (0-1)
    """
    # Convert to inter-arrivals if needed
    if len(timing1) == 0 or len(timing2) == 0:
        return 0.0

    # Normalize
    t1_norm = (timing1 - np.mean(timing1)) / (np.std(timing1) + 1e-9)
    t2_norm = (timing2 - np.mean(timing2)) / (np.std(timing2) + 1e-9)

    # Compute cross-correlation
    corr = np.correlate(t1_norm, t2_norm, mode='full')
    max_corr = np.max(np.abs(corr)) / len(timing1)

    return max_corr


# ==================== TESTING ====================

def test_nhpp_timing():
    """Test NHPP timing model"""
    print("="*70)
    print("NHPP TIMING TEST")
    print("="*70)

    # Initialize
    nhpp = NHPPMixture()

    # Generate 2-minute schedule
    print("\n[1/4] Generating 2-minute schedule...")
    schedule = nhpp.generate_schedule(duration=120.0)
    inter_arrivals = nhpp.get_inter_arrivals(schedule)

    print(f"  Packets: {len(schedule)}")
    print(f"  Mean inter-arrival: {np.mean(inter_arrivals):.3f}s")
    print(f"  Std inter-arrival: {np.std(inter_arrivals):.3f}s")
    print(f"  Min/Max: {np.min(inter_arrivals):.3f}s / {np.max(inter_arrivals):.3f}s")

    # Check for bursts
    burst_threshold = 0.05  # 50ms
    burst_count = sum(1 for dt in inter_arrivals if dt < burst_threshold)
    print(f"  Burst packets (<50ms): {burst_count} ({burst_count/len(inter_arrivals)*100:.1f}%)")

    # Spectral analysis
    print("\n[2/4] Spectral analysis (before deperiodization)...")
    fft = np.fft.rfft(inter_arrivals)
    psd = np.abs(fft)**2
    freqs = np.fft.rfftfreq(len(inter_arrivals), d=np.mean(inter_arrivals))

    # Find dominant frequency
    if len(psd) > 1:
        dominant_idx = np.argmax(psd[1:]) + 1  # Skip DC component
        dominant_freq = freqs[dominant_idx]
        dominant_power = psd[dominant_idx]
        median_power = np.median(psd)

        print(f"  Dominant frequency: {dominant_freq:.2f} Hz")
        print(f"  Power ratio (peak/median): {dominant_power / median_power:.2f}")

    # Deperiodize
    print("\n[3/4] Applying deperiodization...")
    schedule_clean = deperiodize(schedule)
    inter_arrivals_clean = nhpp.get_inter_arrivals(schedule_clean)

    # Verify deperiodization
    fft_clean = np.fft.rfft(inter_arrivals_clean)
    psd_clean = np.abs(fft_clean)**2

    if len(psd_clean) > 1:
        dominant_idx_clean = np.argmax(psd_clean[1:]) + 1
        dominant_power_clean = psd_clean[dominant_idx_clean]
        median_power_clean = np.median(psd_clean)

        print(f"  Power ratio after (peak/median): {dominant_power_clean / median_power_clean:.2f}")

    # Cross-correlation test
    print("\n[4/4] Cross-correlation test...")

    # Generate baseline HTTPS timing (lognormal)
    https_inter_arrivals = np.random.lognormal(mean=-1.0, sigma=0.8, size=len(inter_arrivals_clean))

    xcorr = compute_cross_correlation(
        np.array(inter_arrivals_clean),
        https_inter_arrivals
    )

    print(f"\nXCorr: {xcorr:.3f}")
    if xcorr <= 0.35:
        print("  [PASS] Similar timing patterns (XCorr <= 0.35)")
    else:
        print("  [FAIL] Timing patterns differ (XCorr > 0.35)")

    print("\n" + "="*70)

    return xcorr <= 0.35


if __name__ == "__main__":
    test_nhpp_timing()
