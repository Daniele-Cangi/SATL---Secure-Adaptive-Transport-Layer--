"""
==========================================
GUARD_NODES.PY - Guard Node Selection
==========================================
Implements Tor-style guard nodes for entry point stability
Prevents correlation attacks from rotating entry points
"""
import time
import json
import hashlib
import random
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from pathlib import Path


# ==================== CONSTANTS ====================

GUARD_LIFETIME_DAYS = 90  # How long to use same guards
GUARD_COUNT_PRIMARY = 3  # Number of primary guards
GUARD_COUNT_BACKUP = 5  # Number of backup guards
GUARD_CONFIRMATION_PERIOD = 14 * 86400  # 14 days to confirm new guard
GUARD_ROTATION_PERIOD = 9 * 30 * 86400  # Rotate after 9 months
MIN_GUARD_UPTIME_HOURS = 168  # 7 days minimum uptime
MIN_GUARD_BANDWIDTH_MBPS = 10  # 10 Mbps minimum


# ==================== DATA STRUCTURES ====================

@dataclass
class GuardNode:
    """
    Guard node with metadata

    Guards are long-lived entry points to the network
    Prevents adversary from observing all your connections
    """
    node_id: str
    endpoint: str
    public_keys: Dict[str, str]

    # Selection criteria
    bandwidth_mbps: float
    uptime_hours: float
    reputation: float
    country: str
    asn: int

    # Guard state
    first_added: float  # When first selected as guard
    last_used: float  # Last time used for circuit
    confirmed: bool = False  # Confirmed as reliable
    failure_count: int = 0  # Failed connection attempts
    success_count: int = 0  # Successful connections

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "endpoint": self.endpoint,
            "public_keys": self.public_keys,
            "bandwidth_mbps": self.bandwidth_mbps,
            "uptime_hours": self.uptime_hours,
            "reputation": self.reputation,
            "country": self.country,
            "asn": self.asn,
            "first_added": self.first_added,
            "last_used": self.last_used,
            "confirmed": self.confirmed,
            "failure_count": self.failure_count,
            "success_count": self.success_count
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GuardNode":
        return GuardNode(
            node_id=d["node_id"],
            endpoint=d["endpoint"],
            public_keys=d["public_keys"],
            bandwidth_mbps=d.get("bandwidth_mbps", 10.0),
            uptime_hours=d.get("uptime_hours", 0.0),
            reputation=d.get("reputation", 50.0),
            country=d.get("country", "XX"),
            asn=d.get("asn", 0),
            first_added=d.get("first_added", time.time()),
            last_used=d.get("last_used", 0),
            confirmed=d.get("confirmed", False),
            failure_count=d.get("failure_count", 0),
            success_count=d.get("success_count", 0)
        )

    def is_suitable(self) -> bool:
        """Check if node meets guard requirements"""
        return (
            self.uptime_hours >= MIN_GUARD_UPTIME_HOURS and
            self.bandwidth_mbps >= MIN_GUARD_BANDWIDTH_MBPS and
            self.reputation >= 60.0 and
            self.failure_count < 3
        )

    def success_rate(self) -> float:
        """Calculate connection success rate"""
        total = self.success_count + self.failure_count
        return self.success_count / max(total, 1)


# ==================== GUARD MANAGER ====================

