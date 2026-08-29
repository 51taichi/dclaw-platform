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
from typing import Any, Mapping, cast
from uuid import uuid4

from ..agent_context import get_current_billing_context
from .context import (
    BillingExecutionContext,
    BillingSession,
    SystemBillingExemption,
    get_billing_item_prefix,
    is_billing_required,
)
from .execution import OpenApiBillingExecutionContext, OpenApiExecutionFence
from .open_api import OpenApiBillingSession
from .supplier_reference_sidecar import (
    SupplierReference,
    pop_supplier_reference,
)
from .usage import (
    BillingExecutionFencedError,
    Billability,
    ExecutionOutcome,
    ReserveModelCall,
    SettleModelCall,
    UsageItemResult,
    UsageExecutionGuard,
    UsageService,
)


class MissingBillingContextError(RuntimeError):
    """A user-originated model call has no durable payer execution."""


@dataclass
class MeteredModelCall:
    """The durable reservation associated with an in-flight provider call."""

    session: OpenApiBillingSession | BillingSession
    execution_fence: OpenApiExecutionFence | None
    execution_guard: UsageExecutionGuard | None
    item_key: str
    provider_id: str
    model_key: str
    _finalization_lock: Lock = field(default_factory=Lock, repr=False)
    _finalized: bool = field(default=False, init=False, repr=False)
    _stream_supplier_reference: SupplierReference = field(
        default_factory=lambda: SupplierReference("", ""),
        init=False,
        repr=False,
    )

    def claim_finalization(self) -> bool:
        """Return true exactly once, across stream finalization paths."""
        with self._finalization_lock:
            if self._finalized:
                return False
            self._finalized = True
            return True

    def remember_stream_supplier_reference(
        self,
        reference: SupplierReference,
    ) -> None:
        """Keep one private stream reference after its chunk is yielded."""
        if not reference.value:
            return
        with self._finalization_lock:
            if not self._stream_supplier_reference.value:
                self._stream_supplier_reference = reference

    def stream_supplier_reference(self) -> SupplierReference:
        with self._finalization_lock:
            return self._stream_supplier_reference


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
        self._item_sequence_lock = Lock()
        self._item_sequences: dict[str, int] = {}

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
        context = get_current_billing_context()
        if isinstance(context, SystemBillingExemption):
            return None
        if not isinstance(
            context,
            (OpenApiBillingExecutionContext, BillingExecutionContext),
        ):
            if is_billing_required():
                raise MissingBillingContextError(
                    "user model call has no billing context",
                )
            return None
        session = context.session
        if isinstance(context, OpenApiBillingExecutionContext):
            invocation_id = session.invocation_id
            execution_fence = context.fence
            execution_guard = None
        else:
            invocation_id = ""
            execution_fence = None
            execution_guard = UsageExecutionGuard(
                kind="general",
                execution_id=session.execution_id,
                owner_token=context.fence.owner_token,
                generation=context.fence.generation,
            )

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
        call_key = self._item_key(session, item_key)
        self.usage_service.reserve_model_call(
            ReserveModelCall(
                usage_order_id=session.usage_order_id,
                item_key=call_key,
                provider_id=normalized_provider,
                model_key=normalized_model,
                capability="text",
                parameters={},
                input_tokens=_estimate_input_tokens(messages),
                max_output_tokens=output_tokens,
                invocation_id=invocation_id,
                execution_fence=execution_fence,
                execution_guard=execution_guard,
            ),
        )
        return MeteredModelCall(
            session=session,
            execution_fence=execution_fence,
            execution_guard=execution_guard,
            item_key=call_key,
            provider_id=normalized_provider,
            model_key=normalized_model,
        )

    def _item_key(
        self,
        session: OpenApiBillingSession | BillingSession,
        explicit: str | None,
    ) -> str:
        if explicit is not None:
            return _item_key(session, explicit)
        prefix = get_billing_item_prefix()
        if not prefix:
            return _item_key(session, None)
        with self._item_sequence_lock:
            sequence = self._item_sequences.get(prefix)
            if sequence is None:
                sequence = sum(
                    1
                    for item in self.usage_service.list_items(
                        session.usage_order_id,
                    )
                    if str(item.get("item_key") or "").startswith(
                        f"{prefix}:",
                    )
                )
            sequence += 1
            self._item_sequences[prefix] = sequence
        return f"{prefix}:{sequence}"

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
                    execution_outcome="pending",
                    evidence=_evidence(
                        supplier_reference=SupplierReference("", ""),
                        response_class="provider_call_started",
                    ),
                    actual_input_tokens=0,
                    actual_output_tokens=0,
                    **_execution_fields(call),
                ),
            )
        except BillingExecutionFencedError:
            raise
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
        if not supplier_reference.value:
            supplier_reference = call.stream_supplier_reference()
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
                execution_outcome="succeeded",
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
            execution_outcome="succeeded",
        )

    def observe_stream_chunk(
        self,
        call: MeteredModelCall | None,
        response: Any,
    ) -> None:
        """Consume sidecar evidence before a public stream chunk is yielded."""
        if call is None:
            pop_supplier_reference(response)
            return
        call.remember_stream_supplier_reference(_supplier_reference(response))

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
        if not reference.value:
            reference = call.stream_supplier_reference()
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
            execution_outcome="failed",
        )

    def record_financial_write_failure(
        self,
        call: MeteredModelCall,
        _error: BaseException,
        supplier_reference: SupplierReference,
        execution_outcome: str,
    ) -> BaseException | None:
        """Attempt one non-recursive durable reconciliation transition."""
        try:
            self.usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=call.session.usage_order_id,
                    item_key=call.item_key,
                    supplier_reference=supplier_reference.value,
                    billability="unknown",
                    execution_outcome=cast(
                        ExecutionOutcome,
                        execution_outcome,
                    ),
                    evidence=_evidence(
                        supplier_reference=supplier_reference,
                        response_class="financial_write_failure",
                    ),
                    actual_input_tokens=0,
                    actual_output_tokens=0,
                    **_execution_fields(call),
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
        execution_outcome: str,
    ) -> UsageItemResult:
        try:
            return self.usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=call.session.usage_order_id,
                    item_key=call.item_key,
                    supplier_reference=supplier_reference.value,
                    billability=cast(Billability, billability),
                    evidence=evidence,
                    execution_outcome=cast(
                        ExecutionOutcome,
                        execution_outcome,
                    ),
                    actual_input_tokens=actual_input_tokens,
                    actual_output_tokens=actual_output_tokens,
                    **_execution_fields(call),
                ),
            )
        except BillingExecutionFencedError:
            raise
        except Exception as exc:
            fallback_error = self.record_financial_write_failure(
                call,
                exc,
                supplier_reference,
                execution_outcome,
            )
            detail = "reconciliation"
            if fallback_error is not None:
                detail = "durable reconciliation is unavailable"
            raise BillingSettlementError(
                "provider was contacted but billing settlement needs "
                f"{detail}",
            ) from exc


def _execution_fields(call: MeteredModelCall) -> dict[str, Any]:
    if isinstance(call.session, OpenApiBillingSession):
        return {
            "invocation_id": call.session.invocation_id,
            "execution_fence": call.execution_fence,
            "execution_guard": None,
        }
    return {
        "invocation_id": "",
        "execution_fence": None,
        "execution_guard": call.execution_guard,
    }


def _item_key(
    session: OpenApiBillingSession | BillingSession,
    explicit: str | None,
) -> str:
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
    sidecar_reference = pop_supplier_reference(value)
    if (
        sidecar_reference.value
        and sidecar_reference.source in _SUPPLIER_REFERENCE_SOURCES
    ):
        return sidecar_reference
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
