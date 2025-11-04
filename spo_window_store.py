"""
SATL 3.0 - SQLite-backed Anti-Replay Window Store

Replaces JSON file persistence with atomic, WAL-backed SQLite storage.

Features:
- Atomic transactions (no race conditions)
- WAL mode for concurrent access
- Automatic garbage collection of expired entries
- Per-channel window tracking
- Persistent across restarts

Schema:
    window(channel_id TEXT, rotation_id TEXT, issued_at INTEGER, valid_until INTEGER)
    PRIMARY KEY: (channel_id, rotation_id)
    INDEX: valid_until (for efficient GC)

Author: SATL 3.0 Research Team
Date: 2025-11-04
"""
import sqlite3
import time
import pathlib
import logging
from typing import Tuple, Optional

logger = logging.getLogger("SPO")


# SQLite performance pragmas (Task E3 optimizations)
PRAGMAS = [
    'PRAGMA journal_mode=WAL;',         # Write-Ahead Logging for concurrency
    'PRAGMA synchronous=NORMAL;',       # Balance safety/performance
    'PRAGMA temp_store=MEMORY;',        # Use RAM for temp tables
    'PRAGMA foreign_keys=ON;',          # Enforce foreign key constraints
    'PRAGMA busy_timeout=5000;',        # Wait up to 5s on lock contention
    'PRAGMA mmap_size=268435456;',      # 256MB memory-mapped I/O (Task E3)
    'PRAGMA cache_size=-20000;'         # 20MB page cache (Task E3)
]

# Database schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS window (
    channel_id TEXT NOT NULL,
    rotation_id TEXT NOT NULL,
    issued_at INTEGER NOT NULL,
    valid_until INTEGER NOT NULL,
    PRIMARY KEY (channel_id, rotation_id)
);

