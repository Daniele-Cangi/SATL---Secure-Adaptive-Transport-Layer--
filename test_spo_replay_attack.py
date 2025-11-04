"""
SPO REPLAY ATTACK TEST - Production-grade validation

Test Scenario:
1. Create valid rotation pack (rotation_id, channel_id, validity window)
2. Apply pack to CP config → SHOULD SUCCEED
3. Wait 30 seconds
4. Apply SAME pack again → SHOULD FAIL (replay detected)

Success Criteria:
- First application: PASS
- Second application: FAIL (replay detected)
- Anti-replay detection: 100%

Author: SATL 3.0 Security Research Team
Date: 2025-11-02
"""
import time
import sys
from spo_rotation_pack import RotationPack, RotationPackManager


class MockConfig:
    """Mock configuration for testing"""
    class Cover:
        def __init__(self):
            self.idle_ratio = 0.50

    def __init__(self):
        self.cover = self.Cover()


class SPOReplayAttackTest:
    """Test REAL replay attack scenario"""

    def __init__(self):
        self.results = []

    def test_replay_attack_same_pack_twice(self) -> bool:
        """
        Test 1: Apply same pack twice (30s apart)
        Expected: First succeeds, second fails (replay detected)
        """
        print("\n" + "="*70)
        print("TEST 1: REPLAY ATTACK - SAME PACK TWICE (30s APART)")
        print("="*70)

        # Create rotation pack with 5-minute validity window
        parameters = {"cover.idle_ratio": 0.65}
        channel_id = "test_channel_1"

        print(f"\n[SETUP] Creating rotation pack")
        print(f"  Channel ID: {channel_id}")
        print(f"  Parameters: {parameters}")
        print(f"  Validity: 300s (5 minutes)")

        pack = RotationPack.create(
            parameters=parameters,
            channel_id=channel_id,
            validity_window_seconds=300.0
        )

        print(f"\n[INFO] Pack created:")
        print(f"  Rotation ID: {pack.rotation_id}")
        print(f"  Issued at: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(pack.issued_at))}")
        print(f"  Valid until: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(pack.valid_until))}")

        # Verify signature is valid
        if not pack.verify():
            print(f"\n[FAIL] Pack signature invalid")
            return False

        print(f"[OK] Pack signature valid")

        # Create mock config
        config = MockConfig()
        original_value = config.cover.idle_ratio
        print(f"\n[INFO] Original config value: cover.idle_ratio = {original_value}")

        # FIRST APPLICATION
        print("\n" + "-"*70)
        print("FIRST APPLICATION (should SUCCEED)")
        print("-"*70)

        success1 = pack.apply(config, max_age_hours=24.0)

        if not success1:
            print(f"\n[FAIL] First application failed (should have succeeded)")
            return False

        if config.cover.idle_ratio != 0.65:
            print(f"\n[FAIL] First application didn't update config")
            print(f"  Expected: 0.65")
            print(f"  Got: {config.cover.idle_ratio}")
            return False

        print(f"\n[PASS] First application succeeded")
        print(f"  Config updated: cover.idle_ratio = {config.cover.idle_ratio}")

        # Wait 30 seconds (simulating replay attack delay)
        print("\n" + "-"*70)
        print("WAITING 30 SECONDS (simulating replay attack delay)")
        print("-"*70)

        for i in range(30, 0, -5):
            print(f"  {i}s remaining...")
            time.sleep(5)

        print(f"  [OK] Wait complete")

        # SECOND APPLICATION (REPLAY ATTACK)
        print("\n" + "-"*70)
        print("SECOND APPLICATION (REPLAY ATTACK - should FAIL)")
        print("-"*70)

        # Reset config to original value to test if pack gets applied
        config.cover.idle_ratio = original_value
        print(f"\n[TEST] Reset config to original: {config.cover.idle_ratio}")
        print(f"[ATTACK] Applying same pack again...")

        success2 = pack.apply(config, max_age_hours=24.0)

        if success2:
            print(f"\n[FAIL] Second application succeeded (SECURITY BREACH!)")
            print(f"  Replay attack was NOT detected")
            print(f"  Config was modified: cover.idle_ratio = {config.cover.idle_ratio}")
            return False

        if config.cover.idle_ratio != original_value:
            print(f"\n[FAIL] Config was modified even though apply() returned False")
            print(f"  Expected: {original_value}")
            print(f"  Got: {config.cover.idle_ratio}")
            return False

        print(f"\n[PASS] Second application failed (replay detected)")
        print(f"  Config unchanged: cover.idle_ratio = {config.cover.idle_ratio}")
        print(f"  Anti-replay protection: WORKING")

        return True

    def test_replay_attack_different_channels(self) -> bool:
        """
        Test 2: Same rotation_id on different channels
        Expected: Both succeed (different channels = independent windows)
        """
        print("\n" + "="*70)
        print("TEST 2: SAME ROTATION_ID ON DIFFERENT CHANNELS")
        print("="*70)

        # Create pack for channel A
        parameters_a = {"cover.idle_ratio": 0.60}
        channel_a = "channel_a"

        pack_a = RotationPack.create(
            parameters=parameters_a,
            channel_id=channel_a,
            validity_window_seconds=300.0
        )

        print(f"\n[SETUP] Pack A:")
        print(f"  Rotation ID: {pack_a.rotation_id}")
        print(f"  Channel: {channel_a}")

        # Create pack for channel B (SAME rotation_id, different channel)
        # Note: In production, rotation_id should be globally unique,
        # but this tests channel isolation
        pack_b = RotationPack.create(
            parameters={"cover.idle_ratio": 0.70},
            channel_id="channel_b",
            validity_window_seconds=300.0
        )

        # Manually set same rotation_id for test
        pack_b.rotation_id = pack_a.rotation_id

        print(f"\n[SETUP] Pack B (same rotation_id):")
        print(f"  Rotation ID: {pack_b.rotation_id}")
        print(f"  Channel: channel_b")

        # Apply pack A
        config_a = MockConfig()
        success_a = pack_a.apply(config_a)

        if not success_a:
            print(f"\n[FAIL] Pack A application failed")
            return False

        print(f"\n[OK] Pack A applied successfully")

        # Apply pack B (same rotation_id, different channel)
        config_b = MockConfig()
        success_b = pack_b.apply(config_b)

        if not success_b:
            print(f"\n[FAIL] Pack B application failed")
            print(f"  Channel isolation may be broken")
            return False

        print(f"\n[PASS] Pack B applied successfully")
        print(f"  Channels are properly isolated")

        return True

    def test_expired_pack_rejection(self) -> bool:
        """
        Test 3: Apply pack after validity window expires
        Expected: Rejected (expired)
        """
        print("\n" + "="*70)
        print("TEST 3: EXPIRED PACK REJECTION")
        print("="*70)

        # Create pack with SHORT validity window (5 seconds)
        parameters = {"cover.idle_ratio": 0.80}
        channel_id = "test_channel_3"

        print(f"\n[SETUP] Creating pack with 5-second validity window")

        pack = RotationPack.create(
            parameters=parameters,
            channel_id=channel_id,
            validity_window_seconds=5.0  # Short window for testing
        )

        print(f"  Rotation ID: {pack.rotation_id}")
        print(f"  Valid until: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(pack.valid_until))}")

        # Wait for pack to expire
        print(f"\n[WAIT] Waiting 10 seconds for pack to expire...")
        time.sleep(10)

        # Try to apply expired pack
        print(f"\n[TEST] Applying expired pack...")
        config = MockConfig()
        original_value = config.cover.idle_ratio

        success = pack.apply(config)

        if success:
            print(f"\n[FAIL] Expired pack was accepted (SECURITY BREACH!)")
            return False

        if config.cover.idle_ratio != original_value:
            print(f"\n[FAIL] Config was modified by expired pack")
            return False

        print(f"\n[PASS] Expired pack rejected")
        print(f"  Config unchanged: cover.idle_ratio = {config.cover.idle_ratio}")

        return True

    def run_all_tests(self):
        """Execute all replay attack tests"""
        print("="*70)
        print("SATL 3.0 - SPO REPLAY ATTACK TEST SUITE")
        print("="*70)
        print("\nProduction-grade validation of anti-replay protection")
        print("Testing: Replay detection, channel isolation, expiry")
        print("="*70)

        tests = [
            ("Replay Attack - Same Pack Twice (30s)", self.test_replay_attack_same_pack_twice),
            ("Channel Isolation - Same rotation_id", self.test_replay_attack_different_channels),
            ("Expired Pack Rejection", self.test_expired_pack_rejection),
        ]

        results = {}

        for test_name, test_func in tests:
            try:
                passed = test_func()
                results[test_name] = passed
            except Exception as e:
                print(f"\n[ERROR] Test failed with exception: {e}")
                import traceback
                traceback.print_exc()
                results[test_name] = False

        # Summary
        print("\n\n" + "="*70)
        print("REPLAY ATTACK TEST SUMMARY")
        print("="*70)

        for test_name, passed in results.items():
            status = "[PASS]" if passed else "[FAIL]"
            print(f"  {status} {test_name}")

        all_passed = all(results.values())
        pass_count = sum(results.values())
        total_count = len(results)

        print("\n" + "="*70)
        print(f"Results: {pass_count}/{total_count} tests passed")

        if all_passed:
            print("FINAL VERDICT: [PASS] All replay attack tests passed")
            print("SPO anti-replay protection is PRODUCTION-READY")
        else:
            print("FINAL VERDICT: [FAIL] Some replay attack tests failed")
            print("SECURITY ISSUES DETECTED - DO NOT DEPLOY")

        print("="*70)

        return all_passed


def main():
    """Main entry point"""
    print("\n" + "="*70)
    print("IMPORTANT: This test takes ~50 seconds to complete")
    print("  - Test 1: 30s wait (replay simulation)")
    print("  - Test 2: Immediate")
    print("  - Test 3: 10s wait (expiry)")
    print("="*70)

    input("\nPress ENTER to start test...")

    tester = SPOReplayAttackTest()

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
