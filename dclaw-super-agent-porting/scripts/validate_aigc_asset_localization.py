"""Validate an AIGC asset handoff against the target DevKit and task binding."""

import argparse
import json
from pathlib import Path


CASE_FIELDS = {
    "bound_material_task_id",
    "bound_canvas_id",
    "snapshot_response",
    "list_request",
    "list_response",
    "localize_request",
    "localize_response",
    "read_request",
    "read_response",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _validate_formal_schemas(case, devkit_root):
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError

    root = Path(devkit_root).resolve()
    catalog = json.loads((root / "operation-catalog.json").read_text(encoding="utf-8"))
    workflow = catalog["aigc_workflow_host"]
    assets = workflow["assets"]
    local = catalog["local_task_host"]
    _require(assets["list_capability_id"] == "aigc.task.assets.list/1", "wrong list contract")
    _require(assets["localize_capability_id"] == "aigc.task.assets.localize/1", "wrong localize contract")
    _require(local["read_capability_id"] == "local.task.read/1", "wrong read contract")
    schemas = {
        "snapshot_response": workflow["snapshot"]["response_schema"],
        "list_request": assets["list_request_schema"],
        "list_response": assets["list_response_schema"],
        "localize_request": assets["localize_request_schema"],
        "localize_response": assets["localize_response_schema"],
        "read_request": local["task_request_schema"],
        "read_response": local["receipt_schema"],
    }
    for name, relative_path in schemas.items():
        schema_path = (root / relative_path).resolve()
        _require(schema_path.is_relative_to(root), "schema path outside DevKit")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        try:
            Draft202012Validator(schema).validate(case[name])
        except ValidationError as exc:
            raise ValueError(f"{name}: formal schema mismatch") from exc


def validate_case(case, devkit_root=None):
    _require(isinstance(case, dict) and set(case) == CASE_FIELDS, "case fields mismatch")
    if devkit_root is not None:
        _validate_formal_schemas(case, devkit_root)

    bound_task = case["bound_material_task_id"]
    bound_canvas = case["bound_canvas_id"]
    _require(isinstance(bound_task, str) and bool(bound_task), "missing trusted task binding")
    _require(isinstance(bound_canvas, str) and bool(bound_canvas), "missing trusted canvas binding")
    snapshot = case["snapshot_response"]
    listing = case["list_response"]
    plan = case["localize_request"]
    _require(snapshot.get("status") == "found", "snapshot not found")
    _require(snapshot.get("material_task_id") == bound_task, "snapshot task mismatch")
    _require(snapshot.get("canvas_id") == bound_canvas, "snapshot canvas mismatch")
    _require(case["list_request"].get("material_task_id") == bound_task, "list task mismatch")
    _require(listing.get("status") == "found", "asset list not found")
    _require(listing.get("material_task_id") == bound_task, "asset list task mismatch")
    _require(plan.get("material_task_id") == bound_task, "localize task mismatch")

    succeeded = {
        (job["node_id"], job["job_id"])
        for job in snapshot["node_jobs"] if job["job_status"] == "succeeded"
    }
    generated = {
        (item["node_id"], item["job_id"], item["asset_id"], item["asset_kind"])
        for item in snapshot["generation_assets"]
        if (item["node_id"], item["job_id"]) in succeeded
    }
    listed = {}
    for asset in listing["assets"]:
        asset_id = asset["asset_id"]
        _require(asset_id not in listed, "duplicate listed asset")
        _require(
            (asset["node_id"], asset["job_id"], asset_id, asset["kind"]) in generated,
            "listed asset lacks matching successful job",
        )
        listed[asset_id] = asset

    selected = set()
    orders = set()
    _require(bool(plan["assets"]), "empty localization plan")
    for item in plan["assets"]:
        asset_id = item["asset_id"]
        _require(asset_id in listed, "selected asset not in trusted list")
        _require(asset_id not in selected, "duplicate selected asset")
        _require(isinstance(item["order"], int) and not isinstance(item["order"], bool)
                 and item["order"] >= 0, "invalid asset order")
        _require(item["order"] not in orders, "duplicate asset order")
        expected_destination = "task_root" if item["usage"] == "final_output" else "res"
        _require(item["destination"] == expected_destination, "usage destination mismatch")
        selected.add(asset_id)
        orders.add(item["order"])

    accepted = case["localize_response"]
    finished = case["read_response"]
    _require(accepted.get("status") in {"queued", "running", "succeeded"}, "localize not accepted")
    _require(bool(accepted.get("task_id")), "missing local task ID")
    _require(accepted.get("capability_id") == "aigc.task.assets.localize/1", "capability mismatch")
    _require(accepted.get("idempotency_key") in (None, plan["idempotency_key"]),
             "localize key mismatch")
    _require(case["read_request"].get("task_id") == accepted["task_id"], "read task mismatch")
    _require(finished.get("status") == "succeeded", "localization not complete")
    _require(finished.get("task_id") == accepted["task_id"], "finished task mismatch")
    _require(finished.get("capability_id") == accepted["capability_id"], "capability mismatch")
    _require(finished.get("idempotency_key") in (None, plan["idempotency_key"]),
             "finished key mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devkit-root", required=True, type=Path)
    parser.add_argument("--case", required=True, type=Path)
    args = parser.parse_args()
    try:
        case = json.loads(args.case.read_text(encoding="utf-8"))
        validate_case(case, args.devkit_root)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        if isinstance(exc, ValueError):
            parser.error(str(exc))
        parser.error("DevKit, case, or jsonschema dependency unavailable")
    print("valid: formal schemas and same-task receipts; device files not verified")


if __name__ == "__main__":
    main()
