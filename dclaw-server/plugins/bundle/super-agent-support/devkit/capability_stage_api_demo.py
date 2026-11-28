"""Reference the current capability guide before each model call.

This helper checks the public response shape. It does not decide an expert's
business stage or turn a model proposal into an authorized action.
"""

from __future__ import annotations

from typing import Any


class CapabilityGuideError(ValueError):
    """The Host did not provide the selected stage's usable guide."""


async def enter_stage(host: Any, stage: str) -> dict[str, Any]:
    if stage not in {"interaction", "aigc", "local"}:
        raise CapabilityGuideError("unknown stage")
    response = await host.call("capability.stage.enter/1", {"stage": stage})
    guide = response.get("guide") if isinstance(response, dict) else None
    if (
        not isinstance(response, dict)
        or response.get("contract") != "capability.stage.enter/1"
        or response.get("stage") != stage
        or not isinstance(guide, dict)
        or guide.get("stage") != stage
        or not isinstance(guide.get("instructions"), str)
        or not guide["instructions"].strip()
    ):
        raise CapabilityGuideError("invalid stage guide")
    if stage == "interaction":
        catalog = guide.get("catalog")
        if (
            not isinstance(catalog, dict)
            or catalog.get("catalog_version") != "1"
            or not isinstance(catalog.get("components"), list)
            or not isinstance(guide.get("answer_kind_map"), dict)
        ):
            raise CapabilityGuideError("invalid interaction guide")
    elif stage == "aigc":
        if not isinstance(guide.get("catalog"), dict) or not isinstance(
            guide.get("create_request_schema"), dict,
        ):
            raise CapabilityGuideError("invalid AIGC guide")
    elif not isinstance(guide.get("schemas"), dict):
        raise CapabilityGuideError("invalid local guide")
    return guide
