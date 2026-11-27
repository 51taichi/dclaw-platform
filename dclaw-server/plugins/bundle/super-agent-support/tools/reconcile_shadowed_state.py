#!/usr/bin/env python3
"""Preview or repair a migration shadowed by a second state filename."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from super_agent.grants import SuperExpertGrantRepository  # noqa: E402
from super_agent.state_migration import (  # noqa: E402
    StateMigrationError,
    reconcile_shadowed_migration,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--grants-root", type=Path, required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--migrated-filename", required=True)
    parser.add_argument("--active-filename", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-migrated-sha256")
    parser.add_argument("--expected-active-sha256")
    args = parser.parse_args()
    try:
        result = reconcile_shadowed_migration(
            storage_root=args.storage_root,
            grants=SuperExpertGrantRepository(args.grants_root),
            installation_id=args.installation_id,
            session_id=args.session_id,
            user_id=args.user_id,
            migration_id=args.migration_id,
            migrated_filename=args.migrated_filename,
            active_filename=args.active_filename,
            apply=args.apply,
            expected_migrated_sha256=args.expected_migrated_sha256,
            expected_active_sha256=args.expected_active_sha256,
        )
    except (StateMigrationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
