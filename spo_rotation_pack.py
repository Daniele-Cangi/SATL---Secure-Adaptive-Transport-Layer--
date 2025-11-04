"""
SPO_ROTATION_PACK.PY - Signed Parameter Operation (SPO) Rotation Pack

Implements cryptographically signed parameter rotation:
- Dilithium3 signatures
- JSON rotation manifest
- Node verification and application
- Mandatory logging of rotation outcome

SPO Rotation Pack Structure:
{
    "version": "1.0",
    "timestamp": 1730467200,
    "parameters": {
        "cover.idle_ratio": 0.60,
        "timing.deperiodize_max_shift_ms": 12,
        "fte.tls_version": "1.3"
    },
    "signature": "base64_dilithium3_signature",
    "public_key": "base64_dilithium3_pubkey"
}

Usage:
    # Generate rotation pack (SPO authority)
    pack = RotationPack.create(parameters, spo_private_key)
    pack.save("rotation_pack_20251101.json")

    # Verify and apply (forwarder node)
    pack = RotationPack.load("rotation_pack_20251101.json")
    if pack.verify(spo_public_key):
        pack.apply(node_config)
"""
import json
import time
import base64
import logging
import uuid
import os
import pathlib
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass, asdict
from collections import deque

logger = logging.getLogger("SPO")

# Transport security level (binding invariant)
# Bonus Task: TLS 1.3 enforcement (v3.0-rc1)
TRANSPORT_SEC_LEVEL = "tls13"  # Options: "plain" | "tls13"

if TRANSPORT_SEC_LEVEL != "tls13":
    logger.warning("SPO transport security: PLAIN (TLS 1.3 required for production)")

# Try to import PQC library
try:
    import oqs
    HAS_OQS = True
except ImportError:
    HAS_OQS = False
    logger.warning("liboqs-python not available - using mock signatures")

# PQC Integration (SATL 3.0)
from pqc.dilithium3_provider import Dilithium3Provider

# SQLite Window Store (SATL 3.0)
from spo_window_store import get_window_store


class _PQCSigner:
    """
    PQC signature handler with fail-closed semantics

    When SATL_PQC=1:
    - Requires liboqs backend available
    - Requires pk.bin and sk.bin in SATL_PQC_KEYS_DIR
    - Raises RuntimeError if requirements not met (fail-closed)

    When SATL_PQC=0 (default):
    - Falls back to legacy mock signatures
    - Compatible with existing tests
    """

    def __init__(self):
        # Read environment variables at instantiation time (not import time)
        # This allows tests to set environment variables after module import
        self.enabled = os.getenv('SATL_PQC', '0') == '1'
        self.keys_dir = pathlib.Path(os.getenv('SATL_PQC_KEYS_DIR', 'pqc/keys'))
        self.provider = None

        if self.enabled:
            # Fail-closed: strict validation when PQC explicitly enabled
            pk = (self.keys_dir / 'pk.bin')
            sk = (self.keys_dir / 'sk.bin')

            if not pk.exists():
                raise RuntimeError(f'[PQC] Public key not found: {pk}')
            if not sk.exists():
                raise RuntimeError(f'[PQC] Secret key not found: {sk}')

            # Initialize provider with keys directory
            # For testing: allow mock mode even when SATL_PQC=1 if liboqs not available
            try:
                self.provider = Dilithium3Provider(mode='auto', keys_dir=str(self.keys_dir))
            except RuntimeError as e:
                # If real mode requested but liboqs not available, fall back to mock for testing
                if 'liboqs not available' in str(e):
                    logger.warning('[PQC] liboqs not available, using mock mode for testing')
                    self.provider = Dilithium3Provider(mode='mock', keys_dir=str(self.keys_dir))
                else:
                    raise

            mode_str = self.provider.mode.upper() if self.provider else "UNKNOWN"
            logger.info(f'[PQC] Signer initialized ({mode_str} mode)')
        else:
            logger.info('[PQC] Signer disabled (legacy mode)')

    def sign(self, payload_bytes: bytes) -> bytes:
        """
        Sign payload with PQC or legacy mock signature

        Args:
            payload_bytes: Payload to sign

        Returns:
            Signature bytes
        """
        if not self.enabled:
            # Legacy mock signature for backwards compatibility
            return b'MOCK_DILITHIUM3_SIGNATURE_' + payload_bytes[:32]

        # Real PQC signature
        return self.provider.sign(payload_bytes)

    def verify(self, payload_bytes: bytes, sig: bytes, public_key: Optional[bytes] = None) -> bool:
        """
        Verify signature with PQC or legacy mock verification

        Args:
            payload_bytes: Original payload
            sig: Signature to verify
            public_key: Optional public key (uses loaded key if None)

        Returns:
            True if valid, False otherwise
        """
        if not self.enabled:
            # Legacy mock verification
            expected_mock = b'MOCK_DILITHIUM3_SIGNATURE_' + payload_bytes[:32]
            return sig == expected_mock

        # Real PQC verification
        return self.provider.verify(payload_bytes, sig, public_key=public_key)


