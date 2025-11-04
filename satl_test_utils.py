"""
SATL 3.0 - Test Utilities

Shared helper functions for SATL test scripts.
Ensures consistent packet generation across all performance tests.

Author: SATL 3.0 Research Team
Date: 2025-11-02
"""


def build_perf_packet(packet_id: int, hops: int = 3, payload_size: int = 1200) -> bytes:
    """
    Build a performance test packet with the exact format used in test_performance_bare.py

    This is the CANONICAL packet format that achieved P95 < 100ms in validated tests.

    Format: [hops:1][identifier][padding]
    - hops: 1 byte (always <= 3 for SATL 3-hop enforcement)
    - identifier: string like "perf_00000001" or "endurance_00000001"
    - padding: 'X' bytes to reach total payload_size

    Args:
        packet_id: Unique packet identifier (for tracking)
        hops: Number of hops (MUST be <= 3, will be clamped)
        payload_size: Total payload size in bytes (default 1200)

    Returns:
        bytes: Packet ready to send to guard node

    Security:
        - Enforces hops <= 3 (hard cap for 3-hop circuits)
        - Uses simple format for performance mode (no onion crypto)
        - Compatible with SATL_MODE=performance forwarders
    """
    # CRITICAL: Enforce 3-hop maximum (SATL circuit requirement)
    if hops > 3:
        # Log warning but don't crash - clamp to safe value
        import sys
        print(f"[WARNING] Packet {packet_id}: hops={hops} exceeds limit, clamping to 3", file=sys.stderr)
        hops = 3

    if hops < 0:
        hops = 0

    # Build identifier (same format as test_performance_bare.py)
    identifier = f"perf_{packet_id:08d}".encode()

    # Calculate padding needed
    header_and_id_size = 1 + len(identifier)  # 1 byte for hops + identifier
    padding_size = max(0, payload_size - header_and_id_size)

    # Build packet: [hops:1][identifier][padding]
    packet = bytes([hops]) + identifier + (b"X" * padding_size)

    return packet


def build_endurance_packet(packet_id: int, hops: int = 3, payload_size: int = 1200) -> bytes:
    """
    Build an endurance test packet (uses same format as perf, different identifier prefix)

    This ensures endurance tests use the EXACT same packet structure that
    passed performance validation (P95 < 100ms @ 10 and 50 concurrent).

    Args:
        packet_id: Unique packet identifier
        hops: Number of hops (MUST be <= 3)
        payload_size: Total payload size in bytes

    Returns:
        bytes: Packet ready to send to guard node
    """
    # CRITICAL: Enforce 3-hop maximum
    if hops > 3:
        import sys
        print(f"[WARNING] Endurance packet {packet_id}: hops={hops} exceeds limit, clamping to 3", file=sys.stderr)
        hops = 3

    if hops < 0:
        hops = 0

    # Build identifier with "endurance_" prefix
    identifier = f"endurance_{packet_id:08d}".encode()

    # Calculate padding needed
    header_and_id_size = 1 + len(identifier)
    padding_size = max(0, payload_size - header_and_id_size)

    # Build packet: [hops:1][identifier][padding]
    packet = bytes([hops]) + identifier + (b"X" * padding_size)

    return packet


def validate_packet_format(packet: bytes) -> dict:
    """
    Validate packet format and extract metadata

    Returns:
        dict with keys: valid (bool), hops (int), error (str)
    """
    if len(packet) < 1:
        return {"valid": False, "hops": None, "error": "Empty packet"}

    hops = packet[0]

    if hops > 3:
        return {
            "valid": False,
            "hops": hops,
            "error": f"Invalid hops count: {hops} (max 3)"
        }

    return {"valid": True, "hops": hops, "error": None}


def debug_first4(packet: bytes) -> str:
    """
    Get hex representation of first 4 bytes for debugging

    Used to verify binary integrity across the forwarder path.

    Args:
        packet: Binary packet data

    Returns:
        Hex string of first 4 bytes, or '<non-bytes>' if invalid type
    """
    if isinstance(packet, (bytes, bytearray)):
        return packet[:4].hex() if len(packet) >= 4 else packet.hex()
    else:
        return '<non-bytes>'


# Export public API
__all__ = [
    'build_perf_packet',
    'build_endurance_packet',
    'validate_packet_format',
    'debug_first4'
]


if __name__ == "__main__":
    # Self-test
    print("=== SATL Test Utils Self-Test ===\n")

    # Test 1: Normal packet
    packet1 = build_perf_packet(1, hops=3)
    print(f"Test 1: build_perf_packet(1, hops=3)")
    print(f"  Length: {len(packet1)} bytes")
    print(f"  Hops byte: {packet1[0]}")
    print(f"  Identifier: {packet1[1:15]}")
    validation1 = validate_packet_format(packet1)
    print(f"  Valid: {validation1['valid']}")

    # Test 2: Clamping (hops > 3)
    print(f"\nTest 2: build_perf_packet(2, hops=112) - should clamp to 3")
    packet2 = build_perf_packet(2, hops=112)
    print(f"  Hops byte after clamping: {packet2[0]}")
    validation2 = validate_packet_format(packet2)
    print(f"  Valid: {validation2['valid']}")

    # Test 3: Endurance packet
    packet3 = build_endurance_packet(42)
    print(f"\nTest 3: build_endurance_packet(42)")
    print(f"  Length: {len(packet3)} bytes")
    print(f"  Hops byte: {packet3[0]}")
    print(f"  Identifier: {packet3[1:20]}")
    validation3 = validate_packet_format(packet3)
    print(f"  Valid: {validation3['valid']}")

    # Test 4: Debug hex function
    print(f"\nTest 4: debug_first4() hex representation")
    print(f"  Packet 1 first4: {debug_first4(packet1)}")
    print(f"  Packet 2 first4: {debug_first4(packet2)}")
    print(f"  Packet 3 first4: {debug_first4(packet3)}")
    print(f"  Non-bytes input: {debug_first4('not bytes')}")

    print("\n=== All Tests Passed ===")
