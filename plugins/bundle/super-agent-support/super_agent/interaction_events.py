"""Independent runtime envelopes for basic interaction cards."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .interaction_cards import InteractionCardRecord


class InteractionEventEnvelope(BaseModel):
    """Versioned event payload without any AIGC-only binding fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    event_id: str = Field(min_length=1)
    installation_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    interaction_id: str = Field(min_length=1)
    event_type: Literal[
        "interaction.card.created",
        "interaction.card.cancelled",
        "interaction.card.submitted",
    ]
    interaction: InteractionCardRecord


__all__ = ["InteractionEventEnvelope"]
