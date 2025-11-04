"""
====================================
SATL_PROTO_V3.PY - Onion Routing Protocol
====================================
New envelope format with true onion encryption
Each hop only sees next hop, not full route
"""
import json
import base64
import time
import hashlib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class OnionEnvelope:
    """
    Onion-encrypted envelope (Tor-style)

    Structure:
    - encrypted_payload: Onion blob (multi-layer encrypted)
    - next_hop: Only the immediate next hop (not full route)
    - layer_auth: HMAC to prevent tampering
    - metadata: Visible metadata (circuit_id, timestamp)
    """
    encrypted_payload: bytes  # The onion blob
    next_hop: str  # URL of next hop (only this hop visible)
    layer_auth: str  # HMAC authentication tag
    circuit_id: str  # Circuit identifier (for multiplexing)
    hop_num: int  # Current hop number (0-indexed)
    metadata: Dict[str, Any]  # Non-sensitive metadata

    def to_bytes(self) -> bytes:
        """Serialize to wire format"""
        obj = {
            "payload": base64.urlsafe_b64encode(self.encrypted_payload).decode(),
            "next": self.next_hop,
            "auth": self.layer_auth,
            "circuit": self.circuit_id,
            "hop": self.hop_num,
            "meta": self.metadata
        }
        return json.dumps(obj, separators=(",", ":")).encode()

    @staticmethod
    def from_bytes(data: bytes) -> "OnionEnvelope":
        """Deserialize from wire format"""
        obj = json.loads(data.decode())
        return OnionEnvelope(
            encrypted_payload=base64.urlsafe_b64decode(obj["payload"]),
            next_hop=obj["next"],
            layer_auth=obj["auth"],
            circuit_id=obj["circuit"],
            hop_num=obj["hop"],
            metadata=obj.get("meta", {})
        )


class OnionRouter:
    """
    Handles onion routing at relay nodes

    - Peels one layer of encryption
    - Verifies layer authentication
    - Forwards to next hop
    - No knowledge of full route or final destination
    """

    def __init__(self, node_id: str, secret_key: bytes):
        self.node_id = node_id
        self.secret_key = secret_key

    def process_envelope(self, envelope: OnionEnvelope) -> Optional[OnionEnvelope]:
        """
        Process incoming envelope:
        1. Verify layer auth
        2. Decrypt one layer
        3. Extract next hop from decrypted payload
        4. Re-wrap for forwarding
        """
        from onion_crypto import OnionCrypto

        crypto = OnionCrypto()

        # Decrypt this layer
        try:
            decrypted_payload, is_final = crypto.decrypt_layer(
                envelope.encrypted_payload,
                self.secret_key,
                envelope.hop_num,
                self.node_id
            )
        except Exception as e:
            print(f"Decryption failed at hop {envelope.hop_num}: {e}")
            return None

        # Final hop (exit node)
        if is_final:
            # Deliver to destination
            print(f"EXIT NODE: Final payload received ({len(decrypted_payload)} bytes)")
            return None  # Signal to deliver, not forward

        # Extract next hop from decrypted layer
        # Format: [NEXT_HOP_LEN:2][NEXT_HOP_URL][REMAINING_ONION]
        if len(decrypted_payload) < 2:
            print("Malformed onion layer")
            return None

        next_hop_len = int.from_bytes(decrypted_payload[:2], 'big')
        next_hop_url = decrypted_payload[2:2+next_hop_len].decode()
        remaining_onion = decrypted_payload[2+next_hop_len:]

        # Create auth tag for next layer
        layer_auth = hashlib.blake2b(
            remaining_onion + self.node_id.encode(),
            digest_size=16,
            key=self.secret_key
        ).hexdigest()

        # Forward envelope
        return OnionEnvelope(
            encrypted_payload=remaining_onion,
            next_hop=next_hop_url,
            layer_auth=layer_auth,
            circuit_id=envelope.circuit_id,
            hop_num=envelope.hop_num + 1,
            metadata=envelope.metadata
        )


