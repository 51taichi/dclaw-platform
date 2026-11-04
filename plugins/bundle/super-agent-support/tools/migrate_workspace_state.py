#!/usr/bin/env python3
"""Preview or apply an owner-verified cross-installation state import."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from super_agent.grants import SuperExpertGrantRepository  # noqa: E402
from super_agent.state_migration import (  # noqa: E402
    StateMigrationError,
    migrate_empty_field,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--grants-root", type=Path, required=True)
    parser.add_argument("--source-installation-id", required=True)
    parser.add_argument("--target-installation-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--pointer", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-source-file-sha256")
    parser.add_argument("--expected-target-file-sha256")
    args = parser.parse_args()
    try:
        result = migrate_empty_field(
            storage_root=args.storage_root,
            grants=SuperExpertGrantRepository(args.grants_root),
            source_installation_id=args.source_installation_id,
            target_installation_id=args.target_installation_id,
            session_id=args.session_id,
            user_id=args.user_id,
            pointer=args.pointer,
            apply=args.apply,
            expected_source_file_sha256=args.expected_source_file_sha256,
            expected_target_file_sha256=args.expected_target_file_sha256,
        )
    except (StateMigrationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
