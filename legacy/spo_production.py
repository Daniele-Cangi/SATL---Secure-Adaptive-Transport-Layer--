# spo_production.py - Shadow Path Operator production-ready
import asyncio
import time
import hashlib
import hmac
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, asdict
from collections import defaultdict
import logging
from quantum_entropy import get_seed
from pqc_agility import hybrid_sign

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SPO")

@dataclass
class Node:
    """Rappresentazione di un nodo nella rete"""
    node_id: str
    country: str
    asn: int
    median_latency_ms: float
    uptime_ratio: float  # 0-1
    bandwidth_mbps: int
    reputation_score: float  # 0-1
    last_seen: float
    flagged_events: int = 0

@dataclass
class Channel:
    """Canale attivo"""
    channel_id: str
    client_id: str
    policy: str
    route: List[str]  # node_ids
    opened_at: float
    last_rotation: float
    rotation_count: int = 0

class NodeScorer:
    """
    Calcola score dei nodi per path selection.
    """
    
    def calculate_score(self, node: Node) -> float:
        """Score 0-1 basato su metriche multiple"""
        scores = {
            "uptime": min(node.uptime_ratio / 0.995, 1.0) * 25,
            "latency": self._latency_score(node.median_latency_ms) * 20,
            "bandwidth": self._bandwidth_score(node.bandwidth_mbps) * 15,
            "reputation": node.reputation_score * 15,
        }
        
        total = sum(scores.values())
        
        # Penalità per eventi sospetti
        if node.flagged_events > 0:
            penalty = min(node.flagged_events * 5, 30)
            total -= penalty
        
        return max(0, min(100, total)) / 100
    
    def _latency_score(self, latency_ms: float) -> float:
        """20 pts se <30ms, scala linearmente"""
        if latency_ms < 30:
            return 1.0
        elif latency_ms < 60:
            return 0.75
        elif latency_ms < 100:
            return 0.5
        else:
            return 0.25
    
    def _bandwidth_score(self, bandwidth_mbps: int) -> float:
        """Score basato su bandwidth disponibile"""
        if bandwidth_mbps > 1000:
            return 1.0
        elif bandwidth_mbps > 100:
            return 0.8
        elif bandwidth_mbps > 10:
            return 0.5
        else:
            return 0.2

