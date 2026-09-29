from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SmsAlert:
    event_id: str
    phone_number: str
    display_name: str | None
    tier: str
    available: int
    threshold: int


@dataclass(frozen=True)
class SmsSubmissionResult:
    status: str
    provider_message_id: str | None = None
    provider_error: str | None = None


class SmsSender(Protocol):
    def send(self, alert: SmsAlert) -> SmsSubmissionResult:
        ...


class DisabledSmsSender:
    """First-release sender: deterministic and free of external I/O."""

    def send(self, alert: SmsAlert) -> SmsSubmissionResult:
        del alert
        return SmsSubmissionResult(status="skipped_unconfigured")
