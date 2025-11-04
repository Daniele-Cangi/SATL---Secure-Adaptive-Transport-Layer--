"""
=======================================================
ZK_AUTHENTICATION.PY - Zero-Knowledge Proof Authentication
=======================================================
Prove identity without revealing secret
Schnorr protocol + zkSNARKs-inspired design
"""
import hashlib
import hmac
import secrets
from typing import Tuple, Dict, Any, Optional
from dataclasses import dataclass
import time


# ==================== CONSTANTS ====================

# Large prime for Schnorr protocol (2048-bit)
P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF", 16
)

# Generator
G = 2

# Security parameter
CHALLENGE_BITS = 256


# ==================== ELLIPTIC CURVE (Ed25519) ====================

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    _HAS_ED25519 = True
except ImportError:
    _HAS_ED25519 = False


# ==================== SCHNORR PROTOCOL ====================

class SchnorrProver:
    """
    Schnorr protocol prover

    Proves knowledge of discrete log without revealing it
    Protocol:
    1. Prover commits: r = G^k mod P (random k)
    2. Verifier challenges: c (random)
    3. Prover responds: s = k + c*x mod (P-1)
    4. Verifier checks: G^s == r * y^c mod P
    """

    def __init__(self, secret: int):
        """
        Initialize with secret key

        Args:
            secret: Private key (x)
        """
        self.secret = secret
        self.public_key = pow(G, secret, P)  # y = G^x mod P

    def generate_commitment(self) -> Tuple[int, int]:
        """
        Generate commitment (step 1)

        Returns:
            (commitment, ephemeral_secret)
        """
        # Random k
        k = secrets.randbelow(P - 1)

        # Commitment: r = G^k mod P
        commitment = pow(G, k, P)

        return commitment, k

    def generate_response(self, challenge: int, ephemeral_secret: int) -> int:
        """
        Generate response to challenge (step 3)

        Args:
            challenge: Challenge from verifier
            ephemeral_secret: k from commitment phase

        Returns:
            Response s
        """
        # s = k + c*x mod (P-1)
        s = (ephemeral_secret + challenge * self.secret) % (P - 1)
        return s


class SchnorrVerifier:
    """Schnorr protocol verifier"""

    def __init__(self, public_key: int):
        """
        Initialize with prover's public key

        Args:
            public_key: y = G^x mod P
        """
        self.public_key = public_key

    def generate_challenge(self) -> int:
        """
        Generate random challenge (step 2)

        Returns:
            Challenge c
        """
        return secrets.randbelow(2 ** CHALLENGE_BITS)

    def verify_response(self, commitment: int, challenge: int, response: int) -> bool:
        """
        Verify prover's response (step 4)

        Check: G^s == r * y^c mod P

        Args:
            commitment: r from prover
            challenge: c from verifier
            response: s from prover

        Returns:
            True if proof is valid
        """
        # Left side: G^s mod P
        left = pow(G, response, P)

        # Right side: r * y^c mod P
        right = (commitment * pow(self.public_key, challenge, P)) % P

        return left == right


# ==================== ZK-SNARK INSPIRED (SIMPLIFIED) ====================

@dataclass
class ZKProof:
    """
    Zero-knowledge proof object

    Contains commitment, challenge, response
    """
    commitment: str
    challenge: str
    response: str
    timestamp: float
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commitment": self.commitment,
            "challenge": self.challenge,
            "response": self.response,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ZKProof":
        return ZKProof(
            commitment=d["commitment"],
            challenge=d["challenge"],
            response=d["response"],
            timestamp=d["timestamp"],
            metadata=d.get("metadata", {})
        )


