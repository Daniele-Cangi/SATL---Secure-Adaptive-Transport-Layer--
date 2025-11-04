# SATL 3.0 - Forwarder Restart Procedure (PERFORMANCE PROFILE)

## Objective
Switch forwarders from STEALTH mode to PERFORMANCE mode for bare metal testing.

## Current Configuration
```python
# testnet_beta_policy.py (STEALTH mode)
per_hop_queue_delay_ms = (50, 150)
reorder_rate = 0.1
```

## Target Configuration
```python
# testnet_beta_policy.py (PERFORMANCE mode)
per_hop_queue_delay_ms = (0, 0)
reorder_rate = 0.0
```

## Procedure

### 1. Stop Current Forwarders
In each forwarder terminal window (guard, middle, exit):
```
Press Ctrl+C
```

### 2. Modify Policy File
Edit `testnet_beta_policy.py`:
```python
# Line ~45: Change queue delays
per_hop_queue_delay_ms = (0, 0)  # Was: (50, 150)

# Line ~48: Disable reordering
reorder_rate = 0.0  # Was: 0.1
```

### 3. Restart Forwarders (NEW TERMINALS)

**Terminal 1 (Guard)**:
```bash
cd /c/Users/dacan/OneDrive/Desktop/SATL2.0
python satl_forwarder_daemon.py --role guard --port 9000
```

**Terminal 2 (Middle)**:
```bash
cd /c/Users/dacan/OneDrive/Desktop/SATL2.0
python satl_forwarder_daemon.py --role middle --port 9001
```

**Terminal 3 (Exit)**:
```bash
cd /c/Users/dacan/OneDrive/Desktop/SATL2.0
python satl_forwarder_daemon.py --role exit --port 9002
```

### 4. Verify Configuration
Check forwarder startup logs for:
```
Queue delay: 0-0ms
Reorder rate: 0.0
```

### 5. Run Performance Test
```bash
python test_performance_bare.py
```

**Expected Results**:
- P95 latency < 100ms @ concurrency=10
- Success rate >= 99%

**If FAIL (P95 > 100ms)**:
→ Architectural overhead detected
→ Profile: crypto ops, HTTP, Python GIL, async scheduler
→ Document exact value and concurrency level

## Revert to STEALTH Mode

### 1. Stop Forwarders (Ctrl+C in all terminals)

### 2. Restore Policy
```python
per_hop_queue_delay_ms = (50, 150)
reorder_rate = 0.1
```

### 3. Restart with STEALTH config
Same restart procedure as above.
