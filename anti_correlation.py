# anti_correlation.py - Timing obfuscation per battere correlation attack
from typing import Dict, Any, List
try:
    import numpy as np
    import scipy.signal as sp
    from sklearn.metrics import roc_auc_score
except Exception:
    np=None; sp=None; roc_auc_score=None
from dataclasses import dataclass
from detectability_lab import mutual_information, cross_corr_max

@dataclass
class TrafficEvent:
    """Evento di traffico (send o receive)"""
    timestamp: float
    size: int
    direction: str  # "send" o "receive"

class AntiCorrelationEngine:
    """
    Engine per rendere impossibile correlation attack.
    
    Strategia multi-layer:
    1. Chaff traffic (rumore costante)
    2. Timing quantization (arrotonda timestamp)
    3. Dummy sends (packet vuoti a tempo)
    4. Adaptive delay injection
    """
    
    def __init__(self, policy: str = "stealth"):
        self.policy = policy
        self.params = self._load_params(policy)
        self.chaff_active = True
        self.metrics = {"mi":None,"xcorr":None,"psd_peaks":None}
    
    def _load_params(self, policy: str) -> dict:
        """Parametri anti-correlation per policy"""
        return {
            "stealth": {
                "chaff_rate_pps": 20,      # 20 packet/sec di rumore
                "time_quantum_ms": 100,     # Arrotonda a 100ms
                "dummy_prob": 0.3,          # 30% packet sono dummy
                "delay_variance": 0.5,      # ±50% variance su delay
            },
            "balanced": {
                "chaff_rate_pps": 10,
                "time_quantum_ms": 50,
                "dummy_prob": 0.15,
                "delay_variance": 0.3,
            },
            "lowlatency": {
                "chaff_rate_pps": 5,
                "time_quantum_ms": 20,
                "dummy_prob": 0.05,
                "delay_variance": 0.1,
            }
        }[policy]
    
    def spectral_peaks(self, series, fs_hz=50.0, topk=3):
        f, Pxx = sp.welch(np.asarray(series), fs=fs_hz, nperseg=min(256, len(series)))
        idx = np.argsort(Pxx)[::-1][:topk]
        return [(float(f[i]), float(Pxx[i])) for i in idx]
    
    def evaluate(self, ingress_times, egress_times):
        # esistente: correlazioni basi...
        self.metrics["mi"] = mutual_information(ingress_times, egress_times, bins=64)
        self.metrics["xcorr"] = cross_corr_max(ingress_times, egress_times, max_lag=200)
        self.metrics["psd_peaks"] = self.spectral_peaks(np.diff(ingress_times), fs_hz=50.0)
        return self.metrics
    
    async def chaff_generator(self, send_callback):
        """
        Genera traffico chaff continuo.
        
        Obiettivo: Eve vede sempre traffico, anche quando user è idle.
        Correlazione diventa impossibile.
        """
        rate = self.params["chaff_rate_pps"]
        interval = 1.0 / rate
        
        while self.chaff_active:
            # Genera packet dummy
            size = np.random.randint(64, 1400)
            dummy_data = np.random.bytes(size)
            
            # Marca come chaff (encrypted header che solo nodi SATL capiscono)
            await send_callback(dummy_data, is_chaff=True)
            
            # Wait con jitter
            wait = np.random.exponential(interval)
            await asyncio.sleep(wait)
    
    def quantize_timing(self, events: List[TrafficEvent]) -> List[TrafficEvent]:
        """
        Quantizza timestamp per ridurre precisione.
        
        Esempio: 
        - Vero timestamp: 1234567.891234
        - Quantized (100ms): 1234567.900000
        
        Eve non può correlarmi con precisione <100ms.
        """
        quantum_sec = self.params["time_quantum_ms"] / 1000
        
        quantized = []
        for event in events:
            # Arrotonda a multiplo di quantum
            quantized_time = round(event.timestamp / quantum_sec) * quantum_sec
            
            quantized.append(TrafficEvent(
                timestamp=quantized_time,
                size=event.size,
                direction=event.direction
            ))
        
        return quantized
    
    def inject_dummy_sends(self, events: List[TrafficEvent]) -> List[TrafficEvent]:
        """
        Inietta dummy send a intervalli casuali.
        
        Eve vede send che non corrispondono a receive downstream.
        """
        dummy_prob = self.params["dummy_prob"]
        
        augmented = []
        for event in events:
            augmented.append(event)
            
            # Con prob X, inietta dummy subito dopo
            if np.random.random() < dummy_prob:
                dummy = TrafficEvent(
                    timestamp=event.timestamp + np.random.exponential(0.05),
                    size=np.random.randint(64, 1400),
                    direction="send"
                )
                augmented.append(dummy)
        
        return augmented
    
    def adaptive_delay_injection(self, events: List[TrafficEvent]) -> List[TrafficEvent]:
        """
        Inietta delay adattivo per spezzare correlazione.
        
        Se Eve vede pattern troppo regolare, aumenta randomness.
        """
        variance = self.params["delay_variance"]
        
        delayed = []
        cumulative_delay = 0
        
        for i, event in enumerate(events):
            if i == 0:
                delayed.append(event)
                continue
            
            # Calcola delay normale
            normal_delay = event.timestamp - events[i-1].timestamp
            
            # Aggiungi variance random
            added_delay = normal_delay * np.random.uniform(-variance, variance)
            added_delay = max(0, added_delay)  # No negative delay
            
            cumulative_delay += added_delay
            
            delayed.append(TrafficEvent(
                timestamp=event.timestamp + cumulative_delay,
                size=event.size,
                direction=event.direction
            ))
        
        return delayed
    
    def apply_full_obfuscation(self, events: List[TrafficEvent]) -> List[TrafficEvent]:
        """
        Applica tutte le tecniche in pipeline.
        """
        # 1. Quantize timing
        events = self.quantize_timing(events)
        
        # 2. Inject dummies
        events = self.inject_dummy_sends(events)
        
        # 3. Adaptive delay
        events = self.adaptive_delay_injection(events)
        
        # Sort per timestamp
        events.sort(key=lambda e: e.timestamp)
        
        return events