class ShadowPathOperator:
    """
    SPO Production-Ready.
    
    Features:
    - Entropia remota (MPC + HSM)
    - Node scoring e reputation
    - Rotation pack pre-firmati
    - Firma digitale (Ed25519 → Dilithium)
    - Anti-Sybil (diversity requirements)
    """
    
    def __init__(self, 
                 spo_secret: bytes,
                 mpc_peers: List[str],
                 hsm_path: str = "/dev/hsm0"):
        
        self.spo_secret = spo_secret
        
        # Componenti
        from spo_signature import SPOSigner
        from remote_entropy import HybridEntropySource
        
        self.signer = SPOSigner()
        self.entropy_source = HybridEntropySource(mpc_peers, hsm_path)
        self.scorer = NodeScorer()
        
        # State
        self.nodes: Dict[str, Node] = {}
        self.channels: Dict[str, Channel] = {}
        self.rotation_packs: Dict[str, Dict[str, Any]] = {}
        
        # Anti-replay
        self.used_nonces: Set[int] = set()
        self.nonce_counter = 0
    
    def register_node(self, node: Node):
        """Registra nuovo nodo nella rete"""
        node.reputation_score = self.scorer.calculate_score(node)
        self.nodes[node.node_id] = node
        logger.info(f"Node registered: {node.node_id} (score={node.reputation_score:.2f})")
    
    def _get_network_state_hash(self) -> bytes:
        """Hash dello stato corrente della rete"""
        h = hashlib.sha256()
        
        # Ordine deterministico
        for node_id in sorted(self.nodes.keys()):
            node = self.nodes[node_id]
            h.update(node_id.encode())
            h.update(str(node.last_seen).encode())
            h.update(str(node.median_latency_ms).encode())
        
        h.update(str(time.time() // 60).encode())  # Quantized time
        
        return h.digest()
    
    async def _get_mixed_entropy(self) -> bytes:
        """
        Mix delle 3 sorgenti di entropia.
        
        Returns: 32 bytes di entropia finale.
        """
        network_state = self._get_network_state_hash()
        
        entropy_dict = await self.entropy_source.get_entropy(network_state)
        
        # Mix con HMAC
        final = hmac.new(
            self.spo_secret,
            entropy_dict["mpc"] + entropy_dict["hsm"] + entropy_dict["network"],
            hashlib.sha256
        ).digest()
        
        return final
    
    def _select_diverse_nodes(self, candidates: List[Node], 
                             count: int) -> List[Node]:
        """
        Seleziona nodi garantendo diversity geografica e ASN.
        
        Anti-Sybil: evita clustering.
        """
        if len(candidates) < count:
            raise ValueError(f"Not enough nodes: need {count}, have {len(candidates)}")
        
        selected = []
        used_countries = set()
        used_asns = set()
        
        # Sort per score (migliori primi)
        candidates.sort(key=lambda n: n.reputation_score, reverse=True)
        
        for node in candidates:
            # Skip se stesso paese o stesso ASN (anti-clustering)
            if node.country in used_countries and len(selected) < count:
                continue
            if node.asn in used_asns and len(selected) < count:
                continue
            
            selected.append(node)
            used_countries.add(node.country)
            used_asns.add(node.asn)
            
            if len(selected) >= count:
                break
        
        # Fallback: se non raggiungiamo diversity, prendi i migliori
        if len(selected) < count:
            remaining = [n for n in candidates if n not in selected]
            selected.extend(remaining[:count - len(selected)])
        
        return selected[:count]
    
    async def build_route(self, policy: Dict[str, Any], 
                         entropy_seed: Optional[bytes] = None) -> Dict[str, Any]:
        """
        Genera percorso usando entropia remota + scoring.
        
        Returns: {
            "hops": [node_ids],
            "use_intranodes": bool,
            "entropy_tag": hex,
            "diversity_score": float
        }
        """
        # Get entropia
        if entropy_seed is None:
            entropy_seed = await self._get_mixed_entropy()
        
        # Filtra nodi eligible (score > 0.6)
        eligible = [
            n for n in self.nodes.values()
            if n.reputation_score > 0.6
        ]
        
        if len(eligible) < 3:
            raise RuntimeError("Not enough eligible nodes (min 3)")
        
        # Policy-specific sorting
        if policy.get("name") == "lowlatency":
            # Preferisci latency bassa
            eligible.sort(key=lambda n: n.median_latency_ms)
        else:
            # Preferisci score alto
            eligible.sort(key=lambda n: n.reputation_score, reverse=True)
        
        # Seleziona con diversity
        num_hops = 3  # TODO: policy-configurable
        selected_nodes = self._select_diverse_nodes(eligible, num_hops)
        
        # Calcola diversity score
        countries = len(set(n.country for n in selected_nodes))
        asns = len(set(n.asn for n in selected_nodes))
        diversity_score = (countries + asns) / (num_hops * 2)
        
        return {
            "hops": [n.node_id for n in selected_nodes],
            "use_intranodes": policy.get("use_intranodes", False),
            "entropy_tag": entropy_seed.hex()[:16],  # Primi 8 bytes
            "diversity_score": diversity_score
        }
    
    async def create_channel(self, client_id: str, policy: str) -> Dict[str, Any]:
        """
        Crea nuovo canale sicuro.
        
        Returns: {
            "channel_id": str,
            "session_key_id": str,
            "route_seed": str  (hint, non path completo)
        }
        """
        from satl_config import SATL_POLICIES
        
        policy_config = SATL_POLICIES[policy]
        
        # Build route
        route_info = await self.build_route({"name": policy, **policy_config})
        
        # Create channel
        channel_id = f"ch-{int(time.time() * 1000)}"
        channel = Channel(
            channel_id=channel_id,
            client_id=client_id,
            policy=policy,
            route=route_info["hops"],
            opened_at=time.time(),
            last_rotation=time.time()
        )
        
        self.channels[channel_id] = channel
        
        # Pre-compute rotation pack
        await self._precompute_rotation_pack(channel_id, policy_config)
        
        logger.info(f"Channel created: {channel_id} with {len(route_info['hops'])} hops")
        
        return {
            "channel_id": channel_id,
            "session_key_id": f"sk-{channel_id}",
            "route_seed": route_info["entropy_tag"]  # Non il path reale!
        }
    
    async def _precompute_rotation_pack(self, channel_id: str, 
                                       policy: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pre-genera rotation pack per resilienza.
        
        Valido per 5 minuti.
        """
        channel = self.channels[channel_id]
        
        # Genera nuovo percorso
        new_route = await self.build_route(policy)
        
        # Crea istruzione
        self.nonce_counter += 1
        instruction = {
            "type": "rotate",
            "channel_id": channel_id,
            "payload": new_route,
            "timestamp": time.time(),
            "nonce": self.nonce_counter
        }
        
        # Firma
        signature = self.signer.sign_instruction(instruction)
        
        pack = {
            "valid_until": time.time() + 300,  # 5 min
            "instructions": [instruction],
            "signature": signature
        }
        
        # Entropy attestation: attestiamo la freschezza del seed (senza rivelarlo)
        seed, rep = get_seed(32)
        att = f"{int(rep['ts'])}:{int(rep['min_entropy_bits'])}".encode()
        pack["entropy_attestation"] = hybrid_sign(att, ed25519_sk=b"ed_secret", pqc_sk=None)
        
        self.rotation_packs[channel_id] = pack
        
        return pack
    
    def get_rotation_pack(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """
        Ritorna rotation pack valido.
        
        Se scaduto, ne genera uno nuovo.
        """
        pack = self.rotation_packs.get(channel_id)
        
        if pack and pack["valid_until"] > time.time():
            return pack
        
        # Scaduto, rigenera (sync wrapper)
        channel = self.channels.get(channel_id)
        if not channel:
            return None
        
        from satl_config import SATL_POLICIES
        policy_config = SATL_POLICIES[channel.policy]
        
        # Usa asyncio.run solo se non siamo già in event loop
        try:
            loop = asyncio.get_running_loop()
            # Siamo in async context, schedule
            task = loop.create_task(
                self._precompute_rotation_pack(channel_id, policy_config)
            )
            # Per ora ritorna pack vecchio, task aggiornerà in background
            return pack
        except RuntimeError:
            # Non in async context, possiamo fare asyncio.run
            return asyncio.run(
                self._precompute_rotation_pack(channel_id, policy_config)
            )
    
    def close_channel(self, channel_id: str):
        """Chiude canale e cleanup"""
        if channel_id in self.channels:
            channel = self.channels.pop(channel_id)
            self.rotation_packs.pop(channel_id, None)
            
            logger.info(f"Channel closed: {channel_id} "
                       f"(duration={time.time() - channel.opened_at:.1f}s, "
                       f"rotations={channel.rotation_count})")
    
    def flag_suspicious_node(self, node_id: str, reason: str):
        """Marca un nodo come sospetto"""
        if node_id in self.nodes:
            self.nodes[node_id].flagged_events += 1
            logger.warning(f"Node flagged: {node_id} - {reason}")
            
            # Ricalcola score
            self.nodes[node_id].reputation_score = self.scorer.calculate_score(
                self.nodes[node_id]
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """Statistiche del sistema"""
        return {
            "total_nodes": len(self.nodes),
            "active_channels": len(self.channels),
            "avg_node_score": sum(n.reputation_score for n in self.nodes.values()) / len(self.nodes) if self.nodes else 0,
            "flagged_nodes": sum(1 for n in self.nodes.values() if n.flagged_events > 0),
            "rotation_packs_cached": len(self.rotation_packs)
        }


# Usage example
async def main():
    # Setup
    spo = ShadowPathOperator(
        spo_secret=b"super-secret-spo-key",
        mpc_peers=[
            "https://mpc-1.example.com",
            "https://mpc-2.example.com",
            "https://mpc-3.example.com",
            "https://mpc-4.example.com",
            "https://mpc-5.example.com",
        ]
    )
    
    # Register nodes
    test_nodes = [
        Node("node-a", "US", 12345, 25.0, 0.998, 1000, 0.9, time.time()),
        Node("node-b", "DE", 54321, 30.0, 0.995, 500, 0.85, time.time()),
        Node("node-c", "JP", 67890, 45.0, 0.990, 800, 0.88, time.time()),
        Node("node-d", "UK", 11111, 28.0, 0.997, 1200, 0.92, time.time()),
    ]
    
    for node in test_nodes:
        spo.register_node(node)
    
    # Create channel
    channel_resp = await spo.create_channel("client-123", "stealth")
    print(f"Channel created: {channel_resp}")
    
    # Get rotation pack
    pack = spo.get_rotation_pack(channel_resp["channel_id"])
    print(f"Rotation pack: {pack is not None}")
    
    # Stats
    stats = spo.get_stats()
    print(f"Stats: {stats}")
    
    # Close
    spo.close_channel(channel_resp["channel_id"])

if __name__ == "__main__":
    asyncio.run(main())
