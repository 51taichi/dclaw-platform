# -*- coding: utf-8 -*-
"""Signup-trial policy constants and durable grant identifiers."""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from typing import Mapping


SIGNUP_TRIAL_CREDITS = 100
SIGNUP_TRIAL_EXPIRY = timedelta(days=7)
SIGNUP_TRIAL_ALLOWED_CAPABILITIES = ("text", "image")
SIGNUP_TRIAL_ALLOWED_TIERS = ("standard",)
SIGNUP_TRIAL_DENIED_CAPABILITIES = (
    "video",
    "high_cost",
    "fixed_workflow",
)


def signup_trial_expires_at(now: datetime) -> datetime:
    """Return the seven-day expiry for a newly verified signup trial."""
    return now + SIGNUP_TRIAL_EXPIRY


def signup_trial_idempotency_key(risk_key: str) -> str:
    """Derive a non-PII ledger key that is stable for one risk identity."""
    normalized = risk_key.strip()
    if not normalized:
        raise ValueError("signup trial risk_key must be non-empty")
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return f"signup-trial:risk:{digest}"


def signup_trial_metadata() -> Mapping[str, object]:
    """Describe the capabilities the promotional trial lot may fund."""
    return {
        "grant_policy": "signup_trial",
        "allowed_capabilities": list(SIGNUP_TRIAL_ALLOWED_CAPABILITIES),
        "allowed_tiers": list(SIGNUP_TRIAL_ALLOWED_TIERS),
        "denied_capabilities": list(SIGNUP_TRIAL_DENIED_CAPABILITIES),
    }
