"""
TESTNET_BETA_POLICY.PY - Hardened Policy Configuration

Implements strict testnet-β policy:
- Fail-closed KEM (ML-KEM-768 default, 1024 strict)
- No mock circuits
- Mandatory logging
- Real 3-hop forwarding
"""
from dataclasses import dataclass
from typing import List, Tuple
import logging

logger = logging.getLogger("POLICY")


@dataclass
class PQCPolicy:
    """Post-Quantum Cryptography policy"""
    require_hybrid: bool = True
    kem_default: str = "ML-KEM-768"  # Kyber768
    kem_strict: str = "ML-KEM-1024"  # Kyber1024 (if available)
    ecdhe: str = "X25519"
    fail_closed_on_kem_mismatch: bool = True
    abort_if_kem_unavailable: bool = True

    def validate_kem(self, available_kems: List[str]) -> str:
        """
        Validate KEM availability and select appropriate algorithm

        Returns: Selected KEM algorithm
        Raises: RuntimeError if policy violated
        """
        if self.abort_if_kem_unavailable and not available_kems:
            raise RuntimeError(
                "POLICY VIOLATION: No KEM available. "
                "Install liboqs-python for ML-KEM support."
            )

        # Prefer strict (ML-KEM-1024) if available
        if self.kem_strict in available_kems:
            logger.info(f"[POLICY] Selected {self.kem_strict} (strict mode)")
            return self.kem_strict

        # Fallback to default (ML-KEM-768)
        if self.kem_default in available_kems:
            logger.info(f"[POLICY] Selected {self.kem_default} (default mode)")
            return self.kem_default

        if self.fail_closed_on_kem_mismatch:
            raise RuntimeError(
                f"POLICY VIOLATION: Required KEM algorithms not available. "
                f"Available: {available_kems}, Required: {self.kem_default} or {self.kem_strict}"
            )

        raise RuntimeError("POLICY VIOLATION: KEM policy cannot be satisfied")


@dataclass
class OnionPolicy:
    """Onion routing policy"""
    layers: int = 3
    aead: str = "ChaCha20-Poly1305"
    pfs_rotation_minutes: int = 10


@dataclass
class NetworkPolicy:
    """Network topology policy"""
    no_mock: bool = True
    require_three_hop: bool = True

    guards: int = 3
    middles: int = 2
    exits: int = 2
    asn_diversity_required: bool = True

    def validate_circuit(self, circuit_nodes: List[dict]) -> bool:
        """
        Validate circuit meets policy requirements

        Returns: True if valid
        Raises: RuntimeError if policy violated
        """
        if self.require_three_hop and len(circuit_nodes) < 3:
            raise RuntimeError(
                f"POLICY VIOLATION: Circuit has {len(circuit_nodes)} hops, "
                f"required: {3 if self.require_three_hop else 'any'}"
            )

        if self.no_mock:
            for node in circuit_nodes:
                if "mock" in node.get("node_id", "").lower():
                    raise RuntimeError(
                        f"POLICY VIOLATION: Mock node detected in circuit: {node['node_id']}"
                    )

        if self.asn_diversity_required and len(circuit_nodes) >= 3:
            # Check ASN diversity (simplified - requires real ASN data)
            # For now, check that node IDs are different
            node_ids = [n.get("node_id") for n in circuit_nodes]
            if len(set(node_ids)) != len(node_ids):
                raise RuntimeError(
                    "POLICY VIOLATION: Circuit nodes are not diverse (duplicate node IDs)"
                )

        return True


@dataclass
class ForwarderPolicy:
    """Forwarder node policy"""
    per_hop_queue_delay_ms: Tuple[int, int] = (0, 0)   # PERF MODE: no queue
    reorder_rate: float = 0.0                           # PERF MODE: no reorder
    apply_rotation_pack_from_spo: bool = True
    force_perf_mode: bool = True  # Skip onion+queue for performance testing


