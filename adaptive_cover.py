"""
ADAPTIVE_COVER.PY - Adaptive Cover Traffic Ratio

Implements dynamic cover traffic ratio that adapts based on:
- Current activity state (idle vs active sending)
- Diurnal micro-variations (simulates human circadian patterns)
- Random perturbations (breaks fixed ratio signature)

Target: Eliminate detectable "fixed 30% cover" signature
"""
import numpy as np
import random
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class CoverConfig:
    """Configuration for adaptive cover traffic"""
    # Base ratio (when neither idle nor active)
    base_ratio: float = 0.30

    # State-dependent ratios
    idle_ratio: float = 0.50       # More cover when idle
    active_min_ratio: float = 0.15  # Less cover when actively sending
    active_max_ratio: float = 0.25

    # Diurnal variation parameters
    diurnal_period_min: float = 90.0   # seconds
    diurnal_period_max: float = 150.0  # seconds
    diurnal_amplitude: float = 0.15    # ±15% variation

    # Ratio bounds
    min_ratio: float = 0.10
    max_ratio: float = 0.60


class AdaptiveCover:
    """
    Adaptive cover traffic generator

    Adjusts cover traffic ratio dynamically to:
    1. Break fixed ratio signature
    2. Adapt to user activity patterns
    3. Maintain plausible deniability
    """

    def __init__(self, config: CoverConfig = None):
        self.config = config or CoverConfig()

        # State tracking
        self.state = "idle"  # idle, on_send
        self.diurnal_phase = 0.0
        self.last_update_time = time.time()

        # Diurnal period (randomized per session)
        self.diurnal_period = random.uniform(
            self.config.diurnal_period_min,
            self.config.diurnal_period_max
        )

        print(f"[AdaptiveCover] Initialized")
        print(f"  Base ratio: {self.config.base_ratio:.0%}")
        print(f"  Idle ratio: {self.config.idle_ratio:.0%}")
        print(f"  Active ratio: {self.config.active_min_ratio:.0%}-{self.config.active_max_ratio:.0%}")
        print(f"  Diurnal period: {self.diurnal_period:.0f}s")

    def update_state(self, is_sending: bool):
        """
        Update internal state based on user activity

        Args:
            is_sending: True if user is actively sending data
        """
        new_state = "on_send" if is_sending else "idle"

        if new_state != self.state:
            self.state = new_state
            # print(f"  [AdaptiveCover] State: {self.state}")

    def get_current_ratio(self, real_packet_rate: Optional[float] = None) -> float:
        """
        Compute current adaptive cover ratio

        Args:
            real_packet_rate: Current rate of real packets (optional)

        Returns:
            Cover traffic ratio (0-1)
        """
        # Base ratio from state
        if self.state == "idle":
            ratio = self.config.idle_ratio
        elif self.state == "on_send":
            # Random within active range
            ratio = random.uniform(
                self.config.active_min_ratio,
                self.config.active_max_ratio
            )
        else:
            ratio = self.config.base_ratio

        # Update diurnal phase
        current_time = time.time()
        elapsed = current_time - self.last_update_time
        self.last_update_time = current_time

        self.diurnal_phase += elapsed / self.diurnal_period

        # Apply diurnal micro-variation (sine wave)
        diurnal_factor = 1.0 + self.config.diurnal_amplitude * np.sin(2 * np.pi * self.diurnal_phase)
        ratio *= diurnal_factor

        # Clamp to bounds
        ratio = np.clip(ratio, self.config.min_ratio, self.config.max_ratio)

        return ratio

    def compute_cover_count(self, real_count: int, ratio: Optional[float] = None) -> int:
        """
        Compute number of cover packets to generate

        Args:
            real_count: Number of real packets
            ratio: Cover ratio (if None, use current adaptive ratio)

        Returns:
            Number of cover packets
        """
        if ratio is None:
            ratio = self.get_current_ratio()

        # Formula: cover = real * ratio / (1 - ratio)
        cover_count = int(real_count * ratio / (1 - ratio))

        return max(0, cover_count)

    def get_ratio_history(self, duration: float, update_interval: float = 1.0) -> list:
        """
        Simulate ratio evolution over time

        Args:
            duration: Simulation duration (seconds)
            update_interval: Time between updates (seconds)

        Returns:
            List of (time, ratio) tuples
        """
        history = []
        t = 0.0

        # Simulate activity pattern (send bursts every 30s for 5s)
        while t < duration:
            is_sending = (t % 30 < 5)
            self.update_state(is_sending)

            ratio = self.get_current_ratio()
            history.append((t, ratio))

            t += update_interval

        return history


# ==================== TESTING ====================

def test_adaptive_cover():
    """Test adaptive cover traffic"""
    print("="*70)
    print("ADAPTIVE COVER TEST")
    print("="*70)

    # Initialize
    cover = AdaptiveCover()

    # Test 1: Ratio variability
    print("\n[1/3] Testing ratio variability (2-minute simulation)...")
    history = cover.get_ratio_history(duration=120.0, update_interval=1.0)

    ratios = [r for _, r in history]
    print(f"  Samples: {len(ratios)}")
    print(f"  Mean ratio: {np.mean(ratios):.3f}")
    print(f"  Std ratio: {np.std(ratios):.3f}")
    print(f"  Min/Max: {np.min(ratios):.3f} / {np.max(ratios):.3f}")

    # Check variability
    is_variable = np.std(ratios) > 0.05
    print(f"  Variable: {'YES' if is_variable else 'NO'} (std > 0.05)")

    # Test 2: State transitions
    print("\n[2/3] Testing state transitions...")

    cover2 = AdaptiveCover()

    # Idle state
    cover2.update_state(is_sending=False)
    idle_ratio = cover2.get_current_ratio()
    print(f"  Idle ratio: {idle_ratio:.3f}")

    # Active state
    cover2.update_state(is_sending=True)
    active_ratios = [cover2.get_current_ratio() for _ in range(10)]
    print(f"  Active ratios: {np.mean(active_ratios):.3f} ± {np.std(active_ratios):.3f}")

    # Test 3: Cover count calculation
    print("\n[3/3] Testing cover count calculation...")

    real_packets = 10

    for state, is_sending in [("idle", False), ("active", True)]:
        cover2.update_state(is_sending)
        ratio = cover2.get_current_ratio()
        cover_count = cover2.compute_cover_count(real_packets, ratio)
        total = real_packets + cover_count
        actual_ratio = cover_count / total

        print(f"  {state.capitalize()}: {real_packets} real + {cover_count} cover = {total} total ({actual_ratio:.1%} cover)")

    # Validation
    print("\n" + "="*70)

    if is_variable and np.min(ratios) >= 0.10 and np.max(ratios) <= 0.60:
        print("[PASS] Adaptive cover working correctly")
        print("  - Ratio is variable (not fixed)")
        print("  - Range is reasonable (0.10-0.60)")
        return True
    else:
        print("[FAIL] Adaptive cover issues detected")
        return False


if __name__ == "__main__":
    test_adaptive_cover()
