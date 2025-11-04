"""
SATL 3.0 - Migrate JSON Window Persistence to SQLite

One-time migration script to convert old spo_sliding_window.json to spo_window.db

Usage:
    python tools/migrate_window_json_to_sqlite.py

Input:  spo_sliding_window.json (old format)
Output: spo_window.db (new SQLite database)

Author: SATL 3.0 Research Team
Date: 2025-11-04
"""
import json
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from spo_window_store import RotationWindowStore


def migrate():
    """Migrate JSON window data to SQLite"""
    json_file = "spo_sliding_window.json"
    sqlite_db = "spo_window.db"

    print("="*70)
    print("SATL 3.0 - Window Persistence Migration")
    print("="*70)
    print(f"  Source: {json_file}")
    print(f"  Target: {sqlite_db}")
    print("="*70)

    # Check if JSON file exists
    if not os.path.exists(json_file):
        print(f"\n[ERROR] JSON file not found: {json_file}")
        print("No migration needed.")
        return 0

    # Check if SQLite DB already exists
    if os.path.exists(sqlite_db):
        print(f"\n[WARNING] SQLite database already exists: {sqlite_db}")
        response = input("Overwrite? (yes/no): ")
        if response.lower() != 'yes':
            print("Migration aborted.")
            return 1

        # Backup existing DB
        backup_file = f"{sqlite_db}.backup"
        import shutil
        shutil.copy2(sqlite_db, backup_file)
        print(f"  Created backup: {backup_file}")

    # Load JSON data
    print(f"\n[1/3] Loading JSON data...")
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [ERROR] Failed to load JSON: {e}")
        return 1

    channel_windows = data.get("channel_windows", {})
    print(f"  Found {len(channel_windows)} channels")

    # Count total entries
    total_entries = sum(len(entries) for entries in channel_windows.values())
    print(f"  Total entries: {total_entries}")

    # Create SQLite store
    print(f"\n[2/3] Creating SQLite database...")
    store = RotationWindowStore(sqlite_db)

    # Migrate data
    print(f"\n[3/3] Migrating entries...")
    migrated_count = 0
    skipped_count = 0

    for channel_id, entries in channel_windows.items():
        for entry in entries:
            rotation_id = entry.get("rotation_id")
            issued_at = entry.get("issued_at")
            valid_until = entry.get("valid_until")

            if not all([rotation_id, issued_at, valid_until]):
                print(f"  [WARN] Skipping invalid entry: {entry}")
                skipped_count += 1
                continue

            success = store.add(channel_id, rotation_id, issued_at, valid_until)

            if success:
                migrated_count += 1
            else:
                # Duplicate entry (should not happen in well-formed JSON)
                print(f"  [WARN] Duplicate entry skipped: {rotation_id}")
                skipped_count += 1

    store.close()

    print("\n" + "="*70)
    print("MIGRATION COMPLETE")
    print("="*70)
    print(f"  Migrated: {migrated_count} entries")
    print(f"  Skipped:  {skipped_count} entries")
    print(f"  Database: {sqlite_db}")
    print("="*70)

    # Verify migration
    print(f"\n[VERIFY] Checking SQLite database...")
    store2 = RotationWindowStore(sqlite_db)
    final_count = store2.count()
    channels = store2.get_channels()
    store2.close()

    print(f"  Total entries in DB: {final_count}")
    print(f"  Channels: {len(channels)}")

    if final_count == migrated_count:
        print(f"\n[SUCCESS] Migration verified!")
        print(f"\nNext steps:")
        print(f"  1. Test with: python test_spo_replay_attack.py")
        print(f"  2. If successful, delete old JSON: rm {json_file}")
        return 0
    else:
        print(f"\n[ERROR] Verification failed!")
        print(f"  Expected: {migrated_count} entries")
        print(f"  Found:    {final_count} entries")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(migrate())
    except KeyboardInterrupt:
        print("\n\nMigration interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
