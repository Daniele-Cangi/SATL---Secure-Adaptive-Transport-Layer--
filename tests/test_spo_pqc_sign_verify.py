"""
SATL 3.0 - PQC SPO Rotation Pack Tests

Tests PQC integration with fail-closed semantics:
- Sign/verify with Dilithium3Provider
- Tamper detection (payload, signature)
- Wrong key detection
- Backend unavailable handling
- Environment variable gating

Environment:
    SATL_PQC=1              # Enable PQC mode
    SATL_PQC_KEYS_DIR=...   # Path to keys directory

Author: SATL 3.0 Research Team
Date: 2025-11-03
"""
import pytest
import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from spo_rotation_pack import RotationPack, _PQCSigner, _get_pqc_signer
from pqc.dilithium3_provider import Dilithium3Provider


def _payload():
    """Standard test payload"""
    return b"SATL 3.0 test payload for PQC signature verification"


@pytest.fixture
def keys_dir(tmp_path):
    """
    Create temporary keys directory with test keys

    Uses mock mode to generate test keys without requiring liboqs
    """
    keys_path = tmp_path / "pqc_keys"
    keys_path.mkdir()

    # Generate mock keys for testing
    provider = Dilithium3Provider(mode="mock")
    pk, sk = provider.generate_keys()

    # Save keys
    with open(keys_path / "pk.bin", "wb") as f:
        f.write(pk)
    with open(keys_path / "sk.bin", "wb") as f:
        f.write(sk)

    return keys_path


@pytest.fixture
def set_pqc_env(keys_dir):
    """Set PQC environment variables for testing"""
    old_pqc = os.environ.get('SATL_PQC')
    old_keys_dir = os.environ.get('SATL_PQC_KEYS_DIR')

    os.environ['SATL_PQC'] = '1'
    os.environ['SATL_PQC_KEYS_DIR'] = str(keys_dir)

    # Reset global signer instance
    import spo_rotation_pack
    spo_rotation_pack._pqc_signer = None

    yield

    # Restore original environment
    if old_pqc is None:
        os.environ.pop('SATL_PQC', None)
    else:
        os.environ['SATL_PQC'] = old_pqc

    if old_keys_dir is None:
        os.environ.pop('SATL_PQC_KEYS_DIR', None)
    else:
        os.environ['SATL_PQC_KEYS_DIR'] = old_keys_dir

    # Reset global signer
    spo_rotation_pack._pqc_signer = None


# Test 1: Sign/verify OK
def test_pqc_sign_verify_ok(keys_dir, set_pqc_env):
    """
    Test 1: Sign and verify with PQC provider

    Expected: Signature valid
    """
    provider = Dilithium3Provider(mode="mock", keys_dir=str(keys_dir))

    payload = _payload()
    sig = provider.sign(payload)

    assert provider.verify(payload, sig) is True, "Signature verification should succeed"


# Test 2: Tampered payload detection
def test_pqc_verify_fails_on_tampered_payload(keys_dir, set_pqc_env):
    """
    Test 2: Verify fails when payload is tampered

    Expected: Signature invalid
    """
    provider = Dilithium3Provider(mode="mock", keys_dir=str(keys_dir))

    payload = _payload()
    sig = provider.sign(payload)

    # Tamper with payload
    tampered_payload = b'X' + payload[1:]

    assert provider.verify(tampered_payload, sig) is False, "Tampered payload should fail verification"


# Test 3: Tampered signature detection
def test_pqc_verify_fails_on_tampered_signature(keys_dir, set_pqc_env):
    """
    Test 3: Verify fails when signature is tampered

    Expected: Signature invalid
    """
    provider = Dilithium3Provider(mode="mock", keys_dir=str(keys_dir))

    payload = _payload()
    sig = provider.sign(payload)

    # Tamper with signature (flip one byte)
    tampered_sig = bytearray(sig)
    tampered_sig[0] ^= 0xFF
    tampered_sig = bytes(tampered_sig)

    assert provider.verify(payload, tampered_sig) is False, "Tampered signature should fail verification"


# Test 4: Wrong key detection
def test_pqc_verify_fails_with_wrong_key(keys_dir, set_pqc_env):
    """
    Test 4: Verify fails when using wrong public key

    Expected: Signature invalid
    """
    # Create first provider with original keys
    provider1 = Dilithium3Provider(mode="mock", keys_dir=str(keys_dir))

    payload = _payload()
    sig = provider1.sign(payload)

    # Generate different keys
    provider2 = Dilithium3Provider(mode="mock")
    pk2, sk2 = provider2.generate_keys()

    # Try to verify with wrong public key
    is_valid = provider2.verify(payload, sig, public_key=pk2)

    assert is_valid is False, "Verification with wrong key should fail"


# Test 5: SPO rotation pack integration
def test_spo_rotation_pack_with_pqc(keys_dir, set_pqc_env):
    """
    Test 5: SPO rotation pack create and verify with PQC

    Expected: Pack creates successfully and verifies
    """
    parameters = {
        "cover.idle_ratio": 0.60,
        "timing.deperiodize_max_shift_ms": 12
    }

    # Create rotation pack (uses PQC signer)
    pack = RotationPack.create(
        parameters=parameters,
        channel_id="test_channel",
        validity_window_seconds=300.0
    )

    # Verify rotation pack
    assert pack.verify() is True, "Rotation pack should verify successfully"

    # Verify structure
    assert pack.rotation_id is not None, "Rotation ID should be set"
    assert pack.channel_id == "test_channel", "Channel ID should match"
    assert pack.parameters == parameters, "Parameters should match"


# Test 6: Fail-closed when keys missing
def test_pqc_signer_fails_when_keys_missing(tmp_path):
    """
    Test 6: PQC signer fails when keys not found (fail-closed)

    Expected: RuntimeError raised
    """
    # Create empty keys directory
    empty_keys_dir = tmp_path / "empty_keys"
    empty_keys_dir.mkdir()

    old_pqc = os.environ.get('SATL_PQC')
    old_keys_dir = os.environ.get('SATL_PQC_KEYS_DIR')

    os.environ['SATL_PQC'] = '1'
    os.environ['SATL_PQC_KEYS_DIR'] = str(empty_keys_dir)

    # Reset global signer
    import spo_rotation_pack
    spo_rotation_pack._pqc_signer = None

    try:
        # Should fail because keys don't exist
        with pytest.raises(RuntimeError, match="Public key not found"):
            signer = _PQCSigner()

    finally:
        # Restore environment
        if old_pqc is None:
            os.environ.pop('SATL_PQC', None)
        else:
            os.environ['SATL_PQC'] = old_pqc

        if old_keys_dir is None:
            os.environ.pop('SATL_PQC_KEYS_DIR', None)
        else:
            os.environ['SATL_PQC_KEYS_DIR'] = old_keys_dir

        spo_rotation_pack._pqc_signer = None


# Test 7: Legacy mode compatibility (SATL_PQC=0)
def test_legacy_mode_compatibility():
    """
    Test 7: Legacy mode works when SATL_PQC=0 (default)

    Expected: Mock signatures work, no liboqs required
    """
    old_pqc = os.environ.get('SATL_PQC')

    # Explicitly disable PQC
    os.environ['SATL_PQC'] = '0'

    # Reset global signer
    import spo_rotation_pack
    spo_rotation_pack._pqc_signer = None

    try:
        signer = _PQCSigner()

        assert signer.enabled is False, "PQC should be disabled"

        # Legacy mock signature should work
        payload = _payload()
        sig = signer.sign(payload)

        assert signer.verify(payload, sig) is True, "Legacy mock signature should verify"

        # Check signature format
        assert sig.startswith(b'MOCK_DILITHIUM3_SIGNATURE_'), "Should use mock signature"

    finally:
        # Restore environment
        if old_pqc is None:
            os.environ.pop('SATL_PQC', None)
        else:
            os.environ['SATL_PQC'] = old_pqc

        spo_rotation_pack._pqc_signer = None


# Test 8: Provider is_available() method
def test_provider_is_available(keys_dir):
    """
    Test 8: Provider is_available() returns correct status

    Expected: Returns True in real mode with liboqs, False in mock mode
    """
    # Mock mode should report not available for real PQC
    provider_mock = Dilithium3Provider(mode="mock", keys_dir=str(keys_dir))
    assert provider_mock.is_available() is False, "Mock mode should not be available as real PQC"

    # Note: We can't test real mode without liboqs installed
    # That's tested in production deployment


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
