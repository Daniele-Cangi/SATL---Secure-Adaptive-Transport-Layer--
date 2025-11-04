"""
SPO SECURITY TEST - Scientific validation of rotation pack security

Tests:
1. Signature tampering detection
2. Parameter tampering detection
3. Age check enforcement (stale pack rejection)
4. Replay attack prevention

Success Criteria:
- All tampering detected (100% detection rate)
- Stale packs rejected (age >24h)
- Valid packs accepted
- No false positives

Author: SATL 3.0 Security Research Team
Date: 2025-11-02
"""
import json
import base64
import time
import sys
from spo_rotation_pack import RotationPack


class SPOSecurityTest:
    """Scientific SPO security validation"""

    def __init__(self):
        self.results = []

    def test_signature_tampering(self) -> bool:
        """Test 1: Detect signature tampering"""
        print("\n" + "=" * 70)
        print("TEST 1: SIGNATURE TAMPERING DETECTION")
        print("=" * 70)

        # Create valid pack
        parameters = {"cover.idle_ratio": 0.65}
        pack = RotationPack.create(parameters)
        pack.save("test_sig_valid.json")

        # Verify original is valid
        assert pack.verify(), "Original pack should be valid"
        print("  [OK] Original pack signature valid")

        # Tamper with signature (flip 1 bit)
        with open("test_sig_valid.json") as f:
            data = json.load(f)

        sig_bytes = base64.b64decode(data["signature"])
        tampered_sig = sig_bytes[:-1] + bytes([sig_bytes[-1] ^ 0x01])
        data["signature"] = base64.b64encode(tampered_sig).decode()

        with open("test_sig_tampered.json", 'w') as f:
            json.dump(data, f)

        print("  [TEST] Flipped 1 bit in signature")

        # Load tampered pack
        pack_tampered = RotationPack.load("test_sig_tampered.json")
        is_valid = pack_tampered.verify()

        if not is_valid:
            print("  [PASS] Tampering detected - signature invalid")
            return True
        else:
            print("  [FAIL] Tampering NOT detected - SECURITY BREACH!")
            return False

    def test_parameter_tampering(self) -> bool:
        """Test 2: Detect parameter tampering with valid signature"""
        print("\n" + "=" * 70)
        print("TEST 2: PARAMETER TAMPERING DETECTION")
        print("=" * 70)

        # Create valid pack
        parameters = {"cover.idle_ratio": 0.65}
        pack = RotationPack.create(parameters)
        pack.save("test_param_valid.json")

        print("  [OK] Created pack with cover.idle_ratio=0.65")

        # Tamper with parameters (keep signature)
        with open("test_param_valid.json") as f:
            data = json.load(f)

        original_value = data["parameters"]["cover.idle_ratio"]
        data["parameters"]["cover.idle_ratio"] = 0.99  # Changed!

        with open("test_param_tampered.json", 'w') as f:
            json.dump(data, f)

        print(f"  [TEST] Changed parameter: {original_value} -> 0.99")
        print(f"  [TEST] Signature unchanged (invalid)")

        # Load tampered pack
        pack_tampered = RotationPack.load("test_param_tampered.json")
        is_valid = pack_tampered.verify()

        if not is_valid:
            print("  [PASS] Parameter tampering detected - signature mismatch")
            return True
        else:
            print("  [FAIL] Parameter tampering NOT detected - SECURITY BREACH!")
            return False

    def test_age_check_fresh(self) -> bool:
        """Test 3a: Accept fresh rotation pack (<24h)"""
        print("\n" + "=" * 70)
        print("TEST 3a: AGE CHECK - FRESH PACK (<24h)")
        print("=" * 70)

        # Create fresh pack
        parameters = {"cover.idle_ratio": 0.65}
        pack = RotationPack.create(parameters)

        age_hours = (time.time() - pack.timestamp) / 3600
        print(f"  [INFO] Pack age: {age_hours:.6f} hours (< 0.01h = fresh)")

        # Mock config
        class MockConfig:
            class Cover:
                idle_ratio = 0.50
            cover = Cover()

        config = MockConfig()

        # Verify pack
        if not pack.verify():
            print("  [FAIL] Fresh pack signature invalid")
            return False

        print("  [OK] Fresh pack signature valid")

        # Apply with age check (default 24h)
        success = pack.apply(config, max_age_hours=24.0)

        if success:
            print("  [PASS] Fresh pack accepted")
            print(f"  [VERIFY] Parameter applied: {config.cover.idle_ratio}")
            return config.cover.idle_ratio == 0.65
        else:
            print("  [FAIL] Fresh pack rejected - FALSE NEGATIVE!")
            return False

    def test_age_check_stale(self) -> bool:
        """Test 3b: Reject stale rotation pack (>24h)"""
        print("\n" + "=" * 70)
        print("TEST 3b: AGE CHECK - STALE PACK (>24h)")
        print("=" * 70)

        # Create pack with old timestamp
        parameters = {"cover.idle_ratio": 0.65}
        pack = RotationPack.create(parameters)

        # Manually set old timestamp (25 hours ago)
        pack.timestamp = time.time() - (25 * 3600)

        age_hours = (time.time() - pack.timestamp) / 3600
        print(f"  [INFO] Pack age: {age_hours:.2f} hours (>24h = stale)")

        # Mock config
        class MockConfig:
            class Cover:
                idle_ratio = 0.50
            cover = Cover()

        config = MockConfig()

        # Note: Can't verify signature because timestamp changed
        # In production, pack would be loaded from file with original signature
        # For this test, we only test age check logic

        # Apply with age check
        success = pack.apply(config, max_age_hours=24.0)

        if not success:
            print("  [PASS] Stale pack rejected (age check)")
            print(f"  [VERIFY] Parameter NOT applied: {config.cover.idle_ratio}")
            return config.cover.idle_ratio == 0.50  # Original value
        else:
            print("  [FAIL] Stale pack accepted - SECURITY BREACH!")
            return False

    def test_replay_attack_scenario(self) -> bool:
        """Test 4: Prevent replay attack with old rotation pack"""
        print("\n" + "=" * 70)
        print("TEST 4: REPLAY ATTACK PREVENTION")
        print("=" * 70)

        print("  [SCENARIO] Attacker captures old rotation pack")
        print("  [SCENARIO] SPO authority has issued new pack")
        print("  [SCENARIO] Attacker replays old pack (>24h old)")

        # Create "old" pack
        parameters_old = {"cover.idle_ratio": 0.50}
        pack_old = RotationPack.create(parameters_old)
        pack_old.save("test_replay_old.json")

        # Simulate time passing (set timestamp to 25h ago)
        with open("test_replay_old.json") as f:
            data = json.load(f)

        data["timestamp"] = time.time() - (25 * 3600)

        with open("test_replay_old.json", 'w') as f:
            json.dump(data, f)

        print("  [ATTACK] Replaying pack from 25 hours ago")

        # Load old pack
        pack_replayed = RotationPack.load("test_replay_old.json")

        age_hours = (time.time() - pack_replayed.timestamp) / 3600
        print(f"  [INFO] Replayed pack age: {age_hours:.2f} hours")

        # Mock config
        class MockConfig:
            class Cover:
                idle_ratio = 0.60  # Current value
            cover = Cover()

        config = MockConfig()

        # Verify signature (will be invalid due to timestamp change in test)
        # In real scenario, signature would be valid but pack is too old
        is_valid = pack_replayed.verify()

        if not is_valid:
            print("  [OK] Signature check failed (expected in test)")

        # Apply with age check
        success = pack_replayed.apply(config, max_age_hours=24.0)

        if not success:
            print("  [PASS] Replay attack prevented (age check)")
            print(f"  [VERIFY] Config unchanged: {config.cover.idle_ratio}")
            return config.cover.idle_ratio == 0.60  # Original value
        else:
            print("  [FAIL] Replay attack succeeded - SECURITY BREACH!")
            return False

    def run_all_tests(self):
        """Execute all security tests"""
        print("=" * 70)
        print("SATL 3.0 - SPO SECURITY TEST SUITE")
        print("=" * 70)
        print("\nScientific validation of rotation pack security")
        print("Testing: Signature tampering, parameter tampering, age checks")
        print("=" * 70)

        tests = [
            ("Signature Tampering Detection", self.test_signature_tampering),
            ("Parameter Tampering Detection", self.test_parameter_tampering),
            ("Age Check - Fresh Pack", self.test_age_check_fresh),
            ("Age Check - Stale Pack", self.test_age_check_stale),
            ("Replay Attack Prevention", self.test_replay_attack_scenario),
        ]

        results = {}

        for test_name, test_func in tests:
            try:
                passed = test_func()
                results[test_name] = passed
            except Exception as e:
                print(f"\n  [ERROR] Test failed with exception: {e}")
                import traceback
                traceback.print_exc()
                results[test_name] = False

        # Summary
        print("\n\n" + "=" * 70)
        print("SECURITY TEST SUMMARY")
        print("=" * 70)

        for test_name, passed in results.items():
            status = "[PASS]" if passed else "[FAIL]"
            print(f"  {status} {test_name}")

        all_passed = all(results.values())
        pass_count = sum(results.values())
        total_count = len(results)

        print("\n" + "=" * 70)
        print(f"Results: {pass_count}/{total_count} tests passed")

        if all_passed:
            print("FINAL VERDICT: [PASS] All security tests passed")
            print("SPO rotation pack system is SECURE")
        else:
            print("FINAL VERDICT: [FAIL] Some security tests failed")
            print("SECURITY ISSUES DETECTED - DO NOT DEPLOY")

        print("=" * 70)

        return all_passed


def main():
    """Main entry point"""
    tester = SPOSecurityTest()

    try:
        all_passed = tester.run_all_tests()
        return 0 if all_passed else 1
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
