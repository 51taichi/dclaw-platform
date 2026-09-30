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


class UpstreamBootstrapRequiredError(UpstreamError):
    def __init__(self, missing_items: list[str]) -> None:
        self.missing_items = list(dict.fromkeys(missing_items))
        super().__init__("ADMIN_BOOTSTRAP_REQUIRED")


__all__ = [
    "UpstreamContractError",
    "UpstreamBootstrapRequiredError",
    "UpstreamError",
    "UpstreamNotFoundError",
    "UpstreamUnavailableError",
]