CREATE INDEX IF NOT EXISTS ix_window_expiry ON window(valid_until);
"""


class MemoryWindowStore:
    """
    In-memory anti-replay window store (for performance mode)

    Lightweight alternative to SQLite for high-throughput scenarios.
    No persistence across restarts - acceptable for performance testing.
    """

    def __init__(self, ttl_sec: int = 86400):
        """
        Initialize memory store

        Args:
            ttl_sec: Default TTL for entries (default: 24 hours)
        """
        self.ttl = ttl_sec
        self._m = {}  # (channel_id, rotation_id) -> valid_until
        self._last_gc = 0
        logger.info("[MEMORY] Window store initialized (in-memory backend)")

    def exists(self, channel_id: str, rotation_id: str) -> bool:
        """Check if rotation_id exists for given channel"""
        k = (channel_id, rotation_id)
        self._gc()
        return k in self._m

    def add(self, channel_id: str, rotation_id: str, issued_at: float, valid_until: float) -> bool:
        """Add rotation_id to window (atomic check-and-set)"""
        self._gc()
        k = (channel_id, rotation_id)

        if k in self._m:
            return False  # Replay detected

        self._m[k] = int(valid_until)
        return True

    def gc(self, now_ts: Optional[float] = None) -> int:
        """Garbage collect expired rotation IDs"""
        return self._gc(now_ts)

    def _gc(self, now_ts: Optional[float] = None) -> int:
        """Internal GC implementation"""
        now = int(now_ts or time.time())

        # Rate limit GC to every 30 seconds
        if now - self._last_gc < 30:
            return 0

        self._last_gc = now

        # Find expired entries
        expired = [k for k, v in self._m.items() if v < now]

        # Remove expired
        for k in expired:
            self._m.pop(k, None)

        if expired:
            logger.info(f"[MEMORY] GC removed {len(expired)} expired rotation IDs")

        return len(expired)

    def count(self, channel_id: Optional[str] = None) -> int:
        """Count rotation IDs in window"""
        if channel_id:
            return sum(1 for (ch, _) in self._m.keys() if ch == channel_id)
        return len(self._m)

    def get_channels(self) -> list:
        """Get list of all channels with active rotation IDs"""
        channels = sorted(set(ch for (ch, _) in self._m.keys()))
        return channels

    def close(self):
        """Close store (no-op for memory backend)"""
        logger.info("[MEMORY] Window store closed")


class RotationWindowStore:
    """
    SQLite-backed persistent storage for anti-replay windows

    Thread-safe with WAL mode enabled. Multiple processes can read concurrently.
    """

    def __init__(self, path: str = "spo_window.db"):
        """
        Initialize SQLite store with WAL mode and prepared statements (Task E3)

        Args:
            path: Database file path (default: spo_window.db)
        """
        self.path = pathlib.Path(path)

        # Create connection with check_same_thread=False for multi-threaded access
        self.conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None  # Autocommit mode, we'll use explicit transactions
        )

        # Apply performance pragmas
        for pragma in PRAGMAS:
            self.conn.execute(pragma)

        # Create schema
        self.conn.executescript(SCHEMA)

        # Prepared statements (Task E3 optimization)
        self._stmt_exists = self.conn.cursor()
        self._stmt_add = self.conn.cursor()

        logger.info(f"[SQLITE] Window store initialized: {self.path}")
        logger.info(f"[SQLITE] Journal mode: {self.conn.execute('PRAGMA journal_mode;').fetchone()[0]}")

    def exists(self, channel_id: str, rotation_id: str) -> bool:
        """
        Check if rotation_id exists for given channel (replay detection)
        Uses prepared statement for faster execution (Task E3)

        Args:
            channel_id: Channel identifier
            rotation_id: Rotation pack UUID

        Returns:
            True if rotation_id already seen for this channel, False otherwise
        """
        self._stmt_exists.execute(
            'SELECT 1 FROM window WHERE channel_id = ? AND rotation_id = ? LIMIT 1',
            (channel_id, rotation_id)
        )

        return self._stmt_exists.fetchone() is not None

    def add(self, channel_id: str, rotation_id: str, issued_at: float, valid_until: float) -> bool:
        """
        Add rotation_id to window (atomic operation)
        Uses prepared statement for faster execution (Task E3)

        Args:
            channel_id: Channel identifier
            rotation_id: Rotation pack UUID
            issued_at: Issue timestamp (Unix epoch)
            valid_until: Expiry timestamp (Unix epoch)

        Returns:
            True if added successfully, False if already exists (replay)
        """
        try:
            with self.conn:
                self._stmt_add.execute(
                    'INSERT INTO window (channel_id, rotation_id, issued_at, valid_until) VALUES (?, ?, ?, ?)',
                    (channel_id, rotation_id, int(issued_at), int(valid_until))
                )
            return True

        except sqlite3.IntegrityError:
            # Primary key violation - rotation_id already exists for this channel
            return False

    def gc(self, now_ts: Optional[float] = None, batch_size: int = 2000) -> int:
        """
        Garbage collect expired rotation IDs with batch deletion (Task E3)

        Uses LIMIT to avoid long-running transactions that could block writes.

        Args:
            now_ts: Current timestamp (default: time.time())
            batch_size: Maximum rows to delete per transaction (default: 2000)

        Returns:
            Number of expired entries removed
        """
        if now_ts is None:
            now_ts = time.time()

        now_int = int(now_ts)
        total_deleted = 0

        # Batch delete to avoid blocking writes for too long
        while True:
            cursor = self.conn.execute(
                'DELETE FROM window WHERE rowid IN (SELECT rowid FROM window WHERE valid_until < ? LIMIT ?)',
                (now_int, batch_size)
            )

            deleted_this_batch = cursor.rowcount
            self.conn.commit()

            total_deleted += deleted_this_batch

            if deleted_this_batch < batch_size:
                break  # No more expired entries

        if total_deleted > 0:
            logger.info(f"[SQLITE] GC removed {total_deleted} expired rotation IDs (batched)")

        return total_deleted

    def count(self, channel_id: Optional[str] = None) -> int:
        """
        Count rotation IDs in window

        Args:
            channel_id: Optional channel filter (None = all channels)

        Returns:
            Number of rotation IDs in window
        """
        if channel_id:
            cursor = self.conn.execute(
                'SELECT COUNT(*) FROM window WHERE channel_id = ?',
                (channel_id,)
            )
        else:
            cursor = self.conn.execute('SELECT COUNT(*) FROM window')

        return cursor.fetchone()[0]

    def get_channels(self) -> list:
        """
        Get list of all channels with active rotation IDs

        Returns:
            List of channel IDs
        """
        cursor = self.conn.execute('SELECT DISTINCT channel_id FROM window ORDER BY channel_id')
        return [row[0] for row in cursor.fetchall()]

    def close(self):
        """Close database connection"""
        self.conn.close()
        logger.info("[SQLITE] Window store closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Module-level singleton (lazy initialization)
_store_instance = None


def get_window_store(mode_env: Optional[str] = None):
    """
    Get or create global window store instance

    Backend selection logic:
    - SATL_WINDOW_BACKEND=memory -> MemoryWindowStore
    - SATL_WINDOW_BACKEND=sqlite -> RotationWindowStore (SQLite)
    - SATL_WINDOW_BACKEND=auto (default):
        - SATL_MODE=performance -> MemoryWindowStore
        - SATL_MODE=stealth/security/default -> RotationWindowStore (SQLite)

    Args:
        mode_env: Override SATL_MODE env (for testing)

    Returns:
        Window store instance (MemoryWindowStore or RotationWindowStore)
    """
    global _store_instance

    if _store_instance is None:
        import os

        mode = (mode_env or os.getenv('SATL_MODE', 'performance')).lower()
        backend = os.getenv('SATL_WINDOW_BACKEND', 'auto').lower()

        # Explicit backend selection
        if backend == 'memory':
            _store_instance = MemoryWindowStore()
            logger.info(f"[FACTORY] Window backend: MEMORY (explicit)")

        elif backend == 'sqlite':
            db_path = os.getenv('SATL_WINDOW_DB', 'spo_window.db')
            _store_instance = RotationWindowStore(db_path)
            logger.info(f"[FACTORY] Window backend: SQLITE (explicit)")

        # Auto-selection based on mode
        elif backend == 'auto':
            if mode == 'performance':
                _store_instance = MemoryWindowStore()
                logger.info(f"[FACTORY] Window backend: MEMORY (auto, mode={mode})")
            else:
                db_path = os.getenv('SATL_WINDOW_DB', 'spo_window.db')
                _store_instance = RotationWindowStore(db_path)
                logger.info(f"[FACTORY] Window backend: SQLITE (auto, mode={mode})")

        else:
            # Unknown backend, default to SQLite
            logger.warning(f"[FACTORY] Unknown backend '{backend}', defaulting to SQLITE")
            db_path = os.getenv('SATL_WINDOW_DB', 'spo_window.db')
            _store_instance = RotationWindowStore(db_path)

    return _store_instance


# Export public API
__all__ = ['MemoryWindowStore', 'RotationWindowStore', 'get_window_store']


if __name__ == "__main__":
    # Self-test
    import sys
    import tempfile
    import os

    print("=== RotationWindowStore Self-Test ===\n")

    # Create temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_window.db")

        print(f"[TEST 1] Initialize store: {db_path}")
        store = RotationWindowStore(db_path)
        print(f"  Journal mode: {store.conn.execute('PRAGMA journal_mode;').fetchone()[0]}")

        print("\n[TEST 2] Add rotation IDs")
        now = time.time()
        assert store.add("channel1", "rot1", now, now + 300) is True
        assert store.add("channel1", "rot2", now, now + 300) is True
        assert store.add("channel2", "rot3", now, now + 300) is True
        print(f"  Added 3 rotation IDs")

        print("\n[TEST 3] Check exists (replay detection)")
        assert store.exists("channel1", "rot1") is True
        assert store.exists("channel1", "rot999") is False
        print(f"  Replay detection works")

        print("\n[TEST 4] Reject duplicate (replay)")
        assert store.add("channel1", "rot1", now, now + 300) is False
        print(f"  Duplicate rejected")

        print("\n[TEST 5] Count entries")
        assert store.count() == 3
        assert store.count("channel1") == 2
        assert store.count("channel2") == 1
        print(f"  Count: total={store.count()}, channel1={store.count('channel1')}")

        print("\n[TEST 6] Get channels")
        channels = store.get_channels()
        assert channels == ["channel1", "channel2"]
        print(f"  Channels: {channels}")

        print("\n[TEST 7] Garbage collection")
        # Add expired entry
        store.add("channel1", "expired", now - 600, now - 300)
        assert store.count() == 4

        # GC should remove expired entry
        deleted = store.gc(now)
        assert deleted == 1
        assert store.count() == 3
        assert store.exists("channel1", "expired") is False
        print(f"  GC removed {deleted} expired entries")

        print("\n[TEST 8] Persistence (restart simulation)")
        store.close()

        # Reopen database
        store2 = RotationWindowStore(db_path)
        assert store2.exists("channel1", "rot1") is True
        assert store2.count() == 3
        print(f"  Data persisted across restart")

        store2.close()

    print("\n=== All Tests Passed ===")
