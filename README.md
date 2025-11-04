# SATL - Secure Adaptive Transport Layer

**Version:** 3.0-rc1
**Status:** Release Candidate
**Date:** 2025-11-04
**License:** Apache 2.0

---

## Overview

SATL 3.0 is a 3-hop onion routing system with post-quantum cryptography, anti-replay protection, and stealth traffic analysis resistance.

---

## What SATL Provides

### Core Innovation

SATL combines three distinct capabilities in a single transport layer:

1. **Post-quantum signatures** (Dilithium3) for authentication in distributed networks
2. **Adaptive backend selection** (memory vs SQLite) for performance vs persistence tradeoffs
3. **Traffic analysis resistance** through configurable stealth profiles

### Use Cases

**Privacy-Enhanced Communication:**

- Applications requiring IP address anonymization
- Multi-hop routing without centralized trust
- Protection against network-level surveillance

**Post-Quantum Research:**

- Testing PQC signature schemes in network protocols
- Benchmarking Dilithium3 performance in real-world scenarios
- Evaluating hybrid classical/quantum-resistant systems

**Distributed Systems:**

- Anonymous message passing between nodes
- Decentralized service routing
- Traffic obfuscation in peer-to-peer networks

**Security Testing:**

- Penetration testing with anonymized traffic sources
- Red team operations requiring attribution resistance
- Controlled traffic analysis resistance experiments

### Technical Differentiators

**Compared to Tor:**

- Dilithium3 signatures (quantum-resistant) vs RSA
- Configurable backends (memory/SQLite) vs fixed consensus
- Python-based (rapid prototyping) vs C (production hardening)
- Focused scope (3-hop transport) vs full ecosystem

**Compared to I2P:**

- Stateless packet forwarding vs garlic routing
- REST API interface vs native protocols
- Prometheus metrics integration vs custom monitoring
- Profile-based deployment vs monolithic configuration

**Compared to VPN:**

- Multi-hop unlinkability vs single-hop tunnel
- No trusted operator required vs VPN provider trust
- Per-packet routing vs persistent connection
- Traffic shaping options vs fixed characteristics

### Limitations

- **Not production-ready**: RC1 status, requires further hardening
- **Performance overhead**: 30ms P95 latency vs direct connection
- **Python implementation**: Lower throughput than C/Rust alternatives
- **No mobile support**: Designed for server-to-server communication
- **Limited node discovery**: Static configuration vs dynamic peer discovery

---

## Architecture

```
Client → Guard → Middle → Exit → Destination
         (9000)  (9001)   (9002)
```

**Core Components:**
- **3-hop onion routing**: Triple-layer encryption with independent forwarding nodes
- **Anti-replay window**: SQLite-backed or in-memory state tracking
- **PQC signatures**: Dilithium3 signatures for rotation pack authentication
- **Stealth traffic shaping**: Queue delays, packet reordering, cover traffic
- **Prometheus metrics**: RSS memory, operation timings, backend mode

---

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/Daniele-Cangi/SATL---Secure-Adaptive-Transport-Layer--.git
cd SATL---Secure-Adaptive-Transport-Layer--

