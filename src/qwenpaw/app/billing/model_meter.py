# -*- coding: utf-8 -*-
"""Translate model-provider outcomes into durable OpenAPI usage items.

This module intentionally knows nothing about the analytics queue.  A model
call is reserved and settled through ``UsageService`` while the OpenAPI billing
context is installed; the caller can enqueue token analytics only after this
financial path has completed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Mapping
from uuid import uuid4

from ..agent_context import get_current_billing_context
from .open_api import OpenApiBillingSession
from .usage import (
    ReserveModelCall,
    SettleModelCall,
    UsageItemResult,
    UsageService,
)


@dataclass
class MeteredModelCall:
    """The durable reservation associated with an in-flight provider call."""

    session: OpenApiBillingSession
    item_key: str
    provider_id: str
    model_key: str
    _finalization_lock: Lock = field(default_factory=Lock, repr=False)
    _finalized: bool = field(default=False, init=False, repr=False)

    def claim_finalization(self) -> bool:
        """Return true exactly once, across stream finalization paths."""
        with self._finalization_lock:
            if self._finalized:
                return False
            self._finalized = True
            return True


@dataclass(frozen=True)
class SupplierReference:
    """A supplier reference explicitly surfaced by a provider adapter."""

    value: str
    source: str


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
        platform_max_output_tokens: int | None = None,
    ) -> None:
        if default_max_output_tokens < 0 or (
            platform_max_output_tokens is not None
            and platform_max_output_tokens < 0
        ):
            raise ValueError("output token limits must be non-negative")
        self.usage_service = usage_service
        self.default_max_output_tokens = default_max_output_tokens
        self.platform_max_output_tokens = (
            default_max_output_tokens
            if platform_max_output_tokens is None
            else platform_max_output_tokens
        )

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
        output_tokens = self.default_max_output_tokens
        if max_output_tokens is not None:
            output_tokens = _non_negative_int(
                max_output_tokens,
                "max_output_tokens",
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

    def mark_provider_call_started(
        self,
        call: MeteredModelCall | None,
    ) -> UsageItemResult | None:
        """Durably mark supplier contact before executing the provider call."""
        if call is None:
            return None
        try:
            return self.usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=call.session.usage_order_id,
                    item_key=call.item_key,
                    supplier_reference="",
                    billability="unknown",
                    evidence=_evidence(
                        supplier_reference=SupplierReference("", ""),
                        response_class="provider_call_started",
                    ),
                    actual_input_tokens=0,
                    actual_output_tokens=0,
                ),
            )
        except Exception as exc:
            raise BillingSettlementError(
                "provider call was not started because billing marker "
                "could not persist",
            ) from exc

    def record_response(
        self,
        call: MeteredModelCall | None,
        response: Any,
    ) -> UsageItemResult | None:
        """Settle output only with official usage and a supplier reference."""
        if call is None or not call.claim_finalization():
            return None
        usage = _official_usage(response)
        supplier_reference = _supplier_reference(response)
        if usage is not None and supplier_reference.value:
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
        if call is None or not call.claim_finalization():
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
        call: MeteredModelCall,
        _error: BaseException,
        supplier_reference: SupplierReference,
    ) -> BaseException | None:
        """Attempt one non-recursive durable reconciliation transition."""
        try:
            self.usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=call.session.usage_order_id,
                    item_key=call.item_key,
                    supplier_reference=supplier_reference.value,
                    billability="unknown",
                    evidence=_evidence(
                        supplier_reference=supplier_reference,
                        response_class="financial_write_failure",
                    ),
                    actual_input_tokens=0,
                    actual_output_tokens=0,
                ),
            )
        except BaseException as fallback_error:  # keep original hold if down
            return fallback_error
        return None

    def _settle(
        self,
        call: MeteredModelCall,
        *,
        billability: str,
        supplier_reference: SupplierReference,
        evidence: Mapping[str, Any],
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> UsageItemResult:
        try:
            return self.usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=call.session.usage_order_id,
                    item_key=call.item_key,
                    supplier_reference=supplier_reference.value,
                    billability=billability,  # type: ignore[arg-type]
                    evidence=evidence,
                    actual_input_tokens=actual_input_tokens,
                    actual_output_tokens=actual_output_tokens,
                ),
            )
        except Exception as exc:
            fallback_error = self.record_financial_write_failure(
                call,
                exc,
                supplier_reference,
            )
            detail = "reconciliation"
            if fallback_error is not None:
                detail = "durable reconciliation is unavailable"
            raise BillingSettlementError(
                "provider was contacted but billing settlement needs "
                f"{detail}",
            ) from exc


def _item_key(session: OpenApiBillingSession, explicit: str | None) -> str:
    if explicit is not None:
        key = str(explicit).strip()
        if not key:
            raise ValueError("billing item key must be non-empty")
        return key
    del session
    return f"model:{uuid4()}"


def _estimate_input_tokens(messages: list[dict[str, Any]]) -> int:
    """Conservative, content-free persisted estimate used only for a hold."""
    serialized = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return max(1, len(serialized.encode("utf-8")))


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


def _supplier_reference(value: Any) -> SupplierReference:
    reference = str(
        _optional_value(value, "supplier_billing_reference") or "",
    ).strip()
    source = str(
        _optional_value(value, "supplier_billing_reference_source") or "",
    ).strip()
    if reference and source in _SUPPLIER_REFERENCE_SOURCES:
        return SupplierReference(reference, source)
    return SupplierReference("", "")


_SUPPLIER_REFERENCE_SOURCES = frozenset(
    {
        "provider_response",
        "provider_error",
        "openai.chat.completion.id",
        "openai.chat.chunk.id",
        "anthropic.message.id",
        "gemini.response_id",
    },
)


def _optional_value(value: Any, name: str) -> Any:
    """Safely read optional fields from AgentScope's dict-like responses."""
    try:
        if isinstance(value, Mapping):
            return value.get(name)
        return getattr(value, name, None)
    except (AttributeError, KeyError, TypeError):
        return None


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
        or getattr(error, "phase", None) == "pre_contact"
    ):
        return "not_billable", "supplier_preflight_rejected", normalized_status
    if supplier_not_billed:
        return "not_billable", "supplier_rejected", normalized_status
    return "unknown", "supplier_outcome_unknown", normalized_status


def _evidence(
    *,
    supplier_reference: SupplierReference,
    response_class: str,
    official_usage: Mapping[str, int] | None = None,
    status: int | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "adapter_version": BillingModelMeter.adapter_version,
        "response_class": response_class,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if supplier_reference.value:
        evidence["supplier_reference"] = supplier_reference.value
        evidence["supplier_reference_source"] = supplier_reference.source
    if official_usage is not None:
        evidence["official_usage"] = dict(official_usage)
    if status is not None:
        evidence["status"] = status
    return evidence


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-negative integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return result


__all__ = ["BillingModelMeter", "BillingSettlementError", "MeteredModelCall"]