class CorrelationSimulator:
    """
    Simula correlation attack per testare effectiveness.
    """
    
    @staticmethod
    def simulate_eve_attack(user_traffic: List[TrafficEvent],
                           node_traffic: List[TrafficEvent],
                           window_sec: float = 60.0) -> float:
        """
        Simula Eve che tenta correlazione.
        
        Returns: correlation coefficient (0-1)
        - 0.0-0.3: Cannot correlate (✅)
        - 0.3-0.7: Suspicious but not conclusive (⚠️)
        - 0.7-1.0: Correlated (❌)
        """
        # Estrai timeseries con bin temporali
        def to_timeseries(events, bin_size_sec=0.1):
            max_time = max(e.timestamp for e in events)
            bins = np.arange(0, max_time + bin_size_sec, bin_size_sec)
            
            # Volume per bin
            volumes = np.zeros(len(bins) - 1)
            for event in events:
                bin_idx = int(event.timestamp / bin_size_sec)
                if bin_idx < len(volumes):
                    volumes[bin_idx] += event.size
            
            return volumes
        
        user_ts = to_timeseries(user_traffic)
        node_ts = to_timeseries(node_traffic)
        
        # Pearson correlation
        min_len = min(len(user_ts), len(node_ts))
        user_ts = user_ts[:min_len]
        node_ts = node_ts[:min_len]
        
        if len(user_ts) < 10:
            return 0.0
        
        correlation = np.corrcoef(user_ts, node_ts)[0, 1]
        
        return abs(correlation)  # Absolute value


def test_correlation_resistance():
    """
    Test: SATL con anti-correlation batte Eve?
    """
    print("="*60)
    print("CORRELATION ATTACK RESISTANCE TEST")
    print("="*60)
    
    # Genera traffico user originale
    print("\n1. Generating original user traffic...")
    user_traffic = []
    current_time = 0
    for _ in range(100):
        current_time += np.random.exponential(0.5)
        user_traffic.append(TrafficEvent(
            timestamp=current_time,
            size=np.random.randint(500, 1500),
            direction="send"
        ))
    
    # Simula node traffic (copia con delay)
    node_traffic = []
    for event in user_traffic:
        node_traffic.append(TrafficEvent(
            timestamp=event.timestamp + np.random.normal(0.05, 0.01),  # 50ms delay
            size=event.size + np.random.randint(-100, 100),
            direction="receive"
        ))
    
    # Test 1: Senza obfuscation
    print("\n2. Testing WITHOUT obfuscation...")
    corr_without = CorrelationSimulator.simulate_eve_attack(
        user_traffic, node_traffic
    )
    print(f"   Correlation: {corr_without:.3f}")
    
    if corr_without > 0.7:
        print(f"   ❌ DETECTED by Eve")
    else:
        print(f"   ⚠️  Suspicious")
    
    # Test 2: Con obfuscation "stealth"
    print("\n3. Testing WITH obfuscation (stealth policy)...")
    engine = AntiCorrelationEngine(policy="stealth")
    
    obfuscated_user = engine.apply_full_obfuscation(user_traffic.copy())
    obfuscated_node = engine.apply_full_obfuscation(node_traffic.copy())
    
    corr_with = CorrelationSimulator.simulate_eve_attack(
        obfuscated_user, obfuscated_node
    )
    print(f"   Correlation: {corr_with:.3f}")
    
    if corr_with < 0.3:
        print(f"   ✅ CANNOT be correlated by Eve")
    elif corr_with < 0.7:
        print(f"   ⚠️  Suspicious but not conclusive")
    else:
        print(f"   ❌ Still detected")
    
    # Risultato
    improvement = (corr_without - corr_with) / corr_without
    print(f"\n4. RESULT:")
    print(f"   Correlation reduction: {improvement:.1%}")
    
    print("\n" + "="*60)
    
    if corr_with < 0.3:
        print("✅ VERDICT: Anti-correlation effective")
        print("   Eve cannot correlate user with nodes")
        return True
    else:
        print("❌ VERDICT: Anti-correlation insufficient")
        print(f"   Need more aggressive obfuscation")
        print(f"   Current correlation: {corr_with:.3f} (target: <0.3)")
        return False


if __name__ == "__main__":
    import asyncio
    
    success = test_correlation_resistance()
    
    if not success:
        print("\n💡 Suggestions:")
        print("   1. Increase chaff_rate_pps to 50+")
        print("   2. Reduce time_quantum_ms to 50ms")
        print("   3. Increase dummy_prob to 0.5")
        print("   4. Consider using decoy circuits")
