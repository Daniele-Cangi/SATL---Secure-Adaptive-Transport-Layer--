# SATL 3.0 - TLS 1.3 Configuration

## Overview

This directory contains TLS 1.3 reverse proxy configuration using Caddy server.

## Architecture

```
┌─────────────┐     HTTPS/TLS 1.3      ┌───────────┐     HTTP      ┌──────────────┐
│   Client    │ ──────────────────────▶│   Caddy   │ ────────────▶ │   Uvicorn    │
│  (SPO/CP)   │  :9000/:9001/:9002     │  Proxy    │  :19000-19002 │  Forwarders  │
└─────────────┘                        └───────────┘               └──────────────┘
```

## Port Mapping

| Service | Frontend (TLS) | Backend (HTTP) | Metrics |
|---------|----------------|----------------|---------|
| Guard   | :9000 (HTTPS)  | :19000 (HTTP)  | :10000  |
| Middle  | :9001 (HTTPS)  | :19001 (HTTP)  | :10001  |
| Exit    | :9002 (HTTPS)  | :19002 (HTTP)  | :10002  |

## Installation

### Windows

```powershell
# Via winget
winget install Caddy.Caddy

# Or download from https://caddyserver.com/download
```

### Linux/Mac

```bash
# Ubuntu/Debian
sudo apt install caddy

# macOS
brew install caddy
```

## Usage

### 1. Start Caddy (TLS termination)

```batch
start_caddy.bat
```

This will:
- Generate self-signed certificates for localhost
- Listen on ports 9000/9001/9002 with TLS 1.3
- Proxy requests to backend ports 19000/19001/19002

### 2. Start Forwarders (backend HTTP)

```batch
start_forwarders_tls.bat
```

This will:
- Start 3 uvicorn instances on ports 19000/19001/19002
- Set SATL_MODE=performance
- Enable SATL_ALLOW_COMPAT for testnet

### 3. Verify TLS 1.3

```bash
# Test Guard endpoint
curl -vk https://localhost:9000/health

# Look for these in output:
# * TLSv1.3 (IN), TLS handshake, ...
# * SSL connection using TLSv1.3 / TLS_AES_128_GCM_SHA256
```

Expected output snippet:
```
* SSL connection using TLSv1.3 / TLS_AES_128_GCM_SHA256
* ALPN, server accepted to use h2
* Server certificate:
*  subject: [...]
*  start date: [...]
*  expire date: [...]
< HTTP/2 200
< strict-transport-security: max-age=31536000; includeSubDomains
< x-content-type-options: nosniff
< x-frame-options: DENY
```

## Security Headers

All endpoints include:

- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- Server header removed

## Production Deployment

### Let's Encrypt (Auto HTTPS)

For production with real domain:

```caddyfile
# Replace localhost with your domain
https://guard.satl.example.com {
    tls {
        protocols tls1.3
    }
    # ... rest of config
}
```

Caddy will automatically obtain Let's Encrypt certificates.

### Client Certificate Authentication (mTLS)

For mutual TLS:

```caddyfile
https://localhost:9000 {
    tls internal {
        protocols tls1.3
        client_auth {
            mode require_and_verify
            trusted_ca_cert_file /path/to/ca.crt
        }
    }
    # ... rest of config
}
```

## Troubleshooting

### Caddy not found

```batch
# Check installation
where caddy

# If not found, install via winget
winget install Caddy.Caddy

# Or download manually from https://caddyserver.com/download
```

### Permission denied on ports

Caddy requires admin privileges for ports < 1024 on some systems.

On Windows: Run `start_caddy.bat` as Administrator

### Certificate errors

For self-signed certs (dev/testing), use `-k` flag with curl:
```bash
curl -vk https://localhost:9000/health
```

For production, ensure domain points to server and Caddy will auto-provision Let's Encrypt cert.

### Backend connection refused

Ensure forwarders are running on backend ports:
```bash
# Check if uvicorn is listening
netstat -an | findstr "19000 19001 19002"
```

## Logs

Logs are written to:
- `logs/caddy/guard.log`
- `logs/caddy/middle.log`
- `logs/caddy/exit.log`

Level: WARN (minimal logging for production)

## Performance

Caddy adds ~1-2ms latency for TLS termination.

Expected performance with TLS:
- P95 latency: 25-30ms (vs 20-25ms HTTP)
- Throughput: ~200-300 pkt/s (minimal impact)

## Acceptance Criteria

✅ **PASS Criteria**:
1. `curl -vk https://localhost:9000/health` shows **TLSv1.3**
2. HSTS header present
3. No HTTP/plain access on :9000/:9001/:9002
4. Backend forwarders respond via proxy

## Next Steps

After TLS validation:
1. Update SPO rotation pack to use HTTPS endpoints
2. Configure mutual TLS (mTLS) for client authentication
3. Deploy to production with Let's Encrypt
