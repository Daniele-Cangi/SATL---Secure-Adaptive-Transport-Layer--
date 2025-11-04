# traffic_morphing.py - Advanced traffic morphing per DP
import os
import time
import random
import asyncio
from typing import List, Tuple, Optional
from dataclasses import dataclass
from secrets import SystemRandom
from quantum_entropy import qrng_stream
from mixnet_layer import PoissonMix
from histogram_fitter import inv_cdf_sampler
from spectral_sanitizer import deperiodize_intervals
from satl_config import STEALTH_PROFILES

@dataclass
class MorphedChunk:
    """Un chunk dopo morphing"""
    data: bytes
    send_delay_ms: float  # Jitter delay
    is_cover: bool  # True se è cover traffic
    chunk_id: int

class TrafficMorpher:
    """
    Implementa morphing avanzato per anti-correlation.
    
    Tecniche:
    1. Padding variabile (non multipli di 2^n)
    2. Jitter timing (Exponential distribution)
    3. Burst splitting (chunk random)
    4. Cover traffic injection
    5. Fake keepalive
    """
    
    def __init__(self, profile:str="interactive", size_bins=None, size_cdf=None, **kw):
        cfg = STEALTH_PROFILES[profile]
        self.profile = profile
        self.time_quantum_ms = cfg["time_quantum_ms"]
        # chaff_rate_pps può essere callable (curva diurna)
        self._chaff_fn = cfg["chaff_rate_pps"]
        self.dummy_prob = cfg["dummy_prob"]
        self._qr = qrng_stream(b"/stealth/morpher")
        self._use_mix = cfg["use_mix"]
        self._mix = PoissonMix(cfg["mix_base_rate_hz"], cfg["mix_cover_pps"], label=b"/stealth/mix") if self._use_mix else None
        self._size_bins=size_bins; self._size_cdf=size_cdf
    
    def _load_policy_params(self, policy: str) -> dict:
        """Carica parametri di morphing per policy"""
        policies = {
            "stealth": {
                "padding_min": 512,
                "padding_max": 2048,
                "jitter_lambda": 50,  # ms, Exponential mean
                "burst_split_prob": 0.8,
                "cover_traffic_prob": 0.3,
                "min_chunk_size": 256,
            },
            "balanced": {
                "padding_min": 128,
                "padding_max": 512,
                "jitter_lambda": 20,
                "burst_split_prob": 0.5,
                "cover_traffic_prob": 0.1,
                "min_chunk_size": 512,
            },
            "lowlatency": {
                "padding_min": 0,
                "padding_max": 128,
                "jitter_lambda": 5,
                "burst_split_prob": 0.2,
                "cover_traffic_prob": 0.0,
                "min_chunk_size": 1024,
            }
        }
        return policies.get(policy, policies["balanced"])
    
    def _add_padding(self, data: bytes) -> bytes:
        """
        Padding variabile.
        CRITICAL: NON usa multipli di 2^n per evitare fingerprinting.
        """
        pad_size = int(128 + self._qr.u01() * (512 - 128))
        
        # Aggiungi "noise" al padding size (±10%)
        noise = int((self._qr.u01() - 0.5) * 2 * (pad_size // 10))
        pad_size = max(0, pad_size + noise)
        
        padding = os.urandom(pad_size)
        
        # Format: [DATA_LEN:4][DATA][PADDING]
        import struct
        header = struct.pack("!I", len(data))
        
        return header + data + padding
    
    def _generate_jitter(self) -> float:
        """
        Genera delay random con Exponential distribution.
        
        Exponential è più "naturale" di Uniform perché simula
        timing umano/network reale.
        """
        # Exponential con lambda = mean delay
        jitter = self._qr.exp(1.0 / 50)  # assuming 50ms mean, but since params not used, hardcode or use cfg
        
        # Cap massimo per non degradare troppo
        max_jitter = 50 * 3
        return min(jitter, max_jitter)
    
    def _quantize(self, dt):
        q = self.time_quantum_ms/1000.0
        return max(q, round(dt/q)*q)
    
    def _exp_jitter(self, lam=1/0.02):
        return self._qr.exp(rate=lam)
    
    def _split_into_chunks(self, data: bytes) -> List[bytes]:
        """
        Split data in chunk di dimensione casuale.
        
        Anti-correlation: lunghezza chunk non predicibile.
        """
        if self._qr.u01() > 0.5:  # burst_split_prob
            # No split, invia tutto insieme
            return [data]
        
        chunks = []
        remaining = data
        min_chunk = 512  # hardcoded
        
        while len(remaining) > min_chunk * 2:
            # Chunk size casuale tra min e metà del rimanente
            chunk_size = int(min_chunk + self._qr.u01() * (len(remaining) // 2 - min_chunk))
            
            chunks.append(remaining[:chunk_size])
            remaining = remaining[chunk_size:]
        
        if remaining:
            chunks.append(remaining)
        
        return chunks
    
    def _should_inject_cover(self) -> bool:
        """Decide se iniettare cover traffic"""
        return self._qr.u01() < 0.1  # hardcoded
    
    def _generate_cover_traffic(self) -> bytes:
        """
        Genera chunk di cover traffic.
        
        Indistinguibile da traffico reale per observer esterno.
        """
        size = int(512 + self._qr.u01() * (4096 - 512))
        return os.urandom(size)
    
    def morph(self, data: bytes) -> list:
        chunks=[]
        # 1) Chunking + padding con target istogramma (se codebook presente)
        pos=0; n=len(data)
        while pos<n:
            if self._size_bins and self._size_cdf:
                u=self._qr.u01()
                sz=int(inv_cdf_sampler(self._size_bins, self._size_cdf, u))
            else:
                sz= min(1200, max(300, int(300 + 1000*self._qr.u01())))
            payload=data[pos:pos+sz]; pos+=sz
            if len(payload)<sz: payload = payload + b"\x00"*(sz-len(payload))
            # 2) Timing (prima deperiodize, poi quantize)
            base_dt = self._exp_jitter(lam=1/0.05)  # media 50ms
            dt = self._quantize(base_dt)
            # 3) Inserimento (mix se attivo, altrimenti pass-through con sleep esterno)
            pkt = (dt, payload)
            chunks.append(pkt)
        # 4) Sanitizzazione spettrale sugli inter-arrival
        intervals=[c[0] for c in chunks]
        intervals = deperiodize_intervals(intervals, max_shift_ms=8.0, rng_u01=self._qr.u01)
        chunks=[(intervals[i], chunks[i][1]) for i in range(len(chunks))]
        # 5) Mix layer: schedula nel buffer con cover loops (profilo "blindato")
        out=[]
        if self._mix:
            for _,pl in chunks: self._mix.ingest(pl, egress_hint="auto")
            self._mix.pump_cover()
            out = self._mix.due()   # ritorna MixPacket (ts_due, payload,...)
        else:
            # ritorna come (delay_s, payload) da rispettare a monte
            out = chunks
        return out
    
    async def send_morphed(self, chunks: List[MorphedChunk], 
                          send_callback) -> List[bool]:
        """
        Invia chunk con timing morfato.
        
        send_callback: async function(data: bytes) -> bool
        """
        results = []
        
        for chunk in chunks:
            # Applica jitter delay
            await asyncio.sleep(chunk.send_delay_ms / 1000)
            
            # Invia
            success = await send_callback(chunk.data)
            results.append(success)
        
        return results


class CoverTrafficGenerator:
    """
    Genera cover traffic continuo tra nodi idle.
    
    Obiettivo: observer vede sempre traffico, anche con 0 utenti.
    """
    
    def __init__(self, node_id: str, peers: List[str], 
                 policy: str = "balanced"):
        self.node_id = node_id
        self.peers = peers
        self.policy = policy
        self.running = False
        self.rng = SystemRandom()
        
        # Parametri per policy
        self.rates = {
            "stealth": {"mean_interval_s": 3, "size_range": (1024, 8192)},
            "balanced": {"mean_interval_s": 5, "size_range": (512, 4096)},
            "lowlatency": {"mean_interval_s": 10, "size_range": (256, 2048)},
        }
    
    async def start(self, send_callback):
        """
        Avvia generazione continua.
        
        send_callback: async function(peer: str, data: bytes) -> bool
        """
        self.running = True
        rate = self.rates.get(self.policy, self.rates["balanced"])
        
        while self.running:
            # Scegli peer random
            peer = self.rng.choice(self.peers)
            
            # Genera chunk fake
            size = self.rng.randint(*rate["size_range"])
            fake_data = os.urandom(size)
            
            # Invia
            await send_callback(peer, fake_data)
            
            # Attendi con Poisson distribution
            wait = random.expovariate(1.0 / rate["mean_interval_s"])
            await asyncio.sleep(wait)
    
    def stop(self):
        """Ferma generazione"""
        self.running = False


class TrafficAnalysisDetector:
    """
    Detector per timing attack / traffic analysis.
    
    Se un nodo risponde con timing troppo regolare,
    potrebbe essere un attaccante che sta misurando.
    """
    
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.response_times: List[float] = []
    
    def record_response(self, latency_ms: float):
        """Registra tempo di risposta"""
        self.response_times.append(latency_ms)
        
        if len(self.response_times) > self.window_size:
            self.response_times.pop(0)
    
    def detect_timing_attack(self) -> Optional[str]:
        """
        Detecta timing attack basandosi su variance.
        
        Returns: None se OK, messaggio se suspicious.
        """
        if len(self.response_times) < self.window_size:
            return None
        
        import statistics
        
        mean = statistics.mean(self.response_times)
        stdev = statistics.stdev(self.response_times)
        
        # Coefficient of variation (CV)
        cv = stdev / mean if mean > 0 else 0
        
        # CV troppo basso = timing troppo regolare = suspicious
        if cv < 0.1:
            return f"Timing too regular: CV={cv:.3f}"
        
        # CV troppo alto = timing erratico = possibile scan
        if cv > 2.0:
            return f"Timing too erratic: CV={cv:.3f}"
        
        return None


# Usage example
async def main():
    # Setup morpher
    morpher = TrafficMorpher(seed=b"test", policy="stealth")
    
    # Data originale
    original_data = b"Secret message to transmit"
    
    # Morph
    morphed = morpher.morph(original_data)
    
    print(f"Original: {len(original_data)} bytes")
    print(f"Morphed into {len(morphed)} chunks:")
    for i, chunk in enumerate(morphed):
        print(f"  Chunk {i}: {len(chunk.data)} bytes, "
              f"delay={chunk.send_delay_ms:.1f}ms, "
              f"cover={chunk.is_cover}")
    
    # Simula invio
    async def fake_send(data: bytes) -> bool:
        await asyncio.sleep(0.01)  # Simula network
        print(f"  -> Sent {len(data)} bytes")
        return True
    
    results = await morpher.send_morphed(morphed, fake_send)
    print(f"All sent: {all(results)}")
    
    # Test cover traffic
    print("\n--- Cover Traffic Test ---")
    cover_gen = CoverTrafficGenerator(
        node_id="node-1",
        peers=["node-2", "node-3"],
        policy="balanced"
    )
    
    async def fake_peer_send(peer: str, data: bytes) -> bool:
        print(f"Cover -> {peer}: {len(data)} bytes")
        return True
    
    # Run per 5 secondi
    task = asyncio.create_task(cover_gen.start(fake_peer_send))
    await asyncio.sleep(5)
    cover_gen.stop()
    await task

if __name__ == "__main__":
    asyncio.run(main())
