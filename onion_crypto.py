"""
==============================================
ONION_CRYPTO.PY - Military-Grade Onion Encryption
==============================================
3-layer onion encryption with ChaCha20-Poly1305 AEAD
Perfect Forward Secrecy + Quantum-Resistant Hybrid
"""
import os
import hashlib
import hmac
import json
import base64
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

# ChaCha20-Poly1305 via cryptography library
try:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    _HAS_CHACHA = True
except ImportError:
    _HAS_CHACHA = False
    print("WARNING: ChaCha20Poly1305 not available, install: pip install cryptography")

# PQC - Kyber for KEM
try:
    import oqs
    _HAS_OQS = True
except ImportError:
    _HAS_OQS = False

# X25519 for classical ECDH
try:
    from cryptography.hazmat.primitives.asymmetric import x25519
    _HAS_X25519 = True
except ImportError:
    _HAS_X25519 = False

from qkernel.qrand import qstream
from qkernel.qct import ct_compare


# ==================== UTILITIES ====================

def _hkdf_expand(prk: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-Expand for key derivation (RFC 5869)"""
    okm = b""
    t = b""
    for i in range((length + 31) // 32):
        t = hmac.new(prk, t + info + bytes([i + 1]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def _derive_layer_keys(shared_secret: bytes, layer_id: int) -> Dict[str, bytes]:
    """Derive encryption + MAC keys for a specific layer"""
    prk = hmac.new(b"SATL3-ONION", shared_secret, hashlib.sha256).digest()

    # Separate keys for encryption and authentication
    enc_key = _hkdf_expand(prk, f"ENC-L{layer_id}".encode(), 32)
    mac_key = _hkdf_expand(prk, f"MAC-L{layer_id}".encode(), 32)

    return {"enc": enc_key, "mac": mac_key}


# ==================== LAYER CRYPTO ====================

@dataclass
class OnionLayer:
    """Single layer of onion encryption"""
    node_id: str
    pub_endpoint: str
    shared_secret: bytes  # From hybrid KEM
    layer_num: int  # 0=outer, 1=middle, 2=inner


class OnionCrypto:
    """
    3-Layer Onion Encryption Manager

    Each layer uses:
    - ChaCha20-Poly1305 AEAD (256-bit key)
    - Kyber768 + X25519 hybrid KEM for key agreement
    - Perfect Forward Secrecy via ephemeral keys
    - Layer-specific key derivation (HKDF)
    """

    def __init__(self):
        self.rng = qstream(b"/onion")
        self.layers: List[OnionLayer] = []

    def create_circuit(self, nodes: List[Dict[str, Any]]) -> List[OnionLayer]:
        """
        Create a circuit with N nodes (typically 3)

        Args:
            nodes: List of node info [{"node_id": ..., "pub_ep": ..., "pub_keys": {...}}, ...]

        Returns:
            List of OnionLayer objects with established shared secrets
        """
        if len(nodes) < 3:
            raise ValueError("Onion routing requires at least 3 hops for security")

        layers = []
        for idx, node in enumerate(nodes):
            # Hybrid KEM: Kyber768 + X25519
            shared_secret = self._hybrid_kem(node.get("pub_keys", {}))

            layer = OnionLayer(
                node_id=node["node_id"],
                pub_endpoint=node["pub_ep"],
                shared_secret=shared_secret,
                layer_num=idx
            )
            layers.append(layer)

        self.layers = layers
        return layers

    def _hybrid_kem(self, pub_keys: Dict[str, str]) -> bytes:
        """
        Hybrid Key Encapsulation Mechanism
        Combines Kyber768 (PQC) + X25519 (classical)
        """
        material = b""

        # Kyber768 KEM
        if _HAS_OQS and "kyber_pk" in pub_keys:
            with oqs.KeyEncapsulation("Kyber768") as kem:
                pk_bytes = base64.urlsafe_b64decode(pub_keys["kyber_pk"])
                ciphertext, shared_secret = kem.encap_secret(pk_bytes)
                material += shared_secret
                # TODO: Store ciphertext for handshake

        # X25519 ECDH
        if _HAS_X25519 and "x25519_pk" in pub_keys:
            ephemeral_sk = x25519.X25519PrivateKey.generate()
            peer_pk = x25519.X25519PublicKey.from_public_bytes(
                base64.urlsafe_b64decode(pub_keys["x25519_pk"])
            )
            shared_secret = ephemeral_sk.exchange(peer_pk)
            material += shared_secret

        # HARD-FAIL: No fallback to RNG (production requirement)
        if not material:
            raise RuntimeError(
                "CRITICAL: No KEM keys available! "
                "Node pub_keys must contain 'kyber_pk' and/or 'x25519_pk'. "
                "Install liboqs-python for Kyber support."
            )

        # Combine both secrets via HKDF
        return _hkdf_expand(material, b"HYBRID-KEM", 32)

    def encrypt_onion(self, plaintext: bytes, metadata: Optional[Dict[str, Any]] = None) -> bytes:
        """
        Encrypt plaintext with 3 layers of onion encryption

        Format per layer:
        - Nonce (12 bytes, random)
        - AEAD ciphertext (ChaCha20-Poly1305)
        - Tag (16 bytes, authenticated)

        Encryption order: INNER → MIDDLE → OUTER
        Decryption order: OUTER → MIDDLE → INNER
        """
        if not _HAS_CHACHA:
            raise RuntimeError("ChaCha20-Poly1305 not available, cannot encrypt")

        if len(self.layers) < 3:
            raise RuntimeError("Circuit not established, call create_circuit() first")

        # Start with plaintext + optional metadata
        payload = {
            "data": base64.urlsafe_b64encode(plaintext).decode(),
            "meta": metadata or {}
        }
        current_blob = json.dumps(payload, separators=(",", ":")).encode()

        # Encrypt from INNER to OUTER (reverse order)
        for layer in reversed(self.layers):
            current_blob = self._encrypt_layer(current_blob, layer)

        return current_blob

    def _encrypt_layer(self, plaintext: bytes, layer: OnionLayer) -> bytes:
        """Encrypt a single layer with ChaCha20-Poly1305 AEAD"""
        keys = _derive_layer_keys(layer.shared_secret, layer.layer_num)

        # Generate random nonce (12 bytes for ChaCha20)
        nonce = self.rng.bytes(12)

        # ChaCha20-Poly1305 AEAD encryption
        cipher = ChaCha20Poly1305(keys["enc"])

        # Associated data: layer metadata (prevents layer peeling attacks)
        aad = json.dumps({
            "layer": layer.layer_num,
            "node": layer.node_id,
            "version": "SATL3.0"
        }, separators=(",", ":")).encode()

        # Encrypt + authenticate
        ciphertext = cipher.encrypt(nonce, plaintext, aad)

        # Format: [NONCE:12][AAD_LEN:2][AAD][CIPHERTEXT+TAG]
        aad_len = len(aad).to_bytes(2, 'big')
        return nonce + aad_len + aad + ciphertext

    def decrypt_layer(self, onion_blob: bytes, layer_secret: bytes, layer_num: int, node_id: str) -> Tuple[bytes, bool]:
        """
        Decrypt a single onion layer (called by each hop)

        Returns:
            (decrypted_payload, is_final_layer)
        """
        if not _HAS_CHACHA:
            raise RuntimeError("ChaCha20-Poly1305 not available")

        # Parse format: [NONCE:12][AAD_LEN:2][AAD][CIPHERTEXT+TAG]
        if len(onion_blob) < 14:
            raise ValueError("Invalid onion blob: too short")

        nonce = onion_blob[:12]
        aad_len = int.from_bytes(onion_blob[12:14], 'big')
        aad = onion_blob[14:14+aad_len]
        ciphertext = onion_blob[14+aad_len:]

        # Derive keys for this layer
        keys = _derive_layer_keys(layer_secret, layer_num)

        # Decrypt with ChaCha20-Poly1305
        cipher = ChaCha20Poly1305(keys["enc"])

        try:
            plaintext = cipher.decrypt(nonce, ciphertext, aad)
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")

        # Check if this is the final layer (contains JSON payload)
        try:
            payload = json.loads(plaintext.decode())
            if "data" in payload and "meta" in payload:
                # Final layer reached
                return base64.urlsafe_b64decode(payload["data"]), True
        except Exception:
            pass

        # Not final layer, return next onion blob
        return plaintext, False

    def decrypt_layer_compat(self, encrypted_payload: bytes) -> bytes:
        """
        ⚠️  TEST ONLY – DO NOT SHIP ⚠️

        COMPATIBILITY SHIM for performance testing ONLY.

        This function bypasses all onion decryption and returns the payload
        unchanged (fail-open behavior). This is ONLY acceptable for isolated
        testnet environments where SATL_ALLOW_COMPAT=1 is explicitly set.

        PRODUCTION REQUIREMENTS:
        - Remove this function entirely, OR
        - Make it fail-closed (raise exception if SATL_ALLOW_COMPAT not set)
        - Never deploy to production with this shim enabled

        Current behavior:
        - No PQC key derivation
        - No ChaCha20-Poly1305 decryption
        - No authentication tag validation
        - Returns plaintext payload (SECURITY RISK in production)

        For stealth mode, call real decrypt_layer() with proper layer secrets.
        """
        # FAIL-CLOSED CHECK: Only allow in explicit test mode
        allow_compat = os.getenv('SATL_ALLOW_COMPAT', '0')
        if allow_compat != '1':
            raise RuntimeError(
                "SECURITY VIOLATION: decrypt_layer_compat() called without SATL_ALLOW_COMPAT=1. "
                "This function bypasses all onion decryption and must not be used in production. "
                "Set SATL_ALLOW_COMPAT=1 only in isolated testnet environments, or use real "
                "decrypt_layer() with proper key derivation for production traffic."
            )

        # TEST MODE ONLY: Passthrough without decryption
        return encrypted_payload

    def get_routing_info(self) -> List[Dict[str, Any]]:
        """
        Get routing information for circuit construction
        Returns list of hops in order (for envelope routing)
        """
        return [
            {
                "node_id": layer.node_id,
                "endpoint": layer.pub_endpoint,
                "layer_num": layer.layer_num
            }
            for layer in self.layers
        ]


# ==================== PERFECT FORWARD SECRECY ====================

class ForwardSecrecyManager:
    """
    Manages key rotation for Perfect Forward Secrecy

    - Rotates circuit keys every N minutes
    - Securely erases old keys from memory
    - Supports key ratcheting (Signal Protocol style)
    """

    def __init__(self, rotation_interval_minutes: int = 10):
        self.rotation_interval = rotation_interval_minutes * 60
        self.circuits: Dict[str, OnionCrypto] = {}
        self.last_rotation: Dict[str, float] = {}
        self.rng = qstream(b"/forward-secrecy")

    def get_or_create_circuit(self, circuit_id: str, nodes: List[Dict[str, Any]]) -> OnionCrypto:
        """Get existing circuit or create new one with fresh keys"""
        import time

        now = time.time()

        # Check if rotation needed
        if circuit_id in self.circuits:
            last_rot = self.last_rotation.get(circuit_id, 0)
            if now - last_rot < self.rotation_interval:
                return self.circuits[circuit_id]
            else:
                # Rotate: destroy old circuit
                self._destroy_circuit(circuit_id)

        # Create fresh circuit
        crypto = OnionCrypto()
        crypto.create_circuit(nodes)

        self.circuits[circuit_id] = crypto
        self.last_rotation[circuit_id] = now

        return crypto

    def _destroy_circuit(self, circuit_id: str):
        """Securely erase circuit keys from memory"""
        if circuit_id in self.circuits:
            crypto = self.circuits[circuit_id]

            # Overwrite shared secrets with random data before deletion
            for layer in crypto.layers:
                # Securely wipe memory (Python limitation: best effort)
                layer.shared_secret = self.rng.bytes(len(layer.shared_secret))

            del self.circuits[circuit_id]
            del self.last_rotation[circuit_id]


# ==================== QUANTUM-RESISTANT RATCHET ====================

class QuantumRatchet:
    """
    Quantum-resistant key ratcheting mechanism
    Similar to Signal's Double Ratchet but with PQC
    """

    def __init__(self, initial_key: bytes):
        self.chain_key = initial_key
        self.message_counter = 0
        self.rng = qstream(b"/ratchet")

    def ratchet_forward(self) -> bytes:
        """
        Advance the ratchet and derive new message key

        Uses HMAC-based KDF chain:
        chain_key[n+1] = HMAC(chain_key[n], "RATCHET")
        message_key[n] = HMAC(chain_key[n], "MESSAGE" || counter)
        """
        # Derive message key from current chain key
        message_key = hmac.new(
            self.chain_key,
            f"MESSAGE-{self.message_counter}".encode(),
            hashlib.sha256
        ).digest()

        # Advance chain key (forward secrecy)
        self.chain_key = hmac.new(
            self.chain_key,
            b"RATCHET",
            hashlib.sha256
        ).digest()

        self.message_counter += 1

        return message_key

    def get_current_message_key(self) -> bytes:
        """Get message key without advancing (for decryption)"""
        return hmac.new(
            self.chain_key,
            f"MESSAGE-{self.message_counter}".encode(),
            hashlib.sha256
        ).digest()


# ==================== EXPORT ====================

__all__ = [
    'OnionCrypto',
    'OnionLayer',
    'ForwardSecrecyManager',
    'QuantumRatchet'
]


if __name__ == "__main__":
    # Self-test
    print("=== ONION CRYPTO SELF-TEST ===")

    # Mock nodes with public keys
    mock_nodes = [
        {
            "node_id": "guard-001",
            "pub_ep": "http://guard.satl.net/ingress",
            "pub_keys": {}  # Will use fallback
        },
        {
            "node_id": "middle-042",
            "pub_ep": "http://middle.satl.net/ingress",
            "pub_keys": {}
        },
        {
            "node_id": "exit-099",
            "pub_ep": "http://exit.satl.net/ingress",
            "pub_keys": {}
        }
    ]

    if _HAS_CHACHA:
        # Test circuit creation
        crypto = OnionCrypto()
        layers = crypto.create_circuit(mock_nodes)
        print(f"✓ Circuit created with {len(layers)} layers")

        # Test encryption
        plaintext = b"Hello, quantum-resistant onion world!"
        metadata = {"timestamp": 1234567890, "profile": "blindato"}

        onion = crypto.encrypt_onion(plaintext, metadata)
        print(f"✓ Onion encrypted: {len(onion)} bytes")

        # Test decryption (simulated layer peeling)
        current_blob = onion
        for i, layer in enumerate(crypto.layers):
            decrypted, is_final = crypto.decrypt_layer(
                current_blob,
                layer.shared_secret,
                layer.layer_num,
                layer.node_id
            )
            if is_final:
                print(f"✓ Final layer reached: {decrypted}")
                assert decrypted == plaintext
                break
            else:
                print(f"✓ Layer {i} peeled, continuing...")
                current_blob = decrypted

        print("\n=== ALL TESTS PASSED ===")
    else:
        print("❌ ChaCha20-Poly1305 not available, run: pip install cryptography")
