from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> int:
    from qwenpaw.app.sealed_agents.standard_workspace import (
        StandardWorkspaceError,
        validate_standard_workspace,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--agent-id", required=True)
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    try:
        validate_standard_workspace(args.agent_id, workspace)
    except StandardWorkspaceError as exc:
        print(
            json.dumps(
                {
                    "status": "invalid",
                    "agent_id": args.agent_id,
                    "error_code": exc.error_code,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        return 1
    print(
        json.dumps(
            {
                "status": "valid",
                "agent_id": args.agent_id,
                "workspace": str(workspace),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