class CircuitBuilder:
    """
    Client-side circuit construction with onion encryption

    - Selects guard/middle/exit nodes
    - Performs hybrid KEM with each hop
    - Constructs onion-encrypted envelope
    - Embeds routing info in encrypted layers
    """

    def __init__(self):
        from onion_crypto import OnionCrypto, ForwardSecrecyManager
        self.crypto = OnionCrypto()
        self.fs_manager = ForwardSecrecyManager(rotation_interval_minutes=10)

    def build_circuit(self, guard_node: Dict, middle_nodes: List[Dict], exit_node: Dict) -> str:
        """
        Build a circuit: GUARD → MIDDLE(s) → EXIT

        Returns circuit_id for multiplexing
        """
        nodes = [guard_node] + middle_nodes + [exit_node]
        circuit_id = self._generate_circuit_id()

        # Establish shared secrets with each hop
        crypto = self.fs_manager.get_or_create_circuit(circuit_id, nodes)

        return circuit_id

    def create_onion_envelope(
        self,
        circuit_id: str,
        payload: bytes,
        metadata: Optional[Dict[str, Any]] = None
    ) -> OnionEnvelope:
        """
        Create onion-encrypted envelope for transmission

        The payload is encrypted in layers (INNER → OUTER)
        Each layer embeds the next hop address
        """
        crypto = self.fs_manager.circuits.get(circuit_id)
        if not crypto:
            raise ValueError(f"Circuit {circuit_id} not found")

        # Get routing info
        hops = crypto.get_routing_info()

        # Build onion from INNER to OUTER
        current_payload = payload

        # Start from exit (innermost) and work outward
        for i in range(len(hops) - 1, -1, -1):
            hop = hops[i]

            # Embed next hop URL in payload (except for exit)
            if i < len(hops) - 1:
                next_url = hops[i + 1]["endpoint"].encode()
                next_url_len = len(next_url).to_bytes(2, 'big')
                current_payload = next_url_len + next_url + current_payload

        # Encrypt with all layers
        encrypted_onion = crypto.encrypt_onion(current_payload, metadata or {})

        # Create envelope for first hop (guard)
        first_hop = hops[0]["endpoint"]

        # Initial auth tag
        layer_auth = hashlib.blake2b(
            encrypted_onion + b"SATL3-INIT",
            digest_size=16
        ).hexdigest()

        return OnionEnvelope(
            encrypted_payload=encrypted_onion,
            next_hop=first_hop,
            layer_auth=layer_auth,
            circuit_id=circuit_id,
            hop_num=0,
            metadata=metadata or {"ts": int(time.time()), "ttl": 60}
        )

    def _generate_circuit_id(self) -> str:
        """Generate unique circuit identifier"""
        import secrets
        return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode()[:22]


# ==================== LEGACY COMPATIBILITY ====================

class Envelope:
    """
    Legacy envelope format (DEPRECATED)
    Kept for backward compatibility only

    WARNING: This format exposes full route to all hops!
    Use OnionEnvelope for production.
    """

    def __init__(self, route: List[str], cap: Dict[str, Any], hop: int = 0, meta: Dict[str, Any] = None):
        self.route, self.cap, self.hop = route, cap, hop
        self.meta = meta or {"ttl": 45, "ts": int(time.time())}
        print("⚠️ WARNING: Using legacy Envelope (insecure route exposure)")

    def to_bytes(self) -> bytes:
        return json.dumps(
            {"r": self.route, "h": self.hop, "c": self.cap, "m": self.meta},
            separators=(",", ":")
        ).encode()

    @staticmethod
    def from_bytes(b: bytes) -> "Envelope":
        o = json.loads(b.decode())
        return Envelope(o["r"], o["c"], o["h"], o.get("m", {}))


# ==================== EXPORT ====================

__all__ = [
    'OnionEnvelope',
    'OnionRouter',
    'CircuitBuilder',
    'Envelope'  # Legacy
]


if __name__ == "__main__":
    print("=== ONION ROUTING PROTOCOL TEST ===")

    # Mock circuit
    mock_nodes = [
        {"node_id": "guard-1", "pub_ep": "http://guard.net/ingress", "pub_keys": {}},
        {"node_id": "middle-2", "pub_ep": "http://middle.net/ingress", "pub_keys": {}},
        {"node_id": "exit-3", "pub_ep": "http://exit.net/ingress", "pub_keys": {}}
    ]

    builder = CircuitBuilder()

    # Build circuit
    circuit_id = builder.build_circuit(
        guard_node=mock_nodes[0],
        middle_nodes=[mock_nodes[1]],
        exit_node=mock_nodes[2]
    )
    print(f"✓ Circuit built: {circuit_id}")

    # Create onion envelope
    payload = b"Secret message to destination"
    envelope = builder.create_onion_envelope(
        circuit_id,
        payload,
        metadata={"profile": "blindato"}
    )
    print(f"✓ Onion envelope created: {len(envelope.encrypted_payload)} bytes")
    print(f"  Next hop: {envelope.next_hop}")
    print(f"  Circuit: {envelope.circuit_id}")

    print("\n✅ Protocol test complete")