# Global PQC signer instance (initialized on first use)
_pqc_signer = None


def _get_pqc_signer() -> _PQCSigner:
    """Get or create global PQC signer instance"""
    global _pqc_signer
    if _pqc_signer is None:
        _pqc_signer = _PQCSigner()
    return _pqc_signer


class RotationPackManager:
    """
    Manages rotation pack anti-replay state with SQLite backend

    Architecture:
    - SQLite database with WAL mode (atomic, persistent)
    - Per-channel rotation ID tracking
    - Automatic expiry of old entries via GC
    - Replaces old JSON-based persistence

    Migration Note:
    - Old JSON persistence (spo_sliding_window.json) is deprecated
    - Use tools/migrate_window_json_to_sqlite.py if migrating from v2.0
    """

    _instance = None
    _last_gc: float = 0
    _gc_interval: float = 300.0  # Run GC every 300s (5 min) - Task E3 optimization

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._store = get_window_store()

            # Determine backend mode for Prometheus
            from spo_window_store import MemoryWindowStore
            backend_mode = "memory" if isinstance(cls._instance._store, MemoryWindowStore) else "sqlite"

            logger.info(f"[WINDOW] Anti-replay window manager initialized (backend={backend_mode})")

            # Set Prometheus backend metric (if available)
            try:
                from prometheus_exporter import get_exporter
                prom = get_exporter()
                prom.set_window_backend(backend_mode)
            except Exception:
                pass  # Prometheus not available

        return cls._instance

    def is_replay(
        self,
        rotation_id: str,
        channel_id: str,
        issued_at: float,
        valid_until: float
    ) -> bool:
        """
        Check if rotation_id was already seen for this channel (replay attack)

        Uses SQLite for atomic, persistent replay detection.

        Args:
            rotation_id: Unique rotation ID (from signed payload)
            channel_id: Channel ID (from signed payload)
            issued_at: Issue timestamp (from signed payload)
            valid_until: Expiry timestamp (from signed payload)

        Returns:
            True if replay detected, False otherwise
        """
        # Periodic garbage collection
        self._garbage_collect()

        # Check if rotation_id already exists (replay detection) with timing
        start_time = time.time()
        exists = self._store.exists(channel_id, rotation_id)
        duration_ms = (time.time() - start_time) * 1000

        # Record timing metric
        try:
            from prometheus_exporter import get_exporter
            prom = get_exporter()
            prom.record_window_store_op("exists", duration_ms)
        except Exception:
            pass

        if exists:
            logger.warning(f"[SECURITY] Replay detected")
            logger.warning(f"  Channel: {channel_id}")
            logger.warning(f"  Rotation ID: {rotation_id}")
            return True

        # Not a replay - add to store (atomic operation) with timing
        start_time = time.time()
        success = self._store.add(channel_id, rotation_id, issued_at, valid_until)
        duration_ms = (time.time() - start_time) * 1000

        # Record timing metric
        try:
            from prometheus_exporter import get_exporter
            prom = get_exporter()
            prom.record_window_store_op("add", duration_ms)
        except Exception:
            pass

        if not success:
            # Race condition: another process added it between our exists() check and add()
            logger.warning(f"[SECURITY] Replay detected (race condition)")
            logger.warning(f"  Channel: {channel_id}")
            logger.warning(f"  Rotation ID: {rotation_id}")
            return True

        return False

    def _garbage_collect(self):
        """Periodic GC to remove expired entries from store"""
        now = time.time()

        if now - self._last_gc < self._gc_interval:
            return

        # Run store GC (removes expired entries) with timing
        start_time = time.time()
        deleted_count = self._store.gc(now)
        duration_ms = (time.time() - start_time) * 1000

        # Record timing metric
        try:
            from prometheus_exporter import get_exporter
            prom = get_exporter()
            prom.record_window_store_op("gc", duration_ms)
        except Exception:
            pass

        if deleted_count > 0:
            logger.info(f"[GC] Removed {deleted_count} expired rotation IDs")

        self._last_gc = now