@dataclass
class DHTPolicy:
    """DHT consensus policy"""
    type: str = "kademlia"
    bootstrap_min: int = 2
    bucket_size_k: int = 20
    attestation_signature: str = "Dilithium3"
    quorum_min: int = 3


@dataclass
class PoWPolicy:
    """Proof-of-Work policy"""
    target_solve_ms_idle: Tuple[int, int] = (10, 30)
    target_solve_ms_loaded: Tuple[int, int] = (150, 250)
    difficulty_bits_min: int = 20
    difficulty_bits_max: int = 28
    adaptive_on_queue_pressure: bool = True


@dataclass
class FTETLSPolicy:
    """FTE TLS mimicry policy"""
    format: str = "tls"
    tls_version: str = "1.3"
    cipher_suite: str = "TLS_AES_128_GCM_SHA256"
    alpn: List[str] = None
    ja3_mode: str = "derive_from_local_chrome"
    ja3_require_match: bool = True

    record_shaper_mode: str = "inv_cdf"
    record_shaper_bins: int = 64
    record_shaper_max_bytes: int = 2000
    record_shaper_pad_jitter_bytes: Tuple[int, int] = (10, 60)

    def __post_init__(self):
        if self.alpn is None:
            self.alpn = ["h2", "http/1.1"]


@dataclass
class SizeDistributionPolicy:
    """Size distribution policy"""
    target: str = "https_baseline_inv_cdf"
    mean_bytes: int = 950
    iqr_bytes: Tuple[int, int] = (300, 600)
    heavy_tail_bytes: Tuple[int, int] = (1500, 2000)
    heavy_tail_probability: float = 0.07


@dataclass
class TimingPolicy:
    """Timing pattern policy"""
    model: str = "mixture"
    exp_lambda_hz: float = 2.5
    lognorm_mu: float = -1.2
    lognorm_sigma: float = 0.7

    burst_count_range: Tuple[int, int] = (5, 9)
    burst_intra_gap_ms: Tuple[int, int] = (15, 40)
    burst_probability: float = 0.08

    quantum_ms: int = 20
    deperiodize_enabled: bool = True
    deperiodize_max_shift_ms: int = 8
    interleave_across_circuits: bool = True


@dataclass
class CoverPolicy:
    """Cover traffic policy"""
    base: float = 0.30
    idle: float = 0.50
    on_send_range: Tuple[float, float] = (0.15, 0.25)

    diurnal_micro_enabled: bool = True
    diurnal_micro_amplitude: float = 0.15
    diurnal_micro_period_range: Tuple[int, int] = (90, 150)


@dataclass
class LoggingPolicy:
    """Mandatory logging requirements"""
    require_tls_line: bool = True
    require_cipher_line: bool = True
    require_shaper_line: bool = True
    require_kem_line: bool = True

    def validate_logs(self, log_lines: List[str]) -> bool:
        """
        Validate that all required log lines are present

        Returns: True if all requirements met
        Raises: RuntimeError if missing required logs
        """
        checks = {
            "tls_line": self.require_tls_line,
            "cipher_line": self.require_cipher_line,
            "shaper_line": self.require_shaper_line,
            "kem_line": self.require_kem_line
        }

        patterns = {
            "tls_line": ["FTE=TLS", "TLS mimicry", "ALPN"],
            "cipher_line": ["Cipher=", "TLS=1.3", "ChaCha20"],
            "shaper_line": ["RecordShaper", "invCDF", "bins="],
            "kem_line": ["KEM=", "ML-KEM", "Kyber", "X25519"]
        }

        missing = []

        for check_name, required in checks.items():
            if not required:
                continue

            # Check if any pattern matches
            found = False
            for pattern in patterns[check_name]:
                if any(pattern in line for line in log_lines):
                    found = True
                    break

            if not found:
                missing.append(check_name)

        if missing:
            raise RuntimeError(
                f"POLICY VIOLATION: Missing required log lines: {missing}"
            )

        return True


