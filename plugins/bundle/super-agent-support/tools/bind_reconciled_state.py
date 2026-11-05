#!/usr/bin/env python3
"""Bind a previously repaired state file to the runtime commit guard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from super_agent.grants import SuperExpertGrantRepository  # noqa: E402
from super_agent.state_migration import (  # noqa: E402
    StateMigrationError,
    bind_reconciled_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--grants-root", type=Path, required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--repair-id", required=True)
    parser.add_argument("--expected-state-sha256", required=True)
    args = parser.parse_args()
    try:
        result = bind_reconciled_state(
            storage_root=args.storage_root,
            grants=SuperExpertGrantRepository(args.grants_root),
            installation_id=args.installation_id,
            session_id=args.session_id,
            user_id=args.user_id,
            repair_id=args.repair_id,
            expected_state_sha256=args.expected_state_sha256,
        )
    except (StateMigrationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