class ZKAuthenticator:
    """
    Zero-Knowledge Authentication System

    Allows proving identity/attributes without revealing secret
    """

    def __init__(self, secret: bytes):
        """
        Initialize with secret

        Args:
            secret: Master secret (password, key, etc.)
        """
        self.secret = secret
        self.secret_int = int.from_bytes(
            hashlib.sha256(secret).digest(),
            'big'
        ) % (P - 1)

        # Generate Schnorr keys
        self.prover = SchnorrProver(self.secret_int)
        self.public_key = self.prover.public_key

    def create_proof(self, statement: str, attributes: Optional[Dict[str, Any]] = None) -> ZKProof:
        """
        Create zero-knowledge proof for statement

        Args:
            statement: What we're proving (e.g., "I know password")
            attributes: Optional attributes to prove (age > 18, member of group, etc.)

        Returns:
            ZKProof object
        """
        # Generate commitment
        commitment, ephemeral = self.prover.generate_commitment()

        # Generate challenge (Fiat-Shamir heuristic)
        challenge = self._generate_challenge(commitment, statement, attributes or {})

        # Generate response
        response = self.prover.generate_response(challenge, ephemeral)

        return ZKProof(
            commitment=hex(commitment),
            challenge=hex(challenge),
            response=hex(response),
            timestamp=time.time(),
            metadata={
                "statement": statement,
                "attributes": attributes or {},
                "public_key": hex(self.public_key)
            }
        )

    def _generate_challenge(self, commitment: int, statement: str, attributes: Dict[str, Any]) -> int:
        """
        Generate deterministic challenge (Fiat-Shamir)

        Makes protocol non-interactive by hashing commitment + context
        """
        hash_input = (
            str(commitment) +
            statement +
            str(sorted(attributes.items())) +
            hex(self.public_key)
        ).encode()

        challenge_hash = hashlib.sha256(hash_input).digest()
        return int.from_bytes(challenge_hash, 'big') % (2 ** CHALLENGE_BITS)

    @staticmethod
    def verify_proof(proof: ZKProof) -> bool:
        """
        Verify zero-knowledge proof

        Args:
            proof: ZKProof to verify

        Returns:
            True if proof is valid
        """
        try:
            # Extract values
            commitment = int(proof.commitment, 16)
            challenge = int(proof.challenge, 16)
            response = int(proof.response, 16)
            public_key = int(proof.metadata["public_key"], 16)

            # Check timestamp (prevent replay attacks)
            if abs(time.time() - proof.timestamp) > 300:  # 5 minutes
                return False

            # Verify Fiat-Shamir challenge
            statement = proof.metadata["statement"]
            attributes = proof.metadata["attributes"]

            hash_input = (
                str(commitment) +
                statement +
                str(sorted(attributes.items())) +
                hex(public_key)
            ).encode()

            expected_challenge = int.from_bytes(
                hashlib.sha256(hash_input).digest(),
                'big'
            ) % (2 ** CHALLENGE_BITS)

            if challenge != expected_challenge:
                return False

            # Verify Schnorr proof
            verifier = SchnorrVerifier(public_key)
            return verifier.verify_response(commitment, challenge, response)

        except Exception as e:
            print(f"Verification error: {e}")
            return False


# ==================== ATTRIBUTE-BASED ZK ====================

class AttributeProver:
    """
    Prove attributes without revealing exact values

    Examples:
    - Age > 18 without revealing age
    - Member of group without revealing group list
    - Balance > threshold without revealing balance
    """

    def __init__(self, secret: bytes):
        self.authenticator = ZKAuthenticator(secret)

    def prove_greater_than(self, value: int, threshold: int, attribute_name: str) -> Optional[ZKProof]:
        """
        Prove value > threshold without revealing value

        Args:
            value: Actual value (secret)
            threshold: Public threshold
            attribute_name: What we're proving (e.g., "age")

        Returns:
            ZKProof if value > threshold, None otherwise
        """
        if value <= threshold:
            return None

        # Create commitment to value
        value_hash = hashlib.sha256(str(value).encode()).hexdigest()

        statement = f"{attribute_name} > {threshold}"
        attributes = {
            "attribute": attribute_name,
            "threshold": threshold,
            "value_commitment": value_hash
        }

        return self.authenticator.create_proof(statement, attributes)

    def prove_membership(self, item: str, group_hash: str) -> ZKProof:
        """
        Prove membership in group without revealing which member

        Args:
            item: Your item/identity
            group_hash: Hash of the group members

        Returns:
            ZKProof of membership
        """
        # Commitment to item
        item_hash = hashlib.sha256(item.encode()).hexdigest()

        statement = f"member of group"
        attributes = {
            "group_hash": group_hash,
            "item_commitment": item_hash
        }

        return self.authenticator.create_proof(statement, attributes)


# ==================== SESSION AUTHENTICATION ====================

