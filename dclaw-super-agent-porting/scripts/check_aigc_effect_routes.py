#!/usr/bin/env python3
"""Run an Agent-owned adapter against fixed AIGC creation fault scenarios."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

CASES = ("success", "catalog_only", "created_no_text", "unknown_result", "replay")
RUNNER = Path(__file__).with_name("_aigc_effect_adapter_runner.py")
ENTRY = re.compile(r"[a-z][a-z0-9_.-]{1,63}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
ALLOWED_CALLS = {"aigc_workflow_catalog", "aigc_workflow_create",
                 "aigc.task.binding.resolve/1", "aigc.task.snapshot/1"}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_routes(path, runtime_hash):
    if not path.is_file():
        raise ValueError("AIGC.ROUTE_MISSING")
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"schema_version", "runtime_sha256", "entries"}:
        raise ValueError("AIGC.ROUTE_INVALID")
    if data["schema_version"] != "aigc-effect-routes/1":
        raise ValueError("AIGC.ROUTE_INVALID")
    if not isinstance(data["runtime_sha256"], str) or not HASH.fullmatch(data["runtime_sha256"]):
        raise ValueError("AIGC.ROUTE_INVALID")
    if data["runtime_sha256"] != runtime_hash:
        raise ValueError("AIGC.SOURCE_MISMATCH")
    entries = data["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("AIGC.ROUTE_MISSING")
    names = []
    for entry in entries:
        if set(entry) != {"entry_id", "cases"} or not isinstance(entry["entry_id"], str):
            raise ValueError("AIGC.ROUTE_INVALID")
        if not ENTRY.fullmatch(entry["entry_id"]):
            raise ValueError("AIGC.ROUTE_INVALID")
        if entry["cases"] != list(CASES):
            raise ValueError("AIGC.ROUTE_MISSING")
        names.append(entry["entry_id"])
    if len(names) != len(set(names)):
        raise ValueError("AIGC.ROUTE_INVALID")
    return names


def check_shape(observation, runtime_hash):
    if not isinstance(observation, dict) or set(observation) != {
            "runtime_sha256", "calls", "state", "evidence", "terminal", "model_text_kind",
            "invocations"}:
        return "AIGC.OBSERVATION_UNVERIFIED"
    if observation["runtime_sha256"] != runtime_hash:
        return "AIGC.SOURCE_MISMATCH"
    calls = observation["calls"]
    if not isinstance(calls, list) or any(
            not isinstance(call, dict) or set(call) != {"capability", "outcome"}
            or not isinstance(call["capability"], str)
            or call["capability"] not in ALLOWED_CALLS
            or not isinstance(call["outcome"], str)
            or call["outcome"] not in {"completed", "failed", "started_unknown"}
            for call in calls):
        return "AIGC.OBSERVATION_UNVERIFIED"
    state = observation["state"]
    evidence = observation["evidence"]
    terminal = observation["terminal"]
    if (not isinstance(state, dict) or set(state) != {
            "created", "attempt", "key_preserved", "revision_preserved", "blueprint_preserved"}
            or type(state["created"]) is not bool
            or not isinstance(state["attempt"], str)
            or state["attempt"] not in {"none", "planned", "unknown", "verified"}
            or any(type(state[key]) is not bool for key in (
                "key_preserved", "revision_preserved", "blueprint_preserved"))
            or not isinstance(evidence, dict)
            or set(evidence) != {"create", "binding", "snapshot"}
            or not isinstance(evidence["create"], str)
            or evidence["create"] not in {"not_observed", "completed", "started_unknown"}
            or not isinstance(evidence["binding"], str)
            or evidence["binding"] not in {
                "not_read", "not_found", "found", "ambiguous", "unavailable"}
            or not isinstance(evidence["snapshot"], str)
            or evidence["snapshot"] not in {"not_read", "matched", "mismatch"}
            or not isinstance(terminal, dict) or set(terminal) != {"status", "code"}
            or not isinstance(terminal["status"], str)
            or terminal["status"] not in {"blocked", "created", "recovered"}
            or not isinstance(terminal["code"], str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", terminal["code"])
            or not isinstance(observation["model_text_kind"], str)
            or observation["model_text_kind"] not in {"none", "plain", "receipt_like"}
            or type(observation["invocations"]) is not int
            or observation["invocations"] not in (1, 2)):
        return "AIGC.OBSERVATION_UNVERIFIED"
    return None


def check_case(case, observation):
    calls = observation["calls"]
    state = observation["state"]
    evidence = observation["evidence"]
    terminal = observation["terminal"]
    creates = [call for call in calls if call["capability"] == "aigc_workflow_create"]
    catalogs = [call for call in calls if call["capability"] == "aigc_workflow_catalog"]
    if observation["invocations"] != (2 if case == "replay" else 1):
        return "AIGC.OBSERVATION_UNVERIFIED"
    if not catalogs or (creates and calls.index(catalogs[0]) > calls.index(creates[0])):
        return "AIGC.CONTRACT_MISMATCH"
    if not all(state[key] for key in (
            "key_preserved", "revision_preserved", "blueprint_preserved")):
        return "AIGC.UNKNOWN_REPLAY"
    if case != "replay" and len(catalogs) != 1:
        return "AIGC.CONTRACT_MISMATCH"
    if case in {"success", "created_no_text", "replay"}:
        if len(creates) != 1 or creates[0]["outcome"] != "completed":
            return "AIGC.CREATE_NOT_OBSERVED"
        if evidence["create"] != "completed":
            return "AIGC.OBSERVATION_UNVERIFIED"
        if evidence["binding"] != "found" or evidence["snapshot"] != "matched":
            return "AIGC.BINDING_UNVERIFIED"
        if not state["created"] or state["attempt"] != "verified":
            return "AIGC.TEXT_AS_RECEIPT" if case == "created_no_text" else "AIGC.BINDING_UNVERIFIED"
        if terminal != {"status": "created", "code": "CREATED"}:
            return "AIGC.BINDING_UNVERIFIED"
        if case == "created_no_text" and observation["model_text_kind"] != "none":
            return "AIGC.OBSERVATION_UNVERIFIED"
    elif case == "catalog_only":
        if state["created"] and observation["model_text_kind"] == "receipt_like":
            return "AIGC.TEXT_AS_RECEIPT"
        if (len(creates) != 0 or evidence["create"] != "not_observed"
                or evidence["binding"] not in {"not_read", "not_found"}
                or state["created"]):
            return "AIGC.CREATE_NOT_OBSERVED"
        if state["attempt"] not in {"none", "planned"}:
            return "AIGC.ATTEMPT_LOCKED"
        if terminal != {"status": "blocked", "code": "CREATE_NOT_OBSERVED"}:
            return "AIGC.CREATE_NOT_OBSERVED"
        if observation["model_text_kind"] != "receipt_like":
            return "AIGC.OBSERVATION_UNVERIFIED"
    elif case == "unknown_result":
        if (len(creates) != 1 or creates[0]["outcome"] != "started_unknown"
                or evidence["create"] != "started_unknown"
                or evidence["binding"] not in {"not_found", "ambiguous", "unavailable"}
                or evidence["snapshot"] != "not_read"):
            return "AIGC.UNKNOWN_REPLAY"
        if state["created"] or state["attempt"] != "unknown":
            return "AIGC.UNKNOWN_REPLAY"
        if terminal != {"status": "blocked", "code": "RESULT_UNKNOWN"}:
            return "AIGC.UNKNOWN_REPLAY"
    return None


def run_adapter(adapter, runtime, entry, case, runtime_hash):
    try:
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--adapter", str(adapter), "--runtime", str(runtime),
             "--entry", entry, "--case", case],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if result.returncode or len(result.stdout) > 32768 or len(result.stderr) > 32768:
            return "AIGC.OBSERVATION_UNVERIFIED"
        envelope = json.loads(result.stdout)
        if (not isinstance(envelope, dict) or set(envelope) != {
                "runtime_function_calls", "observation"}
                or type(envelope["runtime_function_calls"]) is not int
                or envelope["runtime_function_calls"] < 1):
            return "AIGC.OBSERVATION_UNVERIFIED"
        observation = envelope["observation"]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return "AIGC.OBSERVATION_UNVERIFIED"
    return check_shape(observation, runtime_hash) or check_case(case, observation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--routes", required=True, type=Path)
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.runtime.is_file() or not args.adapter.is_file():
        parser.error("runtime and adapter must be files")
    runtime_hash = digest(args.runtime)
    try:
        entries = load_routes(args.routes, runtime_hash)
    except (OSError, ValueError, TypeError) as exc:
        code = str(exc)
        if code not in {"AIGC.ROUTE_INVALID", "AIGC.ROUTE_MISSING", "AIGC.SOURCE_MISMATCH"}:
            code = "AIGC.ROUTE_INVALID"
        report = {"schema_version": "aigc-effect-check/1", "runtime_sha256": runtime_hash,
                  "results": [], "status": "blocked", "code": code}
    else:
        results = []
        for entry in entries:
            for case in CASES:
                code = run_adapter(args.adapter, args.runtime, entry, case, runtime_hash)
                results.append({"entry_id": entry, "case": case,
                                "status": "failed" if code else "passed",
                                "code": code or "AIGC.OK"})
        report = {"schema_version": "aigc-effect-check/1", "runtime_sha256": runtime_hash,
                  "results": results, "status": "failed" if any(
                      item["status"] == "failed" for item in results) else "passed",
                  "code": "AIGC.TEST_FAILED" if any(
                      item["status"] == "failed" for item in results) else "AIGC.OK"}
    result_text = json.dumps(report, ensure_ascii=True, sort_keys=True)
    if args.output:
        if args.output.exists() or args.output.is_symlink():
            parser.error("output already exists; choose a new report path")
        args.output.write_text(result_text + "\n", encoding="utf-8")
    print(result_text)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
