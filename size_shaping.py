"""
SIZE_SHAPING.PY - Histogram-Based Packet Size Distribution

Implements inverse CDF sampling from baseline HTTPS traffic to make
SATL packet sizes statistically indistinguishable from normal web traffic.

Target: KS-p ≥ 0.20 (Kolmogorov-Smirnov test p-value)
"""
import numpy as np
import secrets
import random
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class SizeShapingConfig:
    """Configuration for size shaping"""
    # Baseline distribution parameters
    get_mean: int = 800
    get_std: int = 200
    post_mean: int = 1200
    post_std: int = 300
    get_probability: float = 0.70  # 70% GET, 30% POST

    # Padding parameters
    min_padding: int = 10
    max_padding: int = 60

    # Chunk size range
    min_chunk: int = 300
    max_chunk: int = 1600

    # Distribution bins
    histogram_bins: int = 64


class SizeShaper:
    """
    Shapes packet sizes to match HTTPS baseline distribution

    Uses inverse CDF sampling to generate sizes that follow
    the same statistical distribution as normal web traffic.
    """

    def __init__(self, config: SizeShapingConfig = None):
        self.config = config or SizeShapingConfig()

        # Generate baseline HTTPS size distribution
        self.baseline_sizes = self._generate_baseline_distribution(num_samples=1000)

        # Build histogram and CDF
        self.hist, self.bin_edges = np.histogram(
            self.baseline_sizes,
            bins=self.config.histogram_bins
        )
        self.cdf = np.cumsum(self.hist) / np.sum(self.hist)

        print(f"[SizeShaper] Initialized with {len(self.baseline_sizes)} baseline samples")
        print(f"  Mean: {np.mean(self.baseline_sizes):.0f}B")
        print(f"  IQR: [{np.percentile(self.baseline_sizes, 25):.0f}B - {np.percentile(self.baseline_sizes, 75):.0f}B]")
        print(f"  Range: [{np.min(self.baseline_sizes):.0f}B - {np.max(self.baseline_sizes):.0f}B]")

    def _generate_baseline_distribution(self, num_samples: int = 1000) -> np.ndarray:
        """
        Generate realistic HTTPS traffic size distribution

        Mix of:
        - 70% GET responses (mean=800, std=200)
        - 30% POST requests/responses (mean=1200, std=300)
        """
        sizes = []

        for _ in range(num_samples):
            if random.random() < self.config.get_probability:
                # GET response
                size = int(np.random.normal(self.config.get_mean, self.config.get_std))
            else:
                # POST request/response
                size = int(np.random.normal(self.config.post_mean, self.config.post_std))

            # Clamp to reasonable range (100B - 2000B)
            size = max(100, min(2000, size))
            sizes.append(size)

        return np.array(sizes)

    def sample_size(self) -> int:
        """
        Sample a packet size from the baseline distribution

        Uses inverse CDF (quantile function) for exact distribution matching.

        Returns:
            Packet size in bytes
        """
        # Sample uniform random [0, 1)
        u = np.random.random()

        # Find bin via binary search in CDF
        bin_idx = np.searchsorted(self.cdf, u)

        # Prevent out-of-bounds
        bin_idx = min(bin_idx, len(self.bin_edges) - 2)

        # Linear interpolation within bin for smoother distribution
        bin_start = self.bin_edges[bin_idx]
        bin_end = self.bin_edges[bin_idx + 1]
        size = bin_start + np.random.uniform(0, bin_end - bin_start)

        return int(size)

    def add_padding_jitter(self, size: int) -> int:
        """
        Add random padding to break quantization

        Args:
            size: Base packet size

        Returns:
            Size with padding jitter (10-60 bytes)
        """
        padding = random.randint(self.config.min_padding, self.config.max_padding)
        return size + padding

    def chunk_payload(self, payload: bytes) -> List[bytes]:
        """
        Split payload into chunks matching baseline size distribution

        Each chunk:
        1. Sampled from HTTPS baseline distribution
        2. Padded with random jitter (10-60 bytes)
        3. Variable size (breaks fixed-size signature)

        Args:
            payload: Data to chunk

        Returns:
            List of chunks (each is bytes)
        """
        chunks = []
        pos = 0

        while pos < len(payload):
            # Sample chunk size from distribution
            chunk_size = self.sample_size()

            # Clamp to chunk size limits
            chunk_size = max(self.config.min_chunk, min(self.config.max_chunk, chunk_size))

            # Don't exceed remaining payload
            chunk_size = min(chunk_size, len(payload) - pos)

            # Extract chunk
            chunk_data = payload[pos:pos + chunk_size]

            # Add padding jitter
            padding_size = random.randint(self.config.min_padding, self.config.max_padding)
            padding = secrets.token_bytes(padding_size)

            # Combine: [chunk_data][padding]
            chunk_with_padding = chunk_data + padding
            chunks.append(chunk_with_padding)

            pos += chunk_size

        return chunks

    def get_statistics(self, sizes: List[int]) -> dict:
        """
        Compute statistics for a list of packet sizes

        Useful for comparing SATL traffic vs baseline.
        """
        sizes_array = np.array(sizes)

        return {
            "count": len(sizes),
            "mean": np.mean(sizes_array),
            "std": np.std(sizes_array),
            "min": np.min(sizes_array),
            "max": np.max(sizes_array),
            "q25": np.percentile(sizes_array, 25),
            "q50": np.percentile(sizes_array, 50),
            "q75": np.percentile(sizes_array, 75),
            "iqr": np.percentile(sizes_array, 75) - np.percentile(sizes_array, 25)
        }

    def validate_distribution_match(self, sampled_sizes: List[int]) -> Tuple[float, bool]:
        """
        Validate that sampled sizes match baseline distribution

        Uses Kolmogorov-Smirnov test:
        - p-value >= 0.20: distributions are statistically similar (PASS)
        - p-value < 0.20: distributions are different (FAIL)

        Args:
            sampled_sizes: Sizes generated by sample_size()

        Returns:
            (ks_p_value, is_pass)
        """
        from scipy import stats

        ks_stat, p_value = stats.ks_2samp(sampled_sizes, self.baseline_sizes)
        is_pass = p_value >= 0.20

        return p_value, is_pass


