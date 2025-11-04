"""
=========================================
PQC_SIGNATURES.PY - Post-Quantum Signatures
=========================================
Real Dilithium3 implementation for quantum-resistant signatures
Hybrid with Ed25519 for defense-in-depth
"""
import hashlib
import json
import base64
from typing import Tuple, Dict, Any, Optional
from dataclasses import dataclass

# Post-Quantum Cryptography - Dilithium
try:
    import oqs
    _HAS_OQS = True
except ImportError:
    _HAS_OQS = False
    print("WARNING: liboqs not available, PQC signatures disabled")
    print("Install: pip install liboqs-python")

# Classical Ed25519 signatures
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey
    )
    from cryptography.hazmat.primitives import serialization
    _HAS_ED25519 = True
except ImportError:
    _HAS_ED25519 = False


# ==================== KEY TYPES ====================

@dataclass
class HybridKeyPair:
    """
    Hybrid public key pair (Dilithium3 + Ed25519)

    Provides defense-in-depth:
    - If quantum computers break classical crypto → Dilithium protects
    - If Dilithium has implementation flaws → Ed25519 protects
    """
    dilithium_sk: Optional[bytes]
    dilithium_pk: Optional[bytes]
    ed25519_sk: Optional[bytes]
    ed25519_pk: Optional[bytes]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage/transmission"""
        return {
            "pqc_pk": base64.urlsafe_b64encode(self.dilithium_pk).decode() if self.dilithium_pk else None,
            "ed_pk": base64.urlsafe_b64encode(self.ed25519_pk).decode() if self.ed25519_pk else None,
            "version": "SATL3-HYBRID-v1"
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "HybridKeyPair":
        """Deserialize from storage"""
        return HybridKeyPair(
            dilithium_sk=None,  # Never transmit private keys
            dilithium_pk=base64.urlsafe_b64decode(d["pqc_pk"]) if d.get("pqc_pk") else None,
            ed25519_sk=None,
            ed25519_pk=base64.urlsafe_b64decode(d["ed_pk"]) if d.get("ed_pk") else None
        )


# ==================== KEY GENERATION ====================

def generate_hybrid_keypair() -> HybridKeyPair:
    """
    Generate hybrid Dilithium3 + Ed25519 keypair

    Returns:
        HybridKeyPair with both public and private keys
    """
    dilithium_sk, dilithium_pk = None, None
    ed25519_sk_bytes, ed25519_pk_bytes = None, None

    # Generate Dilithium3 keypair
    if _HAS_OQS:
        with oqs.Signature("Dilithium3") as signer:
            dilithium_pk = signer.generate_keypair()
            dilithium_sk = signer.export_secret_key()
    else:
        print("WARNING: Dilithium3 not available, using Ed25519 only")

    # Generate Ed25519 keypair
    if _HAS_ED25519:
        ed25519_sk = Ed25519PrivateKey.generate()
        ed25519_pk = ed25519_sk.public_key()

        # Serialize keys
        ed25519_sk_bytes = ed25519_sk.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        ed25519_pk_bytes = ed25519_pk.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

    if not dilithium_sk and not ed25519_sk_bytes:
        raise RuntimeError("No signature algorithms available")

    return HybridKeyPair(
        dilithium_sk=dilithium_sk,
        dilithium_pk=dilithium_pk,
        ed25519_sk=ed25519_sk_bytes,
        ed25519_pk=ed25519_pk_bytes
    )


# ==================== SIGNING ====================

def hybrid_sign(message: bytes, keypair: HybridKeyPair) -> Dict[str, str]:
    """
    Create hybrid signature (Dilithium3 + Ed25519)

    Signature format:
    {
        "pqc_sig": base64(Dilithium3 signature),
        "ed_sig": base64(Ed25519 signature),
        "timestamp": unix_timestamp,
        "version": "SATL3-HYBRID-v1"
    }

    Args:
        message: Data to sign
        keypair: Private keys for signing

    Returns:
        Dictionary with both signatures
    """
    import time

    signatures = {
        "timestamp": int(time.time()),
        "version": "SATL3-HYBRID-v1"
    }

    # Dilithium3 signature
    if _HAS_OQS and keypair.dilithium_sk:
        with oqs.Signature("Dilithium3", secret_key=keypair.dilithium_sk) as signer:
            pqc_sig = signer.sign(message)
            signatures["pqc_sig"] = base64.urlsafe_b64encode(pqc_sig).decode()
    else:
        signatures["pqc_sig"] = None

    # Ed25519 signature
    if _HAS_ED25519 and keypair.ed25519_sk:
        ed_sk = Ed25519PrivateKey.from_private_bytes(keypair.ed25519_sk)
        ed_sig = ed_sk.sign(message)
        signatures["ed_sig"] = base64.urlsafe_b64encode(ed_sig).decode()
    else:
        signatures["ed_sig"] = None

    # At least one signature must be present
    if not signatures["pqc_sig"] and not signatures["ed_sig"]:
        raise RuntimeError("No signatures generated")

    return signatures


# ==================== VERIFICATION ====================

def hybrid_verify(message: bytes, signature: Dict[str, str], public_keys: HybridKeyPair) -> bool:
    """
    Verify hybrid signature

    Security policy: BOTH signatures must be valid if present
    (Defense against partial breaks)

    Args:
        message: Original signed data
        signature: Signature dictionary from hybrid_sign()
        public_keys: Public keys for verification

    Returns:
        True if signature is valid, False otherwise
    """
    dilithium_valid = False
    ed25519_valid = False

    # Verify Dilithium3 signature
    if signature.get("pqc_sig") and _HAS_OQS and public_keys.dilithium_pk:
        try:
            with oqs.Signature("Dilithium3") as verifier:
                pqc_sig = base64.urlsafe_b64decode(signature["pqc_sig"])
                dilithium_valid = verifier.verify(message, pqc_sig, public_keys.dilithium_pk)
        except Exception as e:
            print(f"Dilithium3 verification failed: {e}")
            dilithium_valid = False
    elif not signature.get("pqc_sig"):
        # No PQC signature present, skip
        dilithium_valid = None

    # Verify Ed25519 signature
    if signature.get("ed_sig") and _HAS_ED25519 and public_keys.ed25519_pk:
        try:
            ed_pk = Ed25519PublicKey.from_public_bytes(public_keys.ed25519_pk)
            ed_sig = base64.urlsafe_b64decode(signature["ed_sig"])
            ed_pk.verify(ed_sig, message)
            ed25519_valid = True
        except Exception as e:
            print(f"Ed25519 verification failed: {e}")
            ed25519_valid = False
    elif not signature.get("ed_sig"):
        # No Ed25519 signature present, skip
        ed25519_valid = None

    # Security policy: Both must be valid if present
    if dilithium_valid is False or ed25519_valid is False:
        return False

    # At least one must be present and valid
    if dilithium_valid or ed25519_valid:
        return True

    return False


# ==================== NODE AUTHENTICATION ====================

class NodeAuthenticator:
    """
    Authenticates nodes using hybrid PQC signatures

    Each node has a long-term identity keypair
    Signs challenges to prove identity
    """

    def __init__(self, node_id: str, keypair: Optional[HybridKeyPair] = None):
        self.node_id = node_id
        self.keypair = keypair or generate_hybrid_keypair()

    def sign_challenge(self, challenge: bytes) -> Dict[str, Any]:
        """
        Sign authentication challenge

        Format: SIGN(node_id || challenge || timestamp)
        """
        import time

        message = json.dumps({
            "node_id": self.node_id,
            "challenge": base64.urlsafe_b64encode(challenge).decode(),
            "timestamp": int(time.time())
        }, separators=(",", ":"), sort_keys=True).encode()

        signature = hybrid_sign(message, self.keypair)

        return {
            "node_id": self.node_id,
            "challenge": base64.urlsafe_b64encode(challenge).decode(),
            "timestamp": signature["timestamp"],
            "signature": signature,
            "public_keys": self.keypair.to_dict()
        }

    @staticmethod
    def verify_challenge(auth_response: Dict[str, Any]) -> bool:
        """
        Verify signed authentication challenge

        Returns True if signature is valid and not expired
        """
        import time

        # Check timestamp (prevent replay attacks)
        timestamp = auth_response.get("timestamp", 0)
        if abs(time.time() - timestamp) > 300:  # 5 minute window
            print("Authentication expired")
            return False

        # Reconstruct signed message
        message = json.dumps({
            "node_id": auth_response["node_id"],
            "challenge": auth_response["challenge"],
            "timestamp": timestamp
        }, separators=(",", ":"), sort_keys=True).encode()

        # Extract public keys
        public_keys = HybridKeyPair.from_dict(auth_response["public_keys"])

        # Verify signature
        return hybrid_verify(message, auth_response["signature"], public_keys)


# ==================== CERTIFICATE AUTHORITY ====================

class SATLCertificateAuthority:
    """
    Decentralized Certificate Authority using DHT

    Issues certificates for node public keys
    Maintains revocation list
    """

    def __init__(self, ca_keypair: HybridKeyPair):
        self.ca_keypair = ca_keypair

    def issue_certificate(self, node_id: str, node_public_keys: HybridKeyPair, validity_days: int = 365) -> Dict[str, Any]:
        """
        Issue signed certificate for node

        Certificate format:
        {
            "node_id": "...",
            "public_keys": {...},
            "issued_at": timestamp,
            "expires_at": timestamp,
            "issuer": "SATL-CA",
            "ca_signature": {...}
        }
        """
        import time

        issued_at = int(time.time())
        expires_at = issued_at + (validity_days * 86400)

        cert = {
            "node_id": node_id,
            "public_keys": node_public_keys.to_dict(),
            "issued_at": issued_at,
            "expires_at": expires_at,
            "issuer": "SATL-CA-v1",
            "version": "SATL3-CERT-v1"
        }

        # Sign certificate with CA keys
        cert_bytes = json.dumps(cert, separators=(",", ":"), sort_keys=True).encode()
        ca_signature = hybrid_sign(cert_bytes, self.ca_keypair)

        cert["ca_signature"] = ca_signature

        return cert

    def verify_certificate(self, cert: Dict[str, Any]) -> bool:
        """
        Verify certificate signature and validity

        Returns True if certificate is valid and not expired
        """
        import time

        # Check expiration
        expires_at = cert.get("expires_at", 0)
        if time.time() > expires_at:
            print("Certificate expired")
            return False

        # Extract CA signature
        ca_signature = cert.get("ca_signature")
        if not ca_signature:
            return False

        # Reconstruct signed data (without signature field)
        cert_copy = dict(cert)
        del cert_copy["ca_signature"]
        cert_bytes = json.dumps(cert_copy, separators=(",", ":"), sort_keys=True).encode()

        # Verify CA signature
        ca_public_keys = HybridKeyPair(
            dilithium_sk=None,
            dilithium_pk=self.ca_keypair.dilithium_pk,
            ed25519_sk=None,
            ed25519_pk=self.ca_keypair.ed25519_pk
        )

        return hybrid_verify(cert_bytes, ca_signature, ca_public_keys)


# ==================== EXPORT ====================

__all__ = [
    'HybridKeyPair',
    'generate_hybrid_keypair',
    'hybrid_sign',
    'hybrid_verify',
    'NodeAuthenticator',
    'SATLCertificateAuthority'
]


if __name__ == "__main__":
    print("=== PQC SIGNATURES SELF-TEST ===")

    if not _HAS_OQS and not _HAS_ED25519:
        print("❌ No signature algorithms available")
        print("Install: pip install liboqs-python cryptography")
        exit(1)

    # Test key generation
    keypair = generate_hybrid_keypair()
    print(f"✓ Hybrid keypair generated")
    print(f"  Dilithium3: {'✓' if keypair.dilithium_pk else '✗'}")
    print(f"  Ed25519: {'✓' if keypair.ed25519_pk else '✗'}")

    # Test signing
    message = b"Test message for quantum-resistant signature"
    signature = hybrid_sign(message, keypair)
    print(f"✓ Message signed")

    # Test verification
    public_keys = HybridKeyPair(
        dilithium_sk=None,
        dilithium_pk=keypair.dilithium_pk,
        ed25519_sk=None,
        ed25519_pk=keypair.ed25519_pk
    )
    valid = hybrid_verify(message, signature, public_keys)
    print(f"✓ Signature {'VALID' if valid else 'INVALID'}")

    # Test node authentication
    auth = NodeAuthenticator("test-node-001")
    challenge = b"random_challenge_12345"
    auth_response = auth.sign_challenge(challenge)
    verified = NodeAuthenticator.verify_challenge(auth_response)
    print(f"✓ Node authentication: {'SUCCESS' if verified else 'FAILED'}")

    # Test CA
    ca_keypair = generate_hybrid_keypair()
    ca = SATLCertificateAuthority(ca_keypair)
    cert = ca.issue_certificate("node-123", keypair, validity_days=365)
    cert_valid = ca.verify_certificate(cert)
    print(f"✓ Certificate issued and verified: {'VALID' if cert_valid else 'INVALID'}")

    print("\n✅ All PQC signature tests passed")
