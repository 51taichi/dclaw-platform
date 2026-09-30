"""Safe error types shared by read-only upstream clients."""

from __future__ import annotations


class UpstreamError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class UpstreamUnavailableError(UpstreamError):
    pass


class UpstreamContractError(UpstreamError):
    pass


class UpstreamNotFoundError(UpstreamError):
    pass


__all__ = [
    "UpstreamContractError",
    "UpstreamError",
    "UpstreamNotFoundError",
    "UpstreamUnavailableError",
]
