"""
SATL 3.0 - SPO Window Persistence Tests

Tests SQLite-backed anti-replay window:
- Replay detection across restarts
- Garbage collection of expired entries
- Atomic operations (no race conditions)
- Per-channel isolation

Author: SATL 3.0 Research Team
Date: 2025-11-04
"""
import pytest
import os
import time
import tempfile
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from spo_window_store import RotationWindowStore


@pytest.fixture
def temp_db(tmp_path):
    """Create temporary database for testing"""
    db_path = tmp_path / "test_window.db"
    return str(db_path)


def test_persist_and_reject(temp_db):
    """
    Test 1: Replay detection persists across restart

    Expected: Rotation ID added before restart is still detected after restart
    """
    # Session 1: Add rotation ID
    store1 = RotationWindowStore(temp_db)

    now = time.time()
    channel_id = "test_channel"
    rotation_id = "rot_abc123"

    # Add entry
    assert store1.add(channel_id, rotation_id, now, now + 300) is True
    assert store1.exists(channel_id, rotation_id) is True

    store1.close()

    # Session 2: Simulate restart
    store2 = RotationWindowStore(temp_db)

    # Entry should still exist after restart
    assert store2.exists(channel_id, rotation_id) is True

    # Try to add same rotation_id again (replay)
    assert store2.add(channel_id, rotation_id, now, now + 300) is False

    store2.close()


def test_gc_expired(temp_db):
    """
    Test 2: Garbage collection removes expired entries

    Expected: Expired entries removed, live entries kept
    """
    store = RotationWindowStore(temp_db)

    now = time.time()
    channel_id = "test_channel"

    # Add expired entry (valid_until in the past)
    store.add(channel_id, "rot_old", now - 600, now - 300)

    # Add live entry (valid_until in the future)
    store.add(channel_id, "rot_live", now, now + 300)

    # Both should exist before GC
    assert store.exists(channel_id, "rot_old") is True
    assert store.exists(channel_id, "rot_live") is True

    # Run GC
    deleted_count = store.gc(now)

    # Only expired entry should be removed
    assert deleted_count == 1
    assert store.exists(channel_id, "rot_old") is False
    assert store.exists(channel_id, "rot_live") is True

    store.close()


def test_per_channel_isolation(temp_db):
    """
    Test 3: Per-channel window isolation

    Expected: Same rotation_id can exist in different channels
    """
    store = RotationWindowStore(temp_db)

    now = time.time()
    rotation_id = "rot_shared"

    # Add to channel1
    assert store.add("channel1", rotation_id, now, now + 300) is True

    # Add same rotation_id to channel2 (should succeed - different channel)
    assert store.add("channel2", rotation_id, now, now + 300) is True

    # Both should exist
    assert store.exists("channel1", rotation_id) is True
    assert store.exists("channel2", rotation_id) is True

    # Try to add to channel1 again (should fail - replay in same channel)
    assert store.add("channel1", rotation_id, now, now + 300) is False

    store.close()


def test_atomic_add(temp_db):
    """
    Test 4: Atomic add operation (no duplicates even with races)

    Expected: Primary key constraint prevents duplicates
    """
    store = RotationWindowStore(temp_db)

    now = time.time()
    channel_id = "test_channel"
    rotation_id = "rot_atomic"

    # First add should succeed
    assert store.add(channel_id, rotation_id, now, now + 300) is True

    # Second add should fail (IntegrityError caught)
    assert store.add(channel_id, rotation_id, now, now + 300) is False

    # Should only have one entry
    assert store.count(channel_id) == 1

    store.close()


def test_count_and_channels(temp_db):
    """
    Test 5: Count and channel enumeration

    Expected: Correct counts and channel lists
    """
    store = RotationWindowStore(temp_db)

    now = time.time()

    # Add entries to multiple channels
    store.add("channel1", "rot1", now, now + 300)
    store.add("channel1", "rot2", now, now + 300)
    store.add("channel2", "rot3", now, now + 300)

    # Check counts
    assert store.count() == 3
    assert store.count("channel1") == 2
    assert store.count("channel2") == 1
    assert store.count("channel_nonexistent") == 0

    # Check channels list
    channels = store.get_channels()
    assert len(channels) == 2
    assert "channel1" in channels
    assert "channel2" in channels

    store.close()


def test_gc_multi_channel(temp_db):
    """
    Test 6: GC works across multiple channels

    Expected: Expired entries removed from all channels
    """
    store = RotationWindowStore(temp_db)

    now = time.time()

    # Add expired entries to multiple channels
    store.add("channel1", "old1", now - 600, now - 300)
    store.add("channel1", "old2", now - 600, now - 300)
    store.add("channel2", "old3", now - 600, now - 300)

    # Add live entries
    store.add("channel1", "live1", now, now + 300)
    store.add("channel2", "live2", now, now + 300)

    assert store.count() == 5

    # Run GC
    deleted_count = store.gc(now)

    assert deleted_count == 3
    assert store.count() == 2

    # Live entries should remain
    assert store.exists("channel1", "live1") is True
    assert store.exists("channel2", "live2") is True

    # Expired entries should be gone
    assert store.exists("channel1", "old1") is False
    assert store.exists("channel2", "old3") is False

    store.close()


def test_empty_gc(temp_db):
    """
    Test 7: GC with no expired entries

    Expected: No entries removed, no errors
    """
    store = RotationWindowStore(temp_db)

    now = time.time()

    # Add only live entries
    store.add("channel1", "live1", now, now + 300)
    store.add("channel1", "live2", now, now + 300)

    # Run GC
    deleted_count = store.gc(now)

    # Nothing should be removed
    assert deleted_count == 0
    assert store.count() == 2

    store.close()


def test_concurrent_access(temp_db):
    """
    Test 8: Multiple store instances can access same DB (WAL mode)

    Expected: No corruption, both instances see same data
    """
    # Store 1: Add entry
    store1 = RotationWindowStore(temp_db)

    now = time.time()
    store1.add("channel1", "rot1", now, now + 300)

    # Store 2: Access same DB without closing store1
    store2 = RotationWindowStore(temp_db)

    # Both should see the entry
    assert store1.exists("channel1", "rot1") is True
    assert store2.exists("channel1", "rot1") is True

    # Store 2 adds another entry
    store2.add("channel1", "rot2", now, now + 300)

    # Both should see both entries
    assert store1.count("channel1") == 2
    assert store2.count("channel1") == 2

    store1.close()
    store2.close()


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