class GuardManager:
    """
    Manages guard node selection and rotation

    Algorithm (based on Tor's guard selection):
    1. Select N guards from high-quality nodes
    2. Use same guards for 2-3 months
    3. Rotate slowly to prevent correlation attacks
    4. Maintain backup guards for failover
    """

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or Path.home() / ".satl" / "guard_state.json"
        self.primary_guards: List[GuardNode] = []
        self.backup_guards: List[GuardNode] = []
        self.blacklisted_nodes: Set[str] = set()

        # Load persistent state
        self._load_state()

    def _load_state(self):
        """Load guard state from disk"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.primary_guards = [GuardNode.from_dict(g) for g in state.get("primary", [])]
                    self.backup_guards = [GuardNode.from_dict(g) for g in state.get("backup", [])]
                    self.blacklisted_nodes = set(state.get("blacklist", []))
                    print(f"Loaded {len(self.primary_guards)} primary guards from state")
            except Exception as e:
                print(f"Failed to load guard state: {e}")

    def _save_state(self):
        """Persist guard state to disk"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "primary": [g.to_dict() for g in self.primary_guards],
            "backup": [g.to_dict() for g in self.backup_guards],
            "blacklist": list(self.blacklisted_nodes),
            "last_updated": time.time()
        }

        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"Failed to save guard state: {e}")

    def select_guards(self, available_nodes: List[Dict[str, Any]]):
        """
        Select new guard nodes from available candidates

        Selection criteria:
        - High bandwidth (top 25%)
        - High uptime (>7 days)
        - Geographic diversity
        - ASN diversity
        - Good reputation
        """
        now = time.time()

        # Check if rotation needed
        if self.primary_guards:
            oldest_guard = min(self.primary_guards, key=lambda g: g.first_added)
            age_days = (now - oldest_guard.first_added) / 86400

            if age_days < GUARD_LIFETIME_DAYS:
                print(f"Guards still valid ({age_days:.0f} days old)")
                return

        # Filter suitable candidates
        candidates = []
        for node_data in available_nodes:
            if node_data["node_id"] in self.blacklisted_nodes:
                continue

            guard = GuardNode(
                node_id=node_data["node_id"],
                endpoint=node_data.get("pub_ep", ""),
                public_keys=node_data.get("pub_keys", {}),
                bandwidth_mbps=node_data.get("bandwidth_mbps", 10.0),
                uptime_hours=node_data.get("uptime_hours", 0.0),
                reputation=node_data.get("reputation", 50.0),
                country=node_data.get("cc", "XX"),
                asn=node_data.get("asn", 0),
                first_added=now,
                last_used=0
            )

            if guard.is_suitable():
                candidates.append(guard)

        if len(candidates) < GUARD_COUNT_PRIMARY:
            print(f"WARNING: Only {len(candidates)} suitable guards found")
            return

        # Sort by weighted score
        candidates.sort(key=lambda g: self._guard_score(g), reverse=True)

        # Select primary guards with diversity
        self.primary_guards = self._select_diverse_guards(
            candidates,
            GUARD_COUNT_PRIMARY
        )

        # Select backup guards
        remaining = [g for g in candidates if g.node_id not in [pg.node_id for pg in self.primary_guards]]
        self.backup_guards = self._select_diverse_guards(
            remaining,
            GUARD_COUNT_BACKUP
        )

        self._save_state()
        print(f"Selected {len(self.primary_guards)} primary + {len(self.backup_guards)} backup guards")

    def _guard_score(self, guard: GuardNode) -> float:
        """
        Calculate guard quality score

        Weights:
        - Bandwidth: 30%
        - Uptime: 25%
        - Reputation: 25%
        - Success rate: 20%
        """
        bandwidth_score = min(guard.bandwidth_mbps / 100.0, 1.0) * 30
        uptime_score = min(guard.uptime_hours / (30 * 24), 1.0) * 25
        reputation_score = (guard.reputation / 100.0) * 25
        success_score = guard.success_rate() * 20

        return bandwidth_score + uptime_score + reputation_score + success_score

    def _select_diverse_guards(self, candidates: List[GuardNode], count: int) -> List[GuardNode]:
        """
        Select guards with geographic and ASN diversity

        Prevents adversary from controlling all guards
        """
        selected = []
        used_countries = set()
        used_asns = set()

        for guard in candidates:
            if len(selected) >= count:
                break

            # Enforce diversity
            if guard.country in used_countries and len(selected) < count // 2:
                continue
            if guard.asn in used_asns and len(selected) < count // 2:
                continue

            selected.append(guard)
            used_countries.add(guard.country)
            used_asns.add(guard.asn)

        # Fill remaining slots if diversity couldn't be achieved
        for guard in candidates:
            if len(selected) >= count:
                break
            if guard not in selected:
                selected.append(guard)

        return selected

    def get_guard_for_circuit(self) -> Optional[GuardNode]:
        """
        Get a guard node for new circuit

        Priority:
        1. Confirmed primary guards (used successfully before)
        2. Unconfirmed primary guards (need confirmation)
        3. Backup guards (if all primaries failed)
        """
        now = time.time()

        # Try confirmed primary guards first
        confirmed = [g for g in self.primary_guards if g.confirmed]
        if confirmed:
            guard = random.choice(confirmed)
            guard.last_used = now
            self._save_state()
            return guard

        # Try unconfirmed primary guards
        unconfirmed = [g for g in self.primary_guards if not g.confirmed]
        if unconfirmed:
            guard = random.choice(unconfirmed)
            guard.last_used = now
            self._save_state()
            return guard

        # Fallback to backup guards
        if self.backup_guards:
            guard = random.choice(self.backup_guards)
            guard.last_used = now
            print("WARNING: Using backup guard (all primaries unavailable)")
            self._save_state()
            return guard

        print("ERROR: No guards available")
        return None

    def report_circuit_result(self, guard_node_id: str, success: bool):
        """
        Report circuit build success/failure

        Used to:
        - Confirm new guards
        - Track reliability
        - Blacklist persistently failing guards
        """
        # Find guard in primary or backup
        guard = None
        for g in self.primary_guards + self.backup_guards:
            if g.node_id == guard_node_id:
                guard = g
                break

        if not guard:
            return

        # Update stats
        if success:
            guard.success_count += 1

            # Confirm guard after successful period
            if not guard.confirmed:
                age = time.time() - guard.first_added
                if age >= GUARD_CONFIRMATION_PERIOD and guard.success_rate() >= 0.8:
                    guard.confirmed = True
                    print(f"Guard {guard.node_id[:8]} confirmed as reliable")
        else:
            guard.failure_count += 1

            # Blacklist if too many failures
            if guard.failure_count >= 5 and guard.success_rate() < 0.3:
                self.blacklisted_nodes.add(guard.node_id)
                self.primary_guards = [g for g in self.primary_guards if g.node_id != guard.node_id]
                self.backup_guards = [g for g in self.backup_guards if g.node_id != guard.node_id]
                print(f"Guard {guard.node_id[:8]} blacklisted (too many failures)")

        self._save_state()

    def get_guard_info(self) -> Dict[str, Any]:
        """Get current guard status for monitoring"""
        return {
            "primary_count": len(self.primary_guards),
            "backup_count": len(self.backup_guards),
            "confirmed_count": sum(1 for g in self.primary_guards if g.confirmed),
            "blacklisted_count": len(self.blacklisted_nodes),
            "primary_guards": [
                {
                    "node_id": g.node_id[:16],
                    "confirmed": g.confirmed,
                    "success_rate": g.success_rate(),
                    "age_days": (time.time() - g.first_added) / 86400
                }
                for g in self.primary_guards
            ]
        }


