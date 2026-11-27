#!/usr/bin/env python3
"""Preview or apply signed workspace-state continuity for one task."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry  # noqa: E402
from super_agent.grants import SuperExpertGrantRepository  # noqa: E402
from super_agent.state_continuity import (  # noqa: E402
    StateContract,
    StateContinuityError,
    ensure_state_continuity,
    register_legacy_pair,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--apply", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register-legacy-pair")
    register.add_argument("--source-release-id", required=True)
    register.add_argument("--target-release-id", required=True)
    register.add_argument("--evidence-module", default="agent/workflow.py")
    register.add_argument("--format-id", required=True)
    register.add_argument("--schema-version", type=int, required=True)
    register.add_argument("--filename-template", required=True)
    register.add_argument("--expected-source-digest")
    register.add_argument("--expected-target-digest")
    register.add_argument("--expected-evidence-sha256")
    resume = commands.add_parser("resume")
    resume.add_argument("--target-installation-id", required=True)
    resume.add_argument("--expected-target-release-id")
    resume.add_argument("--expected-source-installation-id")
    resume.add_argument("--expected-source-file-sha256")
    resume.add_argument("--session-id", required=True)
    resume.add_argument("--user-id", required=True)
    args = parser.parse_args()
    sealed = args.sealed_root.resolve(strict=True)
    record = SealedAgentRegistry(sealed).get_agent(args.agent_id)
    if record is None:
        print(json.dumps({"status": "rejected", "reason": "agent_not_found"}))
        return 1
    grants = SuperExpertGrantRepository(sealed)
    try:
        if args.command == "register-legacy-pair":
            result = register_legacy_pair(
                storage_root=args.storage_root,
                sealed_root=sealed,
                record=record,
                source_release_id=args.source_release_id,
                target_release_id=args.target_release_id,
                evidence_module=args.evidence_module,
                contract=StateContract(
                    contract="workspace.state.continuity/1",
                    format_id=args.format_id,
                    schema_version=args.schema_version,
                    filename_template=args.filename_template,
                ),
                apply=args.apply,
                expected_source_digest=args.expected_source_digest,
                expected_target_digest=args.expected_target_digest,
                expected_evidence_sha256=args.expected_evidence_sha256,
            )
        else:
            target = grants.get(args.target_installation_id)
            if target is None or target.agent_id != args.agent_id:
                raise StateContinuityError("state_target_installation_invalid")
            result = ensure_state_continuity(
                storage_root=args.storage_root,
                sealed_root=sealed,
                grants=grants,
                record=record,
                target_grant=target,
                session_id=args.session_id,
                user_id=args.user_id,
                apply=args.apply,
                expected_target_release_id=args.expected_target_release_id,
                expected_source_installation_id=args.expected_source_installation_id,
                expected_source_file_sha256=args.expected_source_file_sha256,
            )
    except (StateContinuityError, OSError, ValueError) as exc:
        reason = exc.category if isinstance(exc, StateContinuityError) else "state_continuity_failed"
        print(json.dumps({"status": "rejected", "reason": reason}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
