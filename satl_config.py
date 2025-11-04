# satl_config.py
from cover_controller import diurnal_cover_pps
STEALTH_PROFILES = {
  "interactive": {
    "time_quantum_ms": 100,
    "chaff_rate_pps":  lambda: diurnal_cover_pps(20.0, 0.25),
    "dummy_prob":      0.25,
    "mix_base_rate_hz":5.0,   # usato solo se mix abilitato
    "mix_cover_pps":   0.0,
    "quantum_enabled": True,
    "use_mix":         False,
    "shards":          2,
    "rotation_s":      20
  },
  "blindato": {
    "time_quantum_ms": 20,
    "chaff_rate_pps":  lambda: diurnal_cover_pps(50.0, 0.35),
    "dummy_prob":      0.40,
    "mix_base_rate_hz":6.0,
    "mix_cover_pps":   25.0,
    "quantum_enabled": True,
    "use_mix":         True,
    "shards":          4,
    "rotation_s":      15
  }
}