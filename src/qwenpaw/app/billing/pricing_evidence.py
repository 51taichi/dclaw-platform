"""Strict schemas for untrusted AI-assisted pricing evidence."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PositiveInt


class AiPriceExtraction(BaseModel):
    """One normalized price dimension produced from bounded evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    capability: str = Field(min_length=1, max_length=100)
    unit_key: str = Field(min_length=1, max_length=100)
    unit_size: PositiveInt
    conditions: dict[str, str | int | Decimal]
    currency: Literal["CNY", "USD"]
    price_decimal: Decimal = Field(ge=0)
    fx_rate_decimal: Decimal = Field(gt=0)
    source_urls: list[HttpUrl]
    confidence_decimal: Decimal = Field(ge=0, le=1)
    evidence_excerpt: str = Field(min_length=1, max_length=1000)

    @property
    def rmb_cost(self) -> Decimal:
        return self.price_decimal * self.fx_rate_decimal

