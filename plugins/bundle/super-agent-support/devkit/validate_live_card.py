"""Validate a card against the complete schema returned by the Host catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


def validate_live_card(catalog: dict, component_type: str, card: dict) -> None:
    if catalog.get("catalog_version") != "1":
        raise ValueError("unsupported interaction catalog")
    components = [
        component for component in catalog.get("components", [])
        if isinstance(component, dict)
        and component.get("component_type") == component_type
        and component.get("contract_version") == "1"
        and isinstance(component.get("schema"), dict)
    ]
    if len(components) != 1:
        raise ValueError("exactly one detailed component schema is required")
    schema = components[0]["schema"]
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(card)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path, help="complete Host catalog response")
    parser.add_argument("card", type=Path, help="card object, without the outer request")
    parser.add_argument("--component-type", default="single_select")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    card = json.loads(args.card.read_text(encoding="utf-8"))
    try:
        validate_live_card(catalog, args.component_type, card)
    except ValidationError as exc:
        path = "/".join(str(part) for part in exc.absolute_path) or "card"
        print(json.dumps({"valid": False, "field_path": path, "constraint": exc.validator}))
        return 1
    except ValueError as exc:
        print(json.dumps({"valid": False, "category": str(exc)}))
        return 1
    print(json.dumps({"valid": True, "component_type": args.component_type}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