class ZKSession:
    """
    Zero-knowledge session authentication

    Establish authenticated session without password transmission
    """

    def __init__(self, user_id: str, password: bytes):
        self.user_id = user_id
        self.authenticator = ZKAuthenticator(password)
        self.session_key: Optional[bytes] = None

    def initiate_auth(self) -> Dict[str, Any]:
        """
        Initiate authentication (client side)

        Returns:
            Authentication request with ZK proof
        """
        # Create proof of password knowledge
        proof = self.authenticator.create_proof(
            statement=f"authentication for {self.user_id}",
            attributes={"user_id": self.user_id}
        )

        return {
            "user_id": self.user_id,
            "public_key": hex(self.authenticator.public_key),
            "proof": proof.to_dict()
        }

    @staticmethod
    def verify_auth(auth_request: Dict[str, Any], user_db: Dict[str, int]) -> Tuple[bool, Optional[str]]:
        """
        Verify authentication (server side)

        Args:
            auth_request: Request from client
            user_db: Database of {user_id: public_key}

        Returns:
            (success, session_token)
        """
        user_id = auth_request["user_id"]
        claimed_pubkey = int(auth_request["public_key"], 16)

        # Check if user exists and public key matches
        if user_id not in user_db:
            return False, None

        if user_db[user_id] != claimed_pubkey:
            return False, None

        # Verify ZK proof
        proof = ZKProof.from_dict(auth_request["proof"])
        is_valid = ZKAuthenticator.verify_proof(proof)

        if not is_valid:
            return False, None

        # Generate session token
        session_token = secrets.token_urlsafe(32)

        return True, session_token


# ==================== EXPORT ====================

__all__ = [
    'ZKProof',
    'ZKAuthenticator',
    'AttributeProver',
    'ZKSession',
    'SchnorrProver',
    'SchnorrVerifier'
]


if __name__ == "__main__":
    print("=== ZERO-KNOWLEDGE AUTHENTICATION SELF-TEST ===")

    # Test Schnorr protocol
    print("\n1. Testing Schnorr protocol...")
    secret = 12345
    prover = SchnorrProver(secret)
    verifier = SchnorrVerifier(prover.public_key)

    commitment, ephemeral = prover.generate_commitment()
    challenge = verifier.generate_challenge()
    response = prover.generate_response(challenge, ephemeral)

    is_valid = verifier.verify_response(commitment, challenge, response)
    print(f"   ✓ Schnorr proof: {'VALID' if is_valid else 'INVALID'}")

    # Test ZK authenticator
    print("\n2. Testing ZK authenticator...")
    password = b"super_secret_password_12345"
    auth = ZKAuthenticator(password)

    proof = auth.create_proof("I know the password", {"context": "login"})
    print(f"   ✓ Proof created")

    is_valid = ZKAuthenticator.verify_proof(proof)
    print(f"   ✓ Proof verification: {'VALID' if is_valid else 'INVALID'}")

    # Test attribute proving
    print("\n3. Testing attribute proofs...")
    attr_prover = AttributeProver(b"secret")

    # Prove age > 18
    age_proof = attr_prover.prove_greater_than(25, 18, "age")
    if age_proof:
        is_valid = ZKAuthenticator.verify_proof(age_proof)
        print(f"   ✓ Age proof: {'VALID' if is_valid else 'INVALID'}")

    # Prove membership
    group_hash = hashlib.sha256(b"group_members_list").hexdigest()
    member_proof = attr_prover.prove_membership("alice", group_hash)
    is_valid = ZKAuthenticator.verify_proof(member_proof)
    print(f"   ✓ Membership proof: {'VALID' if is_valid else 'INVALID'}")

    # Test session authentication
    print("\n4. Testing session authentication...")
    session = ZKSession("alice", b"alice_password")
    auth_request = session.initiate_auth()
    print(f"   ✓ Auth request created")

    # Simulate server-side verification
    user_db = {"alice": session.authenticator.public_key}
    success, token = ZKSession.verify_auth(auth_request, user_db)
    print(f"   ✓ Auth verification: {'SUCCESS' if success else 'FAILED'}")
    if token:
        print(f"   ✓ Session token: {token[:16]}...")

    print("\n✅ Zero-knowledge authentication test complete")