# ==================== TESTING ====================

def test_size_shaping():
    """Test size shaping distribution matching"""
    print("="*70)
    print("SIZE SHAPING TEST")
    print("="*70)

    # Initialize shaper
    shaper = SizeShaper()

    # Sample 1000 sizes
    print("\n[1/3] Sampling 1000 packet sizes...")
    sampled_sizes = [shaper.sample_size() for _ in range(1000)]

    # Compute statistics
    print("\n[2/3] Computing statistics...")
    baseline_stats = shaper.get_statistics(shaper.baseline_sizes)
    sampled_stats = shaper.get_statistics(sampled_sizes)

    print("\nBaseline HTTPS:")
    print(f"  Mean: {baseline_stats['mean']:.0f}B")
    print(f"  Std: {baseline_stats['std']:.0f}B")
    print(f"  IQR: [{baseline_stats['q25']:.0f}B - {baseline_stats['q75']:.0f}B]")
    print(f"  Range: [{baseline_stats['min']:.0f}B - {baseline_stats['max']:.0f}B]")

    print("\nSampled SATL:")
    print(f"  Mean: {sampled_stats['mean']:.0f}B")
    print(f"  Std: {sampled_stats['std']:.0f}B")
    print(f"  IQR: [{sampled_stats['q25']:.0f}B - {sampled_stats['q75']:.0f}B]")
    print(f"  Range: [{sampled_stats['min']:.0f}B - {sampled_stats['max']:.0f}B]")

    # KS test
    print("\n[3/3] Kolmogorov-Smirnov test...")
    ks_p, is_pass = shaper.validate_distribution_match(sampled_sizes)

    print(f"\nKS-p value: {ks_p:.3f}")
    if is_pass:
        print("  [PASS] Distributions are statistically similar (p >= 0.20)")
    else:
        print("  [FAIL] Distributions differ significantly (p < 0.20)")

    # Test chunking
    print("\n" + "="*70)
    print("CHUNKING TEST")
    print("="*70)

    test_payload = b"X" * 5000  # 5KB payload
    chunks = shaper.chunk_payload(test_payload)

    print(f"\nPayload: {len(test_payload)} bytes")
    print(f"Chunks: {len(chunks)}")
    print(f"Chunk sizes: {[len(c) for c in chunks]}")
    print(f"Total size (with padding): {sum(len(c) for c in chunks)} bytes")
    print(f"Overhead: {(sum(len(c) for c in chunks) - len(test_payload)) / len(test_payload) * 100:.1f}%")

    print("\n" + "="*70)

    return is_pass


if __name__ == "__main__":
    test_size_shaping()
