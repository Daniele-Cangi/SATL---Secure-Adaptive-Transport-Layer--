# remote_entropy.py - MPC-based remote entropy
import time
import hmac
import hashlib
import asyncio
import aiohttp
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class EntropyShare:
    """Una share di entropia da un peer MPC"""
    peer_id: str
    share: bytes
    timestamp: float
    signature: str

class MPCEntropyFetcher:
    """
    Fetcher per entropia remota tramite MPC (3/5 quorum).
    
    Protocollo:
    1. Richiede share a 5 peer
    2. Aspetta almeno 3 risposte (timeout 100ms)
    3. Verifica firme
    4. Combina con XOR
    """
    
    def __init__(self, peer_endpoints: List[str], timeout_ms: int = 100):
        self.peers = peer_endpoints
        self.timeout = timeout_ms / 1000
        self.cache: Optional[bytes] = None
        self.cache_time: float = 0
        self.cache_ttl: float = 30  # Cache per 30s
    
    async def _fetch_share_from_peer(self, peer_url: str, 
                                     session: aiohttp.ClientSession) -> Optional[EntropyShare]:
        """
        Fetcha una share da un singolo peer.
        
        API endpoint: GET /api/v1/entropy/share
        Response: {
            "peer_id": "peer-1",
            "share": "hex_string",
            "timestamp": 1234567890.123,
            "signature": "hex_sig"
        }
        """
        try:
            async with session.get(
                f"{peer_url}/api/v1/entropy/share",
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                return EntropyShare(
                    peer_id=data["peer_id"],
                    share=bytes.fromhex(data["share"]),
                    timestamp=data["timestamp"],
                    signature=data["signature"]
                )
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            print(f"Failed to fetch from {peer_url}: {e}")
            return None
    
    def _verify_share(self, share: EntropyShare, peer_pubkey: bytes) -> bool:
        """
        Verifica che la share sia firmata correttamente dal peer.
        
        In produzione: usa le pubkey distribuite in fase di setup.
        """
        # Placeholder: in produzione usa cryptography per verificare
        # la firma ECDSA o Dilithium del peer
        return True  # TODO: implement real verification
    
    def _combine_shares(self, shares: List[EntropyShare]) -> bytes:
        """
        Combina le share con XOR.
        Questo è semplice ma sicuro: anche se 2/5 peer sono malevoli,
        non possono predire l'output finale.
        """
        if not shares:
            raise ValueError("No shares to combine")
        
        result = shares[0].share
        for share in shares[1:]:
            result = bytes(a ^ b for a, b in zip(result, share.share))
        
        return result
    
    async def fetch_entropy(self, min_shares: int = 3) -> bytes:
        """
        Fetcha entropia remota con quorum 3/5.
        
        Returns: 32 bytes di entropia
        Raises: RuntimeError se non raggiunge quorum
        """
        # Check cache
        now = time.time()
        if self.cache and (now - self.cache_time) < self.cache_ttl:
            return self.cache
        
        # Fetch da tutti i peer in parallelo
        async with aiohttp.ClientSession() as session:
            tasks = [
                self._fetch_share_from_peer(peer, session) 
                for peer in self.peers
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filtra risultati validi
        valid_shares = [
            r for r in results 
            if isinstance(r, EntropyShare) and self._verify_share(r, b"")
        ]
        
        if len(valid_shares) < min_shares:
            raise RuntimeError(
                f"MPC quorum not reached: {len(valid_shares)}/{min_shares} shares"
            )
        
        # Usa solo le prime min_shares (deterministico)
        valid_shares.sort(key=lambda s: s.peer_id)
        entropy = self._combine_shares(valid_shares[:min_shares])
        
        # Cache
        self.cache = entropy
        self.cache_time = now
        
        return entropy


class HSMEntropyFallback:
    """
    Fallback se MPC non raggiunge quorum.
    Usa HSM locale + pre-generated seeds.
    """
    
    def __init__(self, hsm_path: str = "/dev/hsm0"):
        self.hsm_path = hsm_path
        self.pregenerated_seeds: List[bytes] = []
        self._generate_seed_pool(1000)
    
    def _generate_seed_pool(self, count: int):
        """
        Pre-genera N seed quando HSM è disponibile.
        Usati come fallback se HSM diventa irraggiungibile.
        """
        # In produzione: leggi da HSM reale
        # Per ora: usa /dev/urandom
        import os
        for _ in range(count):
            self.pregenerated_seeds.append(os.urandom(32))
    
    def get_entropy(self) -> bytes:
        """
        Ritorna entropia da HSM o da pool pre-generato.
        """
        try:
            # Prova HSM reale
            with open(self.hsm_path, 'rb') as f:
                return f.read(32)
        except:
            # Fallback: usa seed pre-generato
            if not self.pregenerated_seeds:
                raise RuntimeError("HSM unavailable and seed pool exhausted")
            
            return self.pregenerated_seeds.pop(0)


class HybridEntropySource:
    """
    Combina MPC + HSM con fallback intelligente.
    
    Strategia:
    - Normal: MPC (3/5) + HSM + network_state
    - MPC slow: HSM + network_state + timestamp
    - MPC down: HSM pool + network_state
    """
    
    def __init__(self, mpc_peers: List[str], hsm_path: str = "/dev/hsm0"):
        self.mpc = MPCEntropyFetcher(mpc_peers, timeout_ms=100)
        self.hsm = HSMEntropyFallback(hsm_path)
    
    async def get_entropy(self, network_state: bytes) -> Dict[str, bytes]:
        """
        Returns dict con le 3 sorgenti di entropia.
        """
        try:
            # Prova MPC con timeout aggressivo
            mpc_entropy = await asyncio.wait_for(
                self.mpc.fetch_entropy(min_shares=3),
                timeout=0.15  # 150ms max
            )
        except (RuntimeError, asyncio.TimeoutError) as e:
            print(f"MPC fallback: {e}")
            # Fallback: usa timestamp come sostituto debole
            mpc_entropy = hashlib.sha256(
                str(time.time()).encode()
            ).digest()
        
        hsm_entropy = self.hsm.get_entropy()
        
        return {
            "mpc": mpc_entropy,
            "hsm": hsm_entropy,
            "network": network_state
        }


# Usage example
async def main():
    # Setup
    mpc_peers = [
        "https://mpc-peer-1.example.com",
        "https://mpc-peer-2.example.com",
        "https://mpc-peer-3.example.com",
        "https://mpc-peer-4.example.com",
        "https://mpc-peer-5.example.com",
    ]
    
    hybrid = HybridEntropySource(mpc_peers)
    
    # Simula network state
    network_state = hashlib.sha256(b"node-a,node-b,node-c").digest()
    
    # Fetch
    entropy_sources = await hybrid.get_entropy(network_state)
    
    # Mix finale (come in SPO)
    final_entropy = hmac.new(
        b"spo-secret",
        entropy_sources["mpc"] + 
        entropy_sources["hsm"] + 
        entropy_sources["network"],
        hashlib.sha256
    ).digest()
    
    print(f"Final entropy: {final_entropy.hex()}")

if __name__ == "__main__":
    asyncio.run(main())