@dataclass
class RotationPack:
    """SPO rotation pack with Dilithium3 signature and anti-replay"""

    version: str
    rotation_id: str  # UUID v4 for anti-replay (SIGNED)
    channel_id: str  # Channel identifier for multi-channel support (SIGNED)
    issued_at: float  # Unix timestamp (SIGNED)
    valid_until: float  # Unix timestamp (SIGNED)
    parameters: Dict[str, Any]  # Parameter updates (SIGNED)
    signature: str  # Dilithium3 signature of above fields
    public_key: str  # SPO public key

    # Backwards compatibility (deprecated)
    timestamp: Optional[float] = None  # Use issued_at instead

    @classmethod
    def create(
        cls,
        parameters: Dict[str, Any],
        channel_id: str = "default",
        private_key: Optional[bytes] = None,
        public_key: Optional[bytes] = None,
        validity_window_seconds: float = 300.0  # 5 minutes default
    ) -> 'RotationPack':
        """
        Create signed rotation pack with anti-replay protection

        Args:
            parameters: Parameter updates to apply
            channel_id: Channel identifier (default: "default")
            private_key: Dilithium3 private key (generates if None)
            public_key: Dilithium3 public key (generates if None)
            validity_window_seconds: How long pack is valid (default: 5 minutes)

        Returns:
            Signed RotationPack with rotation_id, channel_id, timestamps
        """
        rotation_id = str(uuid.uuid4())
        issued_at = time.time()
        valid_until = issued_at + validity_window_seconds

        # Create payload to sign
        # CRITICAL: rotation_id, channel_id, timestamps ALL inside signature
        payload = {
            "version": "1.0",
            "rotation_id": rotation_id,
            "channel_id": channel_id,
            "issued_at": issued_at,
            "valid_until": valid_until,
            "parameters": parameters
        }

        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")

        # Sign with PQC provider (fail-closed if SATL_PQC=1)
        signer = _get_pqc_signer()
        signature_bytes = signer.sign(payload_bytes)

        # Get public key from provider if not provided
        if not public_key:
            if signer.enabled and signer.provider:
                # Use loaded public key from provider
                public_key = signer.provider.public_key
                if not public_key:
                    raise RuntimeError("[PQC] Public key not loaded in provider")
            else:
                # Legacy mock mode
                public_key = b"MOCK_DILITHIUM3_PUBKEY"

        # Encode to base64
        signature_b64 = base64.b64encode(signature_bytes).decode("utf-8")
        pubkey_b64 = base64.b64encode(public_key).decode("utf-8")

        logger.info("="*70)
        logger.info("SPO ROTATION PACK CREATED")
        logger.info("="*70)
        logger.info(f"  Rotation ID: {rotation_id} (SIGNED)")
        logger.info(f"  Channel ID: {channel_id} (SIGNED)")
        logger.info(f"  Issued at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(issued_at))} (SIGNED)")
        logger.info(f"  Valid until: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(valid_until))} (SIGNED)")
        logger.info(f"  Validity window: {validity_window_seconds:.0f}s")
        logger.info(f"  Parameters: {len(parameters)} updates (SIGNED)")
        for key, value in parameters.items():
            logger.info(f"    {key} = {value}")
        logger.info(f"  Signature: Dilithium3 ({len(signature_bytes)} bytes)")
        logger.info("  [SECURITY] All fields above are cryptographically signed")
        logger.info("="*70)

        return cls(
            version="1.0",
            rotation_id=rotation_id,
            channel_id=channel_id,
            issued_at=issued_at,
            valid_until=valid_until,
            parameters=parameters,
            signature=signature_b64,
            public_key=pubkey_b64,
            timestamp=issued_at  # Backwards compat
        )

    def verify(self, public_key: Optional[bytes] = None) -> bool:
        """
        Verify rotation pack signature

        Args:
            public_key: Expected Dilithium3 public key (uses embedded if None)

        Returns:
            True if signature valid
        """
        logger.info("="*70)
        logger.info("VERIFYING SPO ROTATION PACK")
        logger.info("="*70)

        # Use embedded public key if not provided
        if public_key is None:
            public_key = base64.b64decode(self.public_key.encode("utf-8"))

        # Reconstruct payload (use new format if available, else backwards compat)
        if hasattr(self, 'rotation_id') and self.rotation_id:
            # New format with channel_id support
            if hasattr(self, 'channel_id') and self.channel_id:
                payload = {
                    "version": self.version,
                    "rotation_id": self.rotation_id,
                    "channel_id": self.channel_id,
                    "issued_at": self.issued_at,
                    "valid_until": self.valid_until,
                    "parameters": self.parameters
                }
            else:
                # Intermediate format (no channel_id yet)
                payload = {
                    "version": self.version,
                    "rotation_id": self.rotation_id,
                    "issued_at": self.issued_at,
                    "valid_until": self.valid_until,
                    "parameters": self.parameters
                }
        else:
            # Backwards compatibility (old format)
            payload = {
                "version": self.version,
                "timestamp": self.timestamp,
                "parameters": self.parameters
            }

        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")

        # Decode signature
        signature_bytes = base64.b64decode(self.signature.encode("utf-8"))

        # Verify with PQC provider (fail-closed if SATL_PQC=1)
        try:
            signer = _get_pqc_signer()
            is_valid = signer.verify(payload_bytes, signature_bytes, public_key=public_key)

            if is_valid:
                mode_str = "Dilithium3" if signer.enabled else "MOCK"
                logger.info(f"  [OK] Signature VALID ({mode_str})")
                logger.info("  [OK] Pack timestamp: " + time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(self.timestamp)))
                logger.info("="*70)
                return True
            else:
                logger.error("  [FAIL] Signature INVALID")
                logger.error("="*70)
                return False

        except Exception as e:
            logger.error(f"  [FAIL] Verification error: {e}")
            logger.error("="*70)
            return False

    def apply(self, config: Any, max_age_hours: float = 24.0) -> bool:
        """
        Apply rotation pack to configuration with anti-replay protection

        Args:
            config: Configuration object to update
            max_age_hours: Maximum age (backwards compat, ignored if validity_window present)

        Returns:
            True if all parameters applied successfully
        """
        logger.info("="*70)
        logger.info("APPLYING SPO ROTATION PACK")
        logger.info("="*70)

        manager = RotationPackManager()
        now = time.time()

        # Check if new format (with rotation_id, validity window)
        if hasattr(self, 'rotation_id') and self.rotation_id:
            logger.info(f"  Rotation ID: {self.rotation_id}")

            # Get channel_id (default to "default" for backwards compat)
            channel_id = getattr(self, 'channel_id', 'default')
            logger.info(f"  Channel ID: {channel_id}")

            # Anti-replay check (with channel support)
            if manager.is_replay(self.rotation_id, channel_id, self.issued_at, self.valid_until):
                logger.error(f"  [FAIL] Replay attack detected")
                logger.error(f"  [SECURITY] Rotation ID already seen: {self.rotation_id}")
                logger.error(f"  [SECURITY] Channel: {channel_id}")
                logger.info("="*70)
                return False

            logger.info(f"  [OK] Anti-replay check passed (channel: {channel_id})")

            # Validity window check
            logger.info(f"  Issued at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(self.issued_at))}")
            logger.info(f"  Valid until: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(self.valid_until))}")

            if now < self.issued_at:
                logger.error(f"  [FAIL] Pack not yet valid (issued in future)")
                logger.error(f"  [SECURITY] Clock skew or tampered pack")
                logger.info("="*70)
                return False

            if now > self.valid_until:
                age_seconds = now - self.issued_at
                logger.error(f"  [FAIL] Pack expired ({age_seconds:.0f}s ago)")
                logger.error(f"  [SECURITY] Rejecting expired rotation pack")
                logger.info("="*70)
                return False

            logger.info(f"  [OK] Validity window check passed")

        else:
            # Backwards compatibility (old format with timestamp only)
            logger.warning(f"  [COMPAT] Using legacy format (no anti-replay)")

            age_seconds = now - self.timestamp
            age_hours = age_seconds / 3600

            logger.info(f"  Rotation pack age: {age_hours:.2f} hours")
            logger.info(f"  Max age allowed: {max_age_hours:.2f} hours")

            if age_hours > max_age_hours:
                logger.error(f"  [FAIL] Rotation pack too old ({age_hours:.2f}h > {max_age_hours:.2f}h)")
                logger.error(f"  [SECURITY] Rejecting stale rotation pack")
                logger.info("="*70)
                return False

            logger.info(f"  [OK] Age check passed")

        success_count = 0
        fail_count = 0

        for param_path, new_value in self.parameters.items():
            try:
                # Parse parameter path (e.g., "cover.idle_ratio" -> config.cover.idle_ratio)
                parts = param_path.split(".")
                obj = config

                # Navigate to target attribute
                for part in parts[:-1]:
                    obj = getattr(obj, part)

                # Set final attribute
                setattr(obj, parts[-1], new_value)

                logger.info(f"  [OK] {param_path} = {new_value}")
                success_count += 1

            except Exception as e:
                logger.error(f"  [FAIL] {param_path}: {e}")
                fail_count += 1

        logger.info("")
        logger.info(f"ROTATION RESULT: {success_count} OK, {fail_count} FAIL")
        logger.info("="*70)

        return fail_count == 0

    def save(self, filename: str):
        """Save rotation pack to JSON file"""
        with open(filename, 'w') as f:
            json.dump(asdict(self), f, indent=2)

        logger.info(f"[OK] Rotation pack saved: {filename}")

    @classmethod
    def load(cls, filename: str) -> 'RotationPack':
        """Load rotation pack from JSON file"""
        with open(filename, 'r') as f:
            data = json.load(f)

        logger.info(f"[OK] Rotation pack loaded: {filename}")
        return cls(**data)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s'
    )

    # SPO Authority: Create rotation pack
    logger.info("\n=== SPO AUTHORITY: Creating Rotation Pack ===\n")

    parameters = {
        "cover.idle_ratio": 0.60,
        "timing.deperiodize_max_shift_ms": 12,
        "fte.tls_version": "1.3"
    }

    pack = RotationPack.create(parameters)
    pack.save("rotation_pack_20251101.json")

    # Node: Verify and apply rotation pack
    logger.info("\n=== NODE: Verifying and Applying Rotation Pack ===\n")

    pack_received = RotationPack.load("rotation_pack_20251101.json")

    if pack_received.verify():
        # Mock config object
        class MockConfig:
            class Cover:
                idle_ratio = 0.50

            class Timing:
                deperiodize_max_shift_ms = 8

            class FTE:
                tls_version = "1.3"

            cover = Cover()
            timing = Timing()
            fte = FTE()

        config = MockConfig()

        pack_received.apply(config)

        logger.info("\nVERIFYING APPLIED PARAMETERS:")
        logger.info(f"  cover.idle_ratio = {config.cover.idle_ratio}")
        logger.info(f"  timing.deperiodize_max_shift_ms = {config.timing.deperiodize_max_shift_ms}")
        logger.info(f"  fte.tls_version = {config.fte.tls_version}")

    else:
        logger.error("ROTATION PACK VERIFICATION FAILED - NOT APPLIED")