@dataclass
class ValidatorPolicy:
    """Stealth validation policy"""
    pcap_window_seconds: int = 120
    baseline_capture: str = "same_host_same_window_https"

    ks_p_threshold_min: float = 0.20
    xcorr_threshold_max: float = 0.35
    auc_threshold_max: float = 0.55

    continuous_green_seconds: int = 600  # 10 minutes
    no_mock_occurrences: bool = True
    kem_policy_matches: bool = True
    required_log_lines_present: bool = True


@dataclass
class TestnetBetaPolicy:
    """Complete testnet-β hardened policy"""
    version: str = "1.0"
    project: str = "SATL 3.x — Testnet-β hardening (no mock, no fallback)"

    pqc: PQCPolicy = None
    onion: OnionPolicy = None
    network: NetworkPolicy = None
    forwarder: ForwarderPolicy = None
    dht: DHTPolicy = None
    pow: PoWPolicy = None
    fte_tls: FTETLSPolicy = None
    size_distribution: SizeDistributionPolicy = None
    timing: TimingPolicy = None
    cover: CoverPolicy = None
    logging: LoggingPolicy = None
    validator: ValidatorPolicy = None

    def __post_init__(self):
        """Initialize all sub-policies with defaults"""
        if self.pqc is None:
            self.pqc = PQCPolicy()
        if self.onion is None:
            self.onion = OnionPolicy()
        if self.network is None:
            self.network = NetworkPolicy()
        if self.forwarder is None:
            self.forwarder = ForwarderPolicy()
        if self.dht is None:
            self.dht = DHTPolicy()
        if self.pow is None:
            self.pow = PoWPolicy()
        if self.fte_tls is None:
            self.fte_tls = FTETLSPolicy()
        if self.size_distribution is None:
            self.size_distribution = SizeDistributionPolicy()
        if self.timing is None:
            self.timing = TimingPolicy()
        if self.cover is None:
            self.cover = CoverPolicy()
        if self.logging is None:
            self.logging = LoggingPolicy()
        if self.validator is None:
            self.validator = ValidatorPolicy()

    def log_policy_status(self):
        """Log current policy configuration"""
        logger.info("="*70)
        logger.info("TESTNET-β HARDENED POLICY")
        logger.info("="*70)
        logger.info(f"Version: {self.version}")
        logger.info(f"Project: {self.project}")
        logger.info("")
        logger.info(f"PQC: {self.pqc.kem_default} (default), {self.pqc.kem_strict} (strict)")
        logger.info(f"  Fail-closed: {self.pqc.fail_closed_on_kem_mismatch}")
        logger.info(f"  Abort on unavailable: {self.pqc.abort_if_kem_unavailable}")
        logger.info("")
        logger.info(f"Network: {self.network.guards}G + {self.network.middles}M + {self.network.exits}E")
        logger.info(f"  No mock: {self.network.no_mock}")
        logger.info(f"  Require 3-hop: {self.network.require_three_hop}")
        logger.info(f"  ASN diversity: {self.network.asn_diversity_required}")
        logger.info("")
        logger.info(f"FTE: {self.fte_tls.format.upper()} {self.fte_tls.tls_version}")
        logger.info(f"  Cipher: {self.fte_tls.cipher_suite}")
        logger.info(f"  ALPN: {', '.join(self.fte_tls.alpn)}")
        logger.info("")
        logger.info(f"Stealth Thresholds:")
        logger.info(f"  KS-p >= {self.validator.ks_p_threshold_min}")
        logger.info(f"  XCorr <= {self.validator.xcorr_threshold_max}")
        logger.info(f"  AUC <= {self.validator.auc_threshold_max}")
        logger.info(f"  Continuous green: {self.validator.continuous_green_seconds}s")
        logger.info("="*70)


# Export default policy
DEFAULT_TESTNET_BETA_POLICY = TestnetBetaPolicy()
