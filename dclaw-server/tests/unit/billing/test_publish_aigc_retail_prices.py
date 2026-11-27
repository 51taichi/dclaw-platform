from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "db"
    / "publish_aigc_retail_prices.py"
)
SPEC = importlib.util.spec_from_file_location("publish_aigc_retail_prices", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _catalog() -> dict:
    return {
        "rules": [
            {
                "id": "image-rule",
                "provider_id": "mxapi",
                "model_key": "gpt-image-2",
                "capability": "text_to_image",
                "unit_type": "metered_dimensions",
                "priority": 0,
                "unit_size": 1,
                "credits_per_unit": 0,
                "input_credits_per_1k": 0,
                "output_credits_per_1k": 0,
                "parameter_match": {},
                "metadata": {
                    "dimensions": [
                        {
                            "unit_key": "image_count",
                            "unit_size": 1,
                            "credits_per_unit": 200,
                        },
                        {
                            "unit_key": "input_tokens",
                            "unit_size": 1_000_000,
                            "credits_per_unit": 1,
                        },
                    ],
                },
            },
        ],
    }


def test_build_rules_changes_only_configured_dimension() -> None:
    payload = {
        "change_reason": "approved",
        "prices": [
            {
                "provider_id": "mxapi",
                "model_key": "gpt-image-2",
                "capability": "text_to_image",
                "unit_key": "image_count",
                "credits_per_unit": 40,
            },
        ],
    }

    rules, changes = MODULE.build_rules(_catalog(), payload)

    dimensions = rules[0].metadata["dimensions"]
    assert dimensions[0]["credits_per_unit"] == 40
    assert dimensions[1]["credits_per_unit"] == 1
    assert changes == [
        {
            "provider_id": "mxapi",
            "model_key": "gpt-image-2",
            "capability": "text_to_image",
            "unit_key": "image_count",
            "old_credits_per_unit": 200,
            "new_credits_per_unit": 40,
        },
    ]


def test_build_rules_rejects_missing_price_dimension() -> None:
    payload = {
        "prices": [
            {
                "provider_id": "mxapi",
                "model_key": "missing",
                "capability": "text_to_video",
                "unit_key": "video_duration_seconds",
                "credits_per_unit": 100,
            },
        ],
    }

    with pytest.raises(ValueError, match="price dimensions not found"):
        MODULE.build_rules(_catalog(), payload)
