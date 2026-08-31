"""Trusted registry for server-owned sealed runtime adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


class UnsupportedSealedRuntime(ValueError):
    """A signed package requested a runtime contract this server cannot run."""


class SealedRuntimeAdapter(Protocol):
    @property
    def key(self) -> tuple[str, str]: ...

    async def run(
        self,
        *,
        pinned: Any,
        request: Any,
        model_executor: Any,
    ) -> AsyncIterator[Any]: ...


@dataclass(frozen=True)
class _ReservedRuntimeAdapter:
    """Registry placeholder replaced by the concrete execution implementation."""

    adapter: str
    contract_version: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.adapter, self.contract_version)

    async def run(
        self,
        *,
        pinned: Any,
        request: Any,
        model_executor: Any,
    ) -> AsyncIterator[Any]:
        raise UnsupportedSealedRuntime("sealed runtime adapter is not executable")
        yield  # pragma: no cover


_ADAPTERS: dict[tuple[str, str], SealedRuntimeAdapter] = {
    ("standard", "1"): _ReservedRuntimeAdapter("standard", "1"),
    ("sealed_harness", "1"): _ReservedRuntimeAdapter("sealed_harness", "1"),
}


def get_runtime_adapter(adapter: str, contract_version: str) -> SealedRuntimeAdapter:
    try:
        return _ADAPTERS[(adapter, contract_version)]
    except KeyError as exc:
        raise UnsupportedSealedRuntime(
            "sealed runtime adapter is not supported",
        ) from exc


def register_runtime_adapter(adapter: SealedRuntimeAdapter) -> None:
    """Install a server-owned implementation for an already allowlisted key."""
    if adapter.key not in _ADAPTERS:
        raise UnsupportedSealedRuntime("sealed runtime adapter is not allowlisted")
    _ADAPTERS[adapter.key] = adapter
