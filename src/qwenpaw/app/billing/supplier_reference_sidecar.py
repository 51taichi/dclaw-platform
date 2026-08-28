# -*- coding: utf-8 -*-
"""Private, one-shot supplier-reference storage for parsed responses.

Provider IDs are accounting evidence, not response data.  AgentScope response
objects are dict-like, so setting an attribute on them serializes it into the
public response.  Keep the evidence in this identity sidecar instead and
remove it when the billing boundary consumes (or discards) the response.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any
from weakref import ref


@dataclass(frozen=True)
class SupplierReference:
    """A provider adapter's explicitly verified supplier identifier."""

    value: str
    source: str


_references: dict[int, tuple[ref[Any], SupplierReference]] = {}
_references_lock = Lock()


def stash_supplier_reference(
    response: Any,
    reference: Any,
    source: str,
) -> None:
    """Associate validated adapter evidence without changing ``response``.

    Values that cannot be weak-referenced deliberately receive no evidence:
    treating them as unknown is safer than retaining an unbounded strong
    global reference or serializing financial metadata to a caller.
    """
    if not isinstance(reference, str) or not reference.strip():
        return
    if not isinstance(source, str) or not source.strip():
        return
    identity = id(response)

    def cleanup(dead_reference: ref[Any]) -> None:
        with _references_lock:
            current = _references.get(identity)
            if current is not None and current[0] is dead_reference:
                _references.pop(identity, None)

    try:
        response_ref = ref(response, cleanup)
    except TypeError:
        return
    with _references_lock:
        _references[identity] = (
            response_ref,
            SupplierReference(reference.strip(), source.strip()),
        )


def pop_supplier_reference(response: Any) -> SupplierReference:
    """Consume evidence once, verifying object identity before returning it."""
    with _references_lock:
        stored = _references.pop(id(response), None)
    if stored is None or stored[0]() is not response:
        return SupplierReference("", "")
    return stored[1]


__all__ = [
    "SupplierReference",
    "pop_supplier_reference",
    "stash_supplier_reference",
]
