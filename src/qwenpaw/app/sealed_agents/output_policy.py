"""Conservative final-output filter for sealed agent invocations."""

from __future__ import annotations

import re
from dataclasses import dataclass

_REFUSAL = "无法提供该密封 Agent 的内部信息。"
_ENCODED_BULK = re.compile(r"(?:[A-Za-z0-9+/]{4}){256,}={0,2}")
_HEX_BULK = re.compile(r"(?:[0-9a-fA-F]{2}){512,}")


@dataclass(frozen=True)
class OutputPolicyResult:
    allowed: bool
    public_text: str
    reason_code: str | None = None


class SealedOutputPolicy:
    def __init__(
        self,
        *,
        protected_texts: list[str],
        canaries: list[str],
    ) -> None:
        self._protected_texts = [
            _normalize(value)
            for value in protected_texts
            if len(_normalize(value)) >= 40
        ]
        self._canaries = [value for value in canaries if value]

    def evaluate(self, text: str) -> OutputPolicyResult:
        for canary in self._canaries:
            if canary in text:
                return _blocked("sealed_canary")
        normalized = _normalize(text)
        if any(value in normalized for value in self._protected_texts):
            return _blocked("sealed_source_overlap")
        compact = "".join(text.split())
        if _ENCODED_BULK.search(compact) or _HEX_BULK.search(compact):
            return _blocked("sealed_encoded_bulk")
        return OutputPolicyResult(allowed=True, public_text=text)


def _blocked(reason: str) -> OutputPolicyResult:
    return OutputPolicyResult(
        allowed=False,
        public_text=_REFUSAL,
        reason_code=reason,
    )


def _normalize(value: str) -> str:
    return " ".join(value.split())
