"""
==========================================
DHT_CONSENSUS.PY - Distributed Hash Table
==========================================
Kademlia-based DHT for decentralized consensus
Replaces single control plane with P2P directory
"""
import asyncio
import hashlib
import time
import json
import base64
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, asdict
import aiohttp


# ==================== KADEMLIA CONSTANTS ====================

K_BUCKET_SIZE = 20  # Number of nodes per k-bucket
ALPHA = 3  # Concurrency parameter for node lookups
ID_BITS = 160  # Node ID space (SHA-1 size)
REPLICATION_FACTOR = 3  # Number of nodes to store each value


# ==================== NODE ID & DISTANCE ====================

def sha1_hash(data: bytes) -> int:
    """Hash data to node ID space"""
    return int.from_bytes(hashlib.sha1(data).digest(), 'big')


def xor_distance(id1: int, id2: int) -> int:
    """XOR distance metric (Kademlia)"""
    return id1 ^ id2


def common_prefix_length(id1: int, id2: int) -> int:
    """Count leading zero bits in XOR (determines bucket index)"""
    dist = xor_distance(id1, id2)
    if dist == 0:
        return ID_BITS
    return ID_BITS - dist.bit_length()


# ==================== DATA STRUCTURES ====================

@dataclass
class DHTNode:
    """Node in the DHT network"""
    node_id: int  # 160-bit identifier
    ip_address: str
    port: int
    public_endpoint: str
    last_seen: float  # Timestamp
    capabilities: List[str]  # ["qso", "mix", "pqc"]
    reputation: float  # 0-100 score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": hex(self.node_id),
            "ip": self.ip_address,
            "port": self.port,
            "endpoint": self.public_endpoint,
            "last_seen": self.last_seen,
            "caps": self.capabilities,
            "rep": self.reputation
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DHTNode":
        return DHTNode(
            node_id=int(d["node_id"], 16),
            ip_address=d["ip"],
            port=d["port"],
            public_endpoint=d["endpoint"],
            last_seen=d.get("last_seen", time.time()),
            capabilities=d.get("caps", []),
            reputation=d.get("rep", 50.0)
        )


@dataclass
class KBucket:
    """Routing table bucket (stores up to K nodes)"""
    index: int  # Bucket index (0 to ID_BITS-1)
    nodes: List[DHTNode]
    last_updated: float

    def add_node(self, node: DHTNode) -> bool:
        """Add node to bucket (LRU eviction if full)"""
        # Check if already exists
        for i, n in enumerate(self.nodes):
            if n.node_id == node.node_id:
                # Move to end (most recently seen)
                self.nodes.pop(i)
                self.nodes.append(node)
                self.last_updated = time.time()
                return True

        # Add if space available
        if len(self.nodes) < K_BUCKET_SIZE:
            self.nodes.append(node)
            self.last_updated = time.time()
            return True

        # Bucket full - LRU eviction (ping least recent)
        # For now, simple: reject if full
        return False

    def get_nodes(self, count: int = K_BUCKET_SIZE) -> List[DHTNode]:
        """Get up to count closest nodes"""
        return self.nodes[-count:]  # Most recent


# ==================== ROUTING TABLE ====================

class RoutingTable:
    """Kademlia routing table with k-buckets"""

    def __init__(self, own_id: int):
        self.own_id = own_id
        self.buckets: List[KBucket] = [
            KBucket(index=i, nodes=[], last_updated=0)
            for i in range(ID_BITS)
        ]

    def add_node(self, node: DHTNode) -> bool:
        """Add node to appropriate k-bucket"""
        if node.node_id == self.own_id:
            return False

        bucket_index = common_prefix_length(self.own_id, node.node_id)
        return self.buckets[bucket_index].add_node(node)

    def find_closest_nodes(self, target_id: int, count: int = K_BUCKET_SIZE) -> List[DHTNode]:
        """Find K closest nodes to target ID"""
        all_nodes = []
        for bucket in self.buckets:
            all_nodes.extend(bucket.nodes)

        # Sort by XOR distance
        all_nodes.sort(key=lambda n: xor_distance(n.node_id, target_id))

        return all_nodes[:count]

    def get_random_node(self) -> Optional[DHTNode]:
        """Get random node from routing table (for bootstrapping)"""
        import random
        all_nodes = []
        for bucket in self.buckets:
            all_nodes.extend(bucket.nodes)

        return random.choice(all_nodes) if all_nodes else None


# ==================== DHT PROTOCOL ====================

