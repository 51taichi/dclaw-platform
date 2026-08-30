"""Formal price catalog backed model publication eligibility."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


class ModelPublicationService:
    """Treat the effective retail catalog as the customer model allowlist."""

    def __init__(
        self,
        catalogs: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.catalogs = catalogs
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def published_pairs(self) -> set[tuple[str, str]]:
        return self.effective_pairs() or set()

    def effective_pairs(self) -> set[tuple[str, str]] | None:
        try:
            catalog = self.catalogs.effective_catalog(self.clock())
        except LookupError:
            return None
        return {
            (str(rule["provider_id"]), str(rule["model_key"]))
            for rule in catalog.get("rules", ())
            if rule.get("provider_id") and rule.get("model_key")
        }

    def is_published(self, provider_id: str, model_key: str) -> bool:
        return (provider_id, model_key) in self.published_pairs()