# Install dependencies
pip install -r requirements.txt
```

### Running with Profiles

**Performance Mode** (memory backend, multi-worker):
```powershell
.\profiles\switch_profile.ps1 perf
```

**Stealth Mode** (SQLite backend, traffic shaping):
```powershell
.\profiles\switch_profile.ps1 stealth
```

**Production Mode** (TLS 1.3 termination via Caddy):
```powershell
.\profiles\switch_profile.ps1 prod
```

**Stop All Services:**
```powershell
.\profiles\stop_all.ps1
```

---

## Performance (Bare Metal)

Test configuration: zero queue delays, no stealth features, direct HTTP.

| Concurrency | P95 Latency | Success Rate | Throughput |
|-------------|-------------|--------------|------------|
| 10 clients  | 13.05ms     | 100%         | ~250 pkt/s |
| 50 clients  | 77.14ms     | 100%         | ~400 pkt/s |

**Configuration:**
- Workers: 3 (guard/middle) + 4 (exit)
- HTTP parser: httptools (C parser)
- Window backend: MemoryWindowStore
- Connection pooling: 200 keepalive connections

Results stored in: `perf_artifacts/performance_bare_results.json`

---

## Security Features

### Post-Quantum Cryptography (PQC)

- **Algorithm**: Dilithium3 (NIST PQC standard)
- **Key sizes**: Public=1952 bytes, Secret=4000 bytes, Signature=3293 bytes
- **Validation**: Fail-closed (rejects invalid signatures)

Generate keys:
```bash
python -c "from pqc.dilithium3_provider import Dilithium3Provider; Dilithium3Provider().generate_keys()"
```

Keys stored in: `pqc_keys/dilithium3_secret.key` and `dilithium3_public.key`

### Anti-Replay Protection

**Dual Backend System:**

1. **MemoryWindowStore** (performance mode)
   - In-memory dict lookup: O(1)
   - No persistence across restarts
   - Suitable for testing and high-throughput scenarios

2. **RotationWindowStore** (production mode)
   - SQLite WAL with atomic operations
   - Persistent across restarts
   - Optimizations: mmap, prepared statements, batch GC

Backend auto-selected based on `SATL_MODE` environment variable.

### TLS 1.3 Enforcement

- `TRANSPORT_SEC_LEVEL='tls13'` in `spo_rotation_pack.py`
- Caddy reverse proxy enforces TLS 1.3 at infrastructure layer
- Test with: `python test_tls_handshake.py`

---

## Testing

### Security Tests

```bash
pytest tests/test_spo_security.py -v
```

**Result:** 11/11 tests PASS (100% attack detection rate)

Validates:
- Replay attack detection
- Tampered parameter rejection
- Expired rotation pack rejection
- Invalid signature rejection
- Timestamp manipulation detection
- Channel isolation

### Performance Tests

```bash
# Bare metal (no stealth)
python test_performance_bare.py

# Endurance (1 hour)
python test_endurance_1h.py
```

### PQC Tests

```bash
pytest tests/test_pqc_dilithium3.py -v
```

**Result:** 8/8 tests PASS

---

## Configuration

### Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `SATL_MODE` | `performance` \| `stealth` | `performance` | Operating mode |
| `SATL_WINDOW_BACKEND` | `memory` \| `sqlite` \| `auto` | `auto` | Anti-replay backend |
| `SATL_PQC` | `0` \| `1` | `1` | Enable PQC signatures |
| `SATL_ALLOW_COMPAT` | `0` \| `1` | (unset) | Onion crypto compatibility (not recommended) |

### Profiles

**Performance Profile:**
- Memory backend (no I/O overhead)
- Multi-worker mode (3+3+4)
- httptools C parser
- No access logs
- Connection pooling (200 keepalive)

**Stealth Profile:**
- SQLite backend (persistent)
- Queue delays: 50-150ms per hop
- Packet reordering: 10%
- Cover traffic enabled
- Single worker per node

**Production Profile:**
- SQLite backend (persistent)
- Caddy TLS 1.3 termination
- Fail-closed validation
- Comprehensive metrics

---

## Metrics

Prometheus metrics available on ports 10000/10001/10002:

```bash
# RSS memory tracking
curl http://localhost:10000/metrics | grep satl_process_rss_bytes

# Window backend mode
curl http://localhost:10000/metrics | grep satl_window_backend_mode

# Operation timings
curl http://localhost:10000/metrics | grep satl_window_store_op_ms
```

**Available metrics:**
- `satl_process_rss_bytes{role}` - Process memory usage
- `satl_window_backend_mode{mode}` - Backend type (memory/sqlite)
- `satl_window_store_op_ms{op,stat}` - Operation timings (exists/add/gc)
- `satl_circuit_build_time_ms{stat}` - Circuit build latency
- `satl_packets_forwarded_total` - Total packets forwarded
- `satl_errors_total{type}` - Error counts by type

---

## Documentation

- **[RELEASE_NOTES_v3.0-rc1.md](RELEASE_NOTES_v3.0-rc1.md)** - Comprehensive release documentation (700+ lines)
- **[SATL3_TEST_MATRIX.md](SATL3_TEST_MATRIX.md)** - Complete test results and validation
- **[SPO_SECURITY_FINAL_REPORT.md](SPO_SECURITY_FINAL_REPORT.md)** - Security analysis and threat model

---

## Architecture Details

### Request Flow

```
Client
  ↓
Guard (port 9000)
  ├─ Decrypt layer 1
  ├─ Anti-replay check (window store)
  ↓
Middle (port 9001)
  ├─ Decrypt layer 2
  ├─ Anti-replay check
  ↓