class DHTProtocol:
    """
    Kademlia DHT protocol implementation

    RPC Methods:
    - PING: Check if node is alive
    - FIND_NODE: Find K closest nodes to target ID
    - FIND_VALUE: Find value for key
    - STORE: Store key-value pair
    """

    def __init__(self, node_id: int, ip: str, port: int, public_endpoint: str):
        self.node_id = node_id
        self.ip = ip
        self.port = port
        self.public_endpoint = public_endpoint

        self.routing_table = RoutingTable(node_id)
        self.storage: Dict[str, Any] = {}  # Local key-value storage

        # Node metadata
        self.capabilities = ["qso", "mix", "pqc", "dht"]
        self.reputation = 75.0

    def handle_ping(self, sender: DHTNode) -> Dict[str, Any]:
        """PING RPC - respond with own node info"""
        self.routing_table.add_node(sender)

        return {
            "rpc": "PONG",
            "node": DHTNode(
                node_id=self.node_id,
                ip_address=self.ip,
                port=self.port,
                public_endpoint=self.public_endpoint,
                last_seen=time.time(),
                capabilities=self.capabilities,
                reputation=self.reputation
            ).to_dict()
        }

    def handle_find_node(self, target_id: int, sender: DHTNode) -> Dict[str, Any]:
        """FIND_NODE RPC - return K closest nodes to target"""
        self.routing_table.add_node(sender)

        closest_nodes = self.routing_table.find_closest_nodes(target_id, K_BUCKET_SIZE)

        return {
            "rpc": "NODES",
            "nodes": [n.to_dict() for n in closest_nodes]
        }

    def handle_find_value(self, key: str, sender: DHTNode) -> Dict[str, Any]:
        """FIND_VALUE RPC - return value if stored, else closest nodes"""
        self.routing_table.add_node(sender)

        # Check local storage
        if key in self.storage:
            return {
                "rpc": "VALUE",
                "value": self.storage[key]
            }

        # Not found, return closest nodes instead
        key_id = sha1_hash(key.encode())
        closest_nodes = self.routing_table.find_closest_nodes(key_id, K_BUCKET_SIZE)

        return {
            "rpc": "NODES",
            "nodes": [n.to_dict() for n in closest_nodes]
        }

    def handle_store(self, key: str, value: Any, sender: DHTNode) -> Dict[str, Any]:
        """STORE RPC - store key-value pair"""
        self.routing_table.add_node(sender)

        # Store locally
        self.storage[key] = {
            "value": value,
            "stored_at": time.time(),
            "stored_by": sender.node_id
        }

        return {
            "rpc": "STORED",
            "ok": True
        }


# ==================== DHT CLIENT (Async Network Layer) ====================

class DHTClient:
    """
    Asynchronous DHT client for network operations

    Implements:
    - Node lookup (iterative find_node)
    - Value lookup (iterative find_value)
    - Value storage (replicate to K closest nodes)
    """

    def __init__(self, protocol: DHTProtocol):
        self.protocol = protocol
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """Initialize HTTP client session"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))

    async def stop(self):
        """Close HTTP client session"""
        if self.session:
            await self.session.close()

    async def rpc_call(self, node: DHTNode, method: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make RPC call to remote node"""
        if not self.session:
            return None

        try:
            url = f"http://{node.ip_address}:{node.port}/dht/rpc"
            payload = {
                "method": method,
                "params": params,
                "sender": DHTNode(
                    node_id=self.protocol.node_id,
                    ip_address=self.protocol.ip,
                    port=self.protocol.port,
                    public_endpoint=self.protocol.public_endpoint,
                    last_seen=time.time(),
                    capabilities=self.protocol.capabilities,
                    reputation=self.protocol.reputation
                ).to_dict()
            }

            async with self.session.post(url, json=payload) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"RPC call failed to {node.ip_address}:{node.port}: {e}")

        return None

    async def iterative_find_node(self, target_id: int) -> List[DHTNode]:
        """
        Iterative node lookup (Kademlia algorithm)

        1. Start with K closest nodes from local routing table
        2. Query ALPHA nodes in parallel
        3. Add responses to candidate list
        4. Repeat until K closest nodes found
        """
        # Start with closest nodes from routing table
        closest = self.protocol.routing_table.find_closest_nodes(target_id, K_BUCKET_SIZE)
        queried: Set[int] = set()
        result_nodes: List[DHTNode] = list(closest)

        while True:
            # Find unqueried nodes to query
            to_query = [
                node for node in result_nodes
                if node.node_id not in queried
            ][:ALPHA]

            if not to_query:
                break

            # Query in parallel
            tasks = [
                self.rpc_call(node, "FIND_NODE", {"target_id": hex(target_id)})
                for node in to_query
            ]

            responses = await asyncio.gather(*tasks)

            # Mark as queried
            for node in to_query:
                queried.add(node.node_id)

            # Process responses
            for resp in responses:
                if resp and "nodes" in resp:
                    for node_dict in resp["nodes"]:
                        node = DHTNode.from_dict(node_dict)
                        if node.node_id not in [n.node_id for n in result_nodes]:
                            result_nodes.append(node)

            # Sort by distance
            result_nodes.sort(key=lambda n: xor_distance(n.node_id, target_id))
            result_nodes = result_nodes[:K_BUCKET_SIZE]

        return result_nodes

    async def store_value(self, key: str, value: Any) -> bool:
        """
        Store value in DHT (replicate to K closest nodes)
        """
        key_id = sha1_hash(key.encode())

        # Find K closest nodes to key
        closest_nodes = await self.iterative_find_node(key_id)

        if not closest_nodes:
            return False

        # Store on K nodes
        tasks = [
            self.rpc_call(node, "STORE", {"key": key, "value": value})
            for node in closest_nodes[:REPLICATION_FACTOR]
        ]

        responses = await asyncio.gather(*tasks)

        # Success if majority stored
        success_count = sum(1 for r in responses if r and r.get("ok"))
        return success_count >= (REPLICATION_FACTOR // 2 + 1)

    async def find_value(self, key: str) -> Optional[Any]:
        """
        Find value in DHT (iterative lookup)
        """
        key_id = sha1_hash(key.encode())

        # Start with closest nodes
        closest = self.protocol.routing_table.find_closest_nodes(key_id, K_BUCKET_SIZE)
        queried: Set[int] = set()

        while True:
            to_query = [
                node for node in closest
                if node.node_id not in queried
            ][:ALPHA]

            if not to_query:
                break

            # Query in parallel
            tasks = [
                self.rpc_call(node, "FIND_VALUE", {"key": key})
                for node in to_query
            ]

            responses = await asyncio.gather(*tasks)

            # Mark as queried
            for node in to_query:
                queried.add(node.node_id)

            # Check for value
            for resp in responses:
                if resp and resp.get("rpc") == "VALUE":
                    return resp.get("value")

                # Add new nodes to search
                if resp and "nodes" in resp:
                    for node_dict in resp["nodes"]:
                        node = DHTNode.from_dict(node_dict)
                        if node.node_id not in [n.node_id for n in closest]:
                            closest.append(node)

            # Sort and limit
            closest.sort(key=lambda n: xor_distance(n.node_id, key_id))
            closest = closest[:K_BUCKET_SIZE]

        return None


# ==================== CONSENSUS DIRECTORY ====================

class ConsensusDirectory:
    """
    Decentralized directory service using DHT

    Replaces centralized control plane with distributed consensus
    """

    def __init__(self, dht_client: DHTClient):
        self.dht_client = dht_client

    async def register_node(self, node_info: Dict[str, Any]) -> bool:
        """Register node in distributed directory"""
        key = f"node:{node_info['node_id']}"
        return await self.dht_client.store_value(key, node_info)

    async def get_node_snapshot(self) -> Dict[str, Any]:
        """Get snapshot of active nodes from DHT"""
        # Query multiple random keys to discover nodes
        nodes = {}

        # Sample node space
        for i in range(10):
            random_key = f"node:sample:{i}"
            value = await self.dht_client.find_value(random_key)
            if value:
                nodes[value["node_id"]] = value

        return {"nodes": nodes, "timestamp": time.time()}

    async def publish_rotation_pack(self, profile: str, pack: Dict[str, Any]) -> bool:
        """Publish rotation parameters to DHT"""
        key = f"rotation:{profile}:latest"
        return await self.dht_client.store_value(key, pack)

    async def get_rotation_pack(self, profile: str) -> Optional[Dict[str, Any]]:
        """Fetch rotation parameters from DHT"""
        key = f"rotation:{profile}:latest"
        return await self.dht_client.find_value(key)


# ==================== EXPORT ====================

__all__ = [
    'DHTNode',
    'DHTProtocol',
    'DHTClient',
    'ConsensusDirectory',
    'sha1_hash'
]


if __name__ == "__main__":
    print("=== DHT CONSENSUS SELF-TEST ===")

    # Create test node
    node_id = sha1_hash(b"test-node-001")
    protocol = DHTProtocol(node_id, "127.0.0.1", 8001, "http://localhost:8001")

    print(f"✓ Node ID: {hex(node_id)[:16]}...")

    # Test routing table
    peer_id = sha1_hash(b"peer-node-002")
    peer = DHTNode(
        node_id=peer_id,
        ip_address="127.0.0.1",
        port=8002,
        public_endpoint="http://localhost:8002",
        last_seen=time.time(),
        capabilities=["qso"],
        reputation=80.0
    )

    protocol.routing_table.add_node(peer)
    print(f"✓ Added peer to routing table")

    # Test FIND_NODE
    resp = protocol.handle_find_node(sha1_hash(b"target"), peer)
    print(f"✓ FIND_NODE: {len(resp['nodes'])} nodes returned")

    # Test STORE/FIND_VALUE
    protocol.handle_store("test_key", {"data": "test_value"}, peer)
    resp = protocol.handle_find_value("test_key", peer)
    assert resp["rpc"] == "VALUE"
    print(f"✓ STORE/FIND_VALUE: {resp['value']['value']}")

    print("\n✅ DHT consensus test complete")
