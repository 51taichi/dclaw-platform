# -*- coding: utf-8 -*-
"""Translate model-provider outcomes into durable OpenAPI usage items.

This module intentionally knows nothing about the analytics queue.  A model
call is reserved and settled through ``UsageService`` while the OpenAPI billing
context is installed; the caller can enqueue token analytics only after this
financial path has completed.
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from typing import Any, Mapping

from ..agent_context import get_current_billing_context
from .open_api import OpenApiBillingSession
from .usage import (
    ReserveModelCall,
    SettleModelCall,
    UsageItemResult,
    UsageService,
)


_call_sequence: ContextVar[int] = ContextVar(
    "open_api_model_call_sequence",
    default=0,
)


@dataclass(frozen=True)
class MeteredModelCall:
    """The durable reservation associated with an in-flight provider call."""

    session: OpenApiBillingSession
    item_key: str
    provider_id: str
    model_key: str


class BillingSettlementError(RuntimeError):
    """Supplier work completed but its financial outcome could not persist."""


class BillingModelMeter:
    """Reserve and settle model calls from minimized supplier evidence.

    The service is explicit by design: normal model construction has no hidden
    billing singleton, and callers outside an OpenAPI billing context receive
    ``None`` from :meth:`before_call`.
    """

    adapter_version = "token-recording-v1"

    def __init__(
        self,
        usage_service: UsageService,
        *,
        default_max_output_tokens: int = 1024,
    ) -> None:
        if default_max_output_tokens < 0:
            raise ValueError("default_max_output_tokens must be non-negative")
        self.usage_service = usage_service
        self.default_max_output_tokens = default_max_output_tokens

    def before_call(
        self,
        *,
        provider_id: str,
        model_key: str,
        messages: list[dict[str, Any]],
        max_output_tokens: int | None = None,
        item_key: str | None = None,
    ) -> MeteredModelCall | None:
        """Durably reserve before provider execution, when OpenAPI-scoped."""
        session = get_current_billing_context()
        if not isinstance(session, OpenApiBillingSession):
            return None

        normalized_provider = str(provider_id).strip()
        normalized_model = str(model_key).strip()
        if not normalized_provider or not normalized_model:
            raise ValueError("provider and model identities must be non-empty")
        output_tokens = (
            self.default_max_output_tokens
            if max_output_tokens is None
            else _non_negative_int(max_output_tokens, "max_output_tokens")
        )
        call_key = _item_key(session, item_key)
        self.usage_service.reserve_model_call(
            ReserveModelCall(
                usage_order_id=session.usage_order_id,
                item_key=call_key,
                provider_id=normalized_provider,
                model_key=normalized_model,
                capability="text",
                parameters={"tier": "standard"},
                input_tokens=_estimate_input_tokens(messages),
                max_output_tokens=output_tokens,
            ),
        )
        return MeteredModelCall(
            session=session,
            item_key=call_key,
            provider_id=normalized_provider,
            model_key=normalized_model,
        )

    def record_response(
        self,
        call: MeteredModelCall | None,
        response: Any,
    ) -> UsageItemResult | None:
        """Settle output only with official usage and a supplier reference."""
        if call is None:
            return None
        usage = _official_usage(response)
        supplier_reference = _supplier_reference(response)
        if usage is not None and supplier_reference:
            return self._settle(
                call,
                billability="billable",
                supplier_reference=supplier_reference,
                evidence=_evidence(
                    supplier_reference=supplier_reference,
                    official_usage=usage,
                    response_class="success",
                ),
                actual_input_tokens=usage["input_tokens"],
                actual_output_tokens=usage["output_tokens"],
            )
        return self._settle(
            call,
            billability="unknown",
            supplier_reference=supplier_reference,
            evidence=_evidence(
                supplier_reference=supplier_reference,
                response_class="success_without_official_usage",
            ),
            actual_input_tokens=0,
            actual_output_tokens=0,
        )

    def record_exception(
        self,
        call: MeteredModelCall | None,
        error: BaseException,
        *,
        supplier_contacted: bool = True,
    ) -> UsageItemResult | None:
        """Persist the safest outcome for a failed provider boundary."""
        if call is None:
            return None
        billability, response_class, status = _exception_outcome(
            error,
            supplier_contacted=supplier_contacted,
        )
        reference = _supplier_reference(error)
        return self._settle(
            call,
            billability=billability,
            supplier_reference=reference,
            evidence=_evidence(
                supplier_reference=reference,
                response_class=response_class,
                status=status,
            ),
            actual_input_tokens=0,
            actual_output_tokens=0,
        )

    def record_financial_write_failure(
        self,
        call: MeteredModelCall | None,
        error: BaseException,
    ) -> None:
        """Try to reconcile contacted supplier work without releasing it."""
        if call is None:
            return
        try:
            self.record_exception(call, error, supplier_contacted=True)
        except (
            Exception
        ):  # pragma: no cover - durable hold remains if DB is down
            pass

    def _settle(
        self,
        call: MeteredModelCall,
        *,
        billability: str,
        supplier_reference: str,
        evidence: Mapping[str, Any],
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> UsageItemResult:
        try:
            return self.usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=call.session.usage_order_id,
                    item_key=call.item_key,
                    supplier_reference=supplier_reference,
                    billability=billability,  # type: ignore[arg-type]
                    evidence=evidence,
                    actual_input_tokens=actual_input_tokens,
                    actual_output_tokens=actual_output_tokens,
                ),
            )
        except Exception as exc:
            self.record_financial_write_failure(call, exc)
            raise BillingSettlementError(
                "provider was contacted but billing settlement needs "
                "reconciliation",
            ) from exc


def _item_key(session: OpenApiBillingSession, explicit: str | None) -> str:
    if explicit is not None:
        key = str(explicit).strip()
        if not key:
            raise ValueError("billing item key must be non-empty")
        return key
    sequence = _call_sequence.get() + 1
    _call_sequence.set(sequence)
    return f"model:{session.invocation_id}:{sequence}"


def _estimate_input_tokens(messages: list[dict[str, Any]]) -> int:
    """Conservative, content-free persisted estimate used only for a hold."""
    serialized = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return max(1, ceil(len(serialized) / 4))


def _official_usage(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    try:
        input_tokens = _non_negative_int(
            getattr(usage, "input_tokens"),
            "input_tokens",
        )
        output_tokens = _non_negative_int(
            getattr(usage, "output_tokens"),
            "output_tokens",
        )
    except (TypeError, ValueError):
        return None
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _supplier_reference(value: Any) -> str:
    return str(
        getattr(value, "id", "") or getattr(value, "supplier_reference", ""),
    ).strip()


def _exception_outcome(
    error: BaseException,
    *,
    supplier_contacted: bool,
) -> tuple[str, str, int | None]:
    status = getattr(error, "status_code", None)
    normalized_status = status if isinstance(status, int) else None
    supplier_not_billed = bool(getattr(error, "supplier_not_billed", False))
    if (
        not supplier_contacted
        or supplier_not_billed
        or isinstance(error, ValueError)
    ):
        return "not_billable", "supplier_preflight_rejected", normalized_status
    if normalized_status is not None and 400 <= normalized_status < 500:
        return "not_billable", "supplier_rejected", normalized_status
    return "unknown", "supplier_outcome_unknown", normalized_status


def _evidence(
    *,
    supplier_reference: str,
    response_class: str,
    official_usage: Mapping[str, int] | None = None,
    status: int | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "adapter_version": BillingModelMeter.adapter_version,
        "response_class": response_class,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if supplier_reference:
        evidence["supplier_reference"] = supplier_reference
    if official_usage is not None:
        evidence["official_usage"] = dict(official_usage)
    if status is not None:
        evidence["status"] = status
    return evidence


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return result


__all__ = ["BillingModelMeter", "BillingSettlementError", "MeteredModelCall"]