Exit (port 9002)
  ├─ Decrypt layer 3
  ├─ Forward to destination
  ↓
Response
```

### Backend Selection Logic

```
SATL_WINDOW_BACKEND=memory    → MemoryWindowStore (explicit)
SATL_WINDOW_BACKEND=sqlite    → RotationWindowStore (explicit)
SATL_WINDOW_BACKEND=auto (default):
  ├─ SATL_MODE=performance    → MemoryWindowStore
  └─ SATL_MODE=stealth        → RotationWindowStore (SQLite)
```

### HTTP Connection Pooling

```python
_HTTP = httpx.AsyncClient(
    http2=False,                           # HTTP/1.1 only
    limits=httpx.Limits(
        max_keepalive_connections=200,     # Reuse connections
        max_connections=200                # Total pool size
    ),
    timeout=httpx.Timeout(5.0),            # Fast timeout
    headers={'Connection': 'keep-alive'}   # Explicit keep-alive
)
```

**Benefits:**
- Zero TCP handshake overhead
- Connection reuse across requests
- Automatic connection management

---

## Migration from v2.0

### Anti-Replay Window

Migrate from JSON to SQLite:
```bash
python tools/migrate_window_json_to_sqlite.py
```

**Files created:**
- `spo_window.db` (SQLite database)
- `spo_window.db-wal` (Write-Ahead Log)
- `spo_window.db-shm` (Shared Memory)

**Old files (can be deleted):**
- `spo_sliding_window.json`

### PQC Keys

Generate Dilithium3 keys (authority only):
```bash
python -c "from pqc.dilithium3_provider import Dilithium3Provider; Dilithium3Provider().generate_keys()"
```

Distribute `pqc_keys/dilithium3_public.key` to all nodes.

---

## Known Limitations

### Endurance Test (1 Hour)

**Status:** Executed - results available

**Test:** `python test_endurance_1h.py`

**Acceptance criteria:**
- Duration: 3600 seconds
- Success rate: ≥ 99%
- RSS drift: < 100 MB/hour
- P95 latency degradation: < 10% vs baseline
- No 500 errors

Results: `perf_artifacts/endurance_1h_results.json`

### Stealth Mode Validation

**Status:** Implementation complete, 600-second KS/xcorr/AUC validation pending

**Test:** `test_stealth_600s.py` (not yet created)

**Goal:** Validate indistinguishability from baseline traffic using statistical tests.

---

## Development

### File Structure

```
SATL2.0/
├── satl_forwarder_daemon.py     # Core forwarder logic
├── spo_rotation_pack.py          # SPO signed parameter operations
├── spo_window_store.py           # Anti-replay window (Memory/SQLite)
├── prometheus_exporter.py        # Metrics collection
├── pqc/
│   └── dilithium3_provider.py    # PQC signature provider
├── profiles/
│   ├── switch_profile.ps1        # Profile switcher
│   └── stop_all.ps1              # Stop all services
├── tests/
│   ├── test_spo_security.py      # Security validation (11/11 PASS)
│   ├── test_pqc_dilithium3.py    # PQC tests (8/8 PASS)
│   └── test_spo_window_persist.py # Window store tests (8/8 PASS)
├── perf_artifacts/
│   ├── performance_bare_results.json
│   └── endurance_1h_results.json
└── tools/
    └── migrate_window_json_to_sqlite.py
```

### Contributing

1. Run all tests before committing:
   ```bash
   pytest tests/ -v
   python test_performance_bare.py
   ```

2. Update SATL3_TEST_MATRIX.md with test results

3. Follow commit message format:
   ```
   [Component] Brief description

   - Detailed change 1
   - Detailed change 2

   Tests: X/Y PASS
   ```

---

## License

This project is licensed under the **Apache License 2.0**.

See [LICENSE](LICENSE) for full terms.

**Key Points:**

- ✅ Commercial use allowed
- ✅ Modification allowed
- ✅ Distribution allowed
- ✅ Patent use allowed
- ⚠️ Must include license and copyright notice
- ⚠️ Changes must be documented
- ⚠️ No warranty provided

---

## Authors

SATL 3.0 Research Team

For questions or issues, see documentation in `docs/` directory.

---

**Version History:**

- **v3.0-rc1** (2025-11-04): Performance optimization, dual backend, PQC integration, Apache 2.0 license
- **v2.0** (2025-11-02): Initial 3-hop implementation with stealth features
