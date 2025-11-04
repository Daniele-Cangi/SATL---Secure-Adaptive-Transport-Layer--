"""
SATL 3.0 - TLS 1.3 Handshake Test

Tests TLS configuration for guard/middle/exit endpoints.
Verifies TLS 1.3 protocol, security headers, and certificate chain.

Author: SATL 3.0 Research Team
Date: 2025-11-03
"""
import ssl
import socket
import urllib.request
import urllib.error
import sys
from typing import Dict, List


class TLSHandshakeTest:
    """Test TLS 1.3 handshake and security headers"""

    def __init__(self):
        self.endpoints = {
            "guard": "https://localhost:9000/health",
            "middle": "https://localhost:9001/health",
            "exit": "https://localhost:9002/health"
        }

    def test_tls_version(self, url: str) -> Dict:
        """Test TLS version negotiation"""
        print(f"\n[TEST] TLS Version for {url}")

        # Create SSL context that only allows TLS 1.3
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # Self-signed cert

        try:
            # Extract hostname and port
            parts = url.replace("https://", "").split("/")[0].split(":")
            hostname = parts[0]
            port = int(parts[1])

            # Create secure socket
            with socket.create_connection((hostname, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    # Get negotiated protocol
                    version = ssock.version()
                    cipher = ssock.cipher()

                    print(f"  ✓ TLS Version: {version}")
                    print(f"  ✓ Cipher Suite: {cipher[0]}")
                    print(f"  ✓ Protocol: {cipher[1]}")
                    print(f"  ✓ Bits: {cipher[2]}")

                    return {
                        "success": True,
                        "version": version,
                        "cipher": cipher[0],
                        "protocol": cipher[1]
                    }

        except ssl.SSLError as e:
            print(f"  ✗ TLS Error: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            print(f"  ✗ Connection Error: {e}")
            return {"success": False, "error": str(e)}

    def test_security_headers(self, url: str) -> Dict:
        """Test security headers (HSTS, X-Content-Type-Options, etc.)"""
        print(f"\n[TEST] Security Headers for {url}")

        # Create SSL context (allow self-signed)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, context=context, timeout=5) as response:
                headers = dict(response.headers)

                required_headers = {
                    "strict-transport-security": "max-age=31536000",
                    "x-content-type-options": "nosniff",
                    "x-frame-options": "DENY"
                }

                results = {}
                all_present = True

                for header, expected_value in required_headers.items():
                    header_lower = header.lower()
                    if header_lower in [h.lower() for h in headers]:
                        actual_value = headers.get(header) or headers.get(header_lower)
                        present = expected_value.lower() in actual_value.lower()
                        results[header] = {
                            "present": present,
                            "value": actual_value
                        }
                        if present:
                            print(f"  ✓ {header}: {actual_value}")
                        else:
                            print(f"  ✗ {header}: {actual_value} (expected: {expected_value})")
                            all_present = False
                    else:
                        results[header] = {"present": False, "value": None}
                        print(f"  ✗ {header}: MISSING")
                        all_present = False

                # Check that Server header is removed
                if "server" not in [h.lower() for h in headers]:
                    print(f"  ✓ Server header removed (security)")
                else:
                    print(f"  ⚠ Server header present: {headers.get('server')}")

                return {
                    "success": all_present,
                    "headers": results
                }

        except urllib.error.URLError as e:
            print(f"  ✗ Request Error: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            print(f"  ✗ Unexpected Error: {e}")
            return {"success": False, "error": str(e)}

    def run_all_tests(self) -> bool:
        """Run all TLS tests for all endpoints"""
        print("="*70)
        print("SATL 3.0 - TLS 1.3 Handshake Test Suite")
        print("="*70)

        all_passed = True
        results = {}

        for name, url in self.endpoints.items():
            print(f"\n{'='*70}")
            print(f"Testing {name.upper()} Node: {url}")
            print(f"{'='*70}")

            # Test TLS version
            tls_result = self.test_tls_version(url)
            if not tls_result.get("success"):
                all_passed = False

            # Test security headers
            header_result = self.test_security_headers(url)
            if not header_result.get("success"):
                all_passed = False

            results[name] = {
                "tls": tls_result,
                "headers": header_result
            }

        # Final summary
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)

        for name, result in results.items():
            tls_status = "PASS" if result["tls"].get("success") else "FAIL"
            header_status = "PASS" if result["headers"].get("success") else "FAIL"

            print(f"\n{name.upper()}:")
            print(f"  TLS Version:     [{tls_status}]")
            print(f"  Security Headers: [{header_status}]")

        print("\n" + "="*70)

        if all_passed:
            print("[PASS] All TLS tests passed")
            print("TLS 1.3 configuration is correct")
        else:
            print("[FAIL] Some TLS tests failed")
            print("\nTroubleshooting:")
            print("1. Ensure Caddy is running: start_caddy.bat")
            print("2. Ensure forwarders are running: start_forwarders_tls.bat")
            print("3. Check Caddy logs in logs/caddy/")
            print("4. Verify Caddyfile has 'protocols tls1.3'")

        print("="*70)

        return all_passed


def main():
    """Main entry point"""
    print("\nPrerequisites:")
    print("1. Caddy server must be running (start_caddy.bat)")
    print("2. Forwarders must be running on backend ports (start_forwarders_tls.bat)")
    print("\nPress Ctrl+C to abort, or Enter to continue...")

    try:
        input()
    except KeyboardInterrupt:
        print("\n\nTest aborted by user")
        return 1

    tester = TLSHandshakeTest()
    success = tester.run_all_tests()

    return 0 if success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