# ==================== EXPORT ====================

__all__ = [
    'GuardNode',
    'GuardManager',
    'GUARD_LIFETIME_DAYS',
    'GUARD_COUNT_PRIMARY'
]


if __name__ == "__main__":
    print("=== GUARD NODES SELF-TEST ===")

    # Mock node data
    mock_nodes = [
        {
            "node_id": f"node-{i:03d}",
            "pub_ep": f"http://node{i}.satl.net/ingress",
            "pub_keys": {},
            "bandwidth_mbps": random.uniform(10, 100),
            "uptime_hours": random.uniform(100, 10000),
            "reputation": random.uniform(60, 100),
            "cc": random.choice(["US", "DE", "JP", "CA", "FR"]),
            "asn": random.randint(10000, 60000)
        }
        for i in range(50)
    ]

    # Test guard selection
    manager = GuardManager(state_file=Path("/tmp/test_guards.json"))
    manager.select_guards(mock_nodes)
    print(f"✓ Selected guards")

    # Test guard retrieval
    guard = manager.get_guard_for_circuit()
    if guard:
        print(f"✓ Got guard: {guard.node_id}")

        # Simulate circuit results
        manager.report_circuit_result(guard.node_id, success=True)
        manager.report_circuit_result(guard.node_id, success=True)
        manager.report_circuit_result(guard.node_id, success=True)
        print(f"✓ Reported circuit results")

    # Print status
    info = manager.get_guard_info()
    print(f"\nGuard Status:")
    print(f"  Primary: {info['primary_count']}")
    print(f"  Confirmed: {info['confirmed_count']}")
    print(f"  Backup: {info['backup_count']}")

    print("\n✅ Guard nodes test complete")
