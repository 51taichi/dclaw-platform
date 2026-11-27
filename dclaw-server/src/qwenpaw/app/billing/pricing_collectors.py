"""Ordered, auditable pricing evidence collection primitives."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from .official_pricing import OfficialPriceRegistry
from .pricing_evidence import AiPriceExtraction
from .pricing_inventory import PriceableModel

EvidenceLevel = Literal[
    "official_verified",
    "ai_official_extract",
    "ai_multi_source",
    "ai_no_evidence",
    "failed",
]

EVIDENCE_DEFAULTS: dict[
    EvidenceLevel, tuple[Decimal | None, bool]
] = {
    "official_verified": (Decimal("1.5"), True),
    "ai_official_extract": (Decimal("1.6"), False),
    "ai_multi_source": (Decimal("1.8"), False),
    "ai_no_evidence": (Decimal("2.0"), False),
    "failed": (None, False),
}


@dataclass(frozen=True)
class CollectedPriceCandidate:
    provider_id: str
    official_model_id: str
    pricing_region: str | None
    capability: str
    unit_key: str
    unit_size: int
    conditions: Mapping[str, Any]
    original_currency: str
    original_price: Decimal
    rmb_cost: Decimal
    source_url: str | None
    evidence_level: EvidenceLevel
    evidence_excerpt: str | None
    collector_version: str
    ai_model: str | None
    prompt_version: str | None
    confidence: Decimal | None

    def validate(self, official_hosts: frozenset[str]) -> None:
        if self.unit_size <= 0:
            raise ValueError("invalid price quantity")
        if self.original_price < 0 or self.rmb_cost < 0:
            raise ValueError("invalid price quantity")
        if self.original_currency not in {"CNY", "USD"}:
            raise ValueError("unsupported price currency")
        if self.confidence is not None and not Decimal(0) <= self.confidence <= Decimal(1):
            raise ValueError("invalid price confidence")
        if self.source_url is None:
            if self.evidence_level not in {"ai_no_evidence", "failed"}:
                raise ValueError("pricing evidence source is required")
            return
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in official_hosts:
            raise ValueError("untrusted pricing source")


class PriceCollector(Protocol):
    def collect(
        self, model: PriceableModel
    ) -> Sequence[CollectedPriceCandidate]:
        ...  # noqa: E704


@dataclass(frozen=True)
class CollectionStage:
    name: str
    collector: PriceCollector


@dataclass(frozen=True)
class ModelCollectionResult:
    provider_id: str
    model_key: str
    pricing_region: str | None
    evidence_level: EvidenceLevel
    default_multiplier: Decimal | None
    default_include_in_publish: bool
    candidates: tuple[CollectedPriceCandidate, ...]
    attempt_errors: tuple[str, ...] = ()


class PricingCollectionPipeline:
    """Stop at the first collection stage that yields valid candidates."""

    def __init__(self, stages: Sequence[CollectionStage]) -> None:
        self.stages = tuple(stages)

    def collect(self, model: PriceableModel) -> ModelCollectionResult:
        attempt_errors: list[str] = []
        for stage in self.stages:
            try:
                candidates = tuple(stage.collector.collect(model))
            except Exception as exc:  # pylint: disable=broad-exception-caught
                attempt_errors.append(f"{stage.name}: {exc}")
                continue
            if not candidates:
                continue
            levels = {candidate.evidence_level for candidate in candidates}
            if len(levels) != 1:
                raise ValueError(
                    f"collection stage {stage.name} returned mixed evidence"
                )
            level = next(iter(levels))
            multiplier, included = EVIDENCE_DEFAULTS[level]
            return ModelCollectionResult(
                provider_id=model.provider_id,
                model_key=model.model_key,
                pricing_region=model.pricing_region,
                evidence_level=level,
                default_multiplier=multiplier,
                default_include_in_publish=included,
                candidates=candidates,
                attempt_errors=tuple(attempt_errors),
            )
        return ModelCollectionResult(
            provider_id=model.provider_id,
            model_key=model.model_key,
            pricing_region=model.pricing_region,
            evidence_level="failed",
            default_multiplier=None,
            default_include_in_publish=False,
            candidates=(),
            attempt_errors=tuple(attempt_errors),
        )


class OfficialRegistryCollector:
    """Return bundled verified evidence for an exact model and region."""

    def __init__(
        self,
        registry: OfficialPriceRegistry,
        official_hosts: Mapping[str, frozenset[str]],
    ) -> None:
        self.registry = registry
        self.official_hosts = dict(official_hosts)

    def collect(
        self, model: PriceableModel
    ) -> tuple[CollectedPriceCandidate, ...]:
        if model.official_model_id is None:
            return ()
        hosts = self.official_hosts.get(model.provider_id, frozenset())
        rows: list[CollectedPriceCandidate] = []
        for dimension in self.registry.dimensions(
            model.provider_id, model.official_model_id
        ):
            official_region = dimension.conditions.get("region")
            if official_region is not None and (
                model.pricing_region is None
                or official_region != model.pricing_region
            ):
                continue
            row = CollectedPriceCandidate(
                provider_id=model.provider_id,
                official_model_id=model.official_model_id,
                pricing_region=(
                    str(official_region)
                    if official_region is not None
                    else model.pricing_region
                ),
                capability=dimension.capability,
                unit_key=dimension.unit_key,
                unit_size=dimension.unit_size,
                conditions=dimension.conditions,
                original_currency=dimension.original_currency,
                original_price=dimension.original_price,
                rmb_cost=dimension.rmb_cost,
                source_url=dimension.source_url,
                evidence_level="official_verified",
                evidence_excerpt=None,
                collector_version=dimension.registry_version,
                ai_model=None,
                prompt_version=None,
                confidence=Decimal(1),
            )
            row.validate(hosts)
            rows.append(row)
        return tuple(rows)


class StructuredAiCollector:
    """Convert strict AI extraction payloads into non-official candidates."""

    def __init__(
        self,
        *,
        extractor: Callable[
            [PriceableModel, Sequence[str]], Sequence[Mapping[str, Any]]
        ],
        evidence_level: EvidenceLevel,
        ai_model: str,
        prompt_version: str,
        collector_version: str,
        official_hosts: frozenset[str],
        evidence_blocks: Sequence[str],
    ) -> None:
        if evidence_level not in {
            "ai_official_extract",
            "ai_multi_source",
            "ai_no_evidence",
        }:
            raise ValueError("invalid AI pricing evidence level")
        self.extractor = extractor
        self.evidence_level = evidence_level
        self.ai_model = ai_model
        self.prompt_version = prompt_version
        self.collector_version = collector_version
        self.official_hosts = official_hosts
        self.evidence_blocks = tuple(evidence_blocks)

    def collect(
        self, model: PriceableModel
    ) -> tuple[CollectedPriceCandidate, ...]:
        raw_rows = self.extractor(model, self.evidence_blocks)
        candidates: list[CollectedPriceCandidate] = []
        for raw in raw_rows:
            parsed = AiPriceExtraction.model_validate(raw)
            source_urls = tuple(str(url) for url in parsed.source_urls)
            source_url = source_urls[0] if source_urls else None
            conditions = dict(parsed.conditions)
            condition_region = conditions.get("region")
            if condition_region is not None and (
                model.pricing_region is None
                or condition_region != model.pricing_region
            ):
                raise ValueError("AI pricing region does not match endpoint")
            candidate = CollectedPriceCandidate(
                provider_id=model.provider_id,
                official_model_id=(
                    model.official_model_id or model.model_key
                ),
                pricing_region=model.pricing_region,
                capability=parsed.capability,
                unit_key=parsed.unit_key,
                unit_size=parsed.unit_size,
                conditions=conditions,
                original_currency=parsed.currency,
                original_price=parsed.price_decimal,
                rmb_cost=parsed.rmb_cost,
                source_url=source_url,
                evidence_level=self.evidence_level,
                evidence_excerpt=parsed.evidence_excerpt,
                collector_version=self.collector_version,
                ai_model=self.ai_model,
                prompt_version=self.prompt_version,
                confidence=parsed.confidence_decimal,
            )
            candidate.validate(self.official_hosts)
            candidates.append(candidate)
        return tuple(candidates)


class OfficialPageAiCollector:
    """Fetch a bounded official page and ask AI to normalize its evidence."""

    def __init__(
        self,
        *,
        page_urls: Mapping[str, str],
        official_hosts: Mapping[str, frozenset[str]],
        fetcher: Callable[[str], str],
        extractor: Callable[
            [PriceableModel, Sequence[str]], Sequence[Mapping[str, Any]]
        ],
        ai_model: str,
        max_evidence_chars: int = 30_000,
    ) -> None:
        self.page_urls = dict(page_urls)
        self.official_hosts = dict(official_hosts)
        self.fetcher = fetcher
        self.extractor = extractor
        self.ai_model = ai_model
        self.max_evidence_chars = max_evidence_chars

    def collect(
        self, model: PriceableModel
    ) -> tuple[CollectedPriceCandidate, ...]:
        url = self.page_urls.get(model.provider_id)
        if not url:
            return ()
        parsed = urlparse(url)
        hosts = self.official_hosts.get(model.provider_id, frozenset())
        if parsed.scheme != "https" or parsed.hostname not in hosts:
            raise ValueError("untrusted official pricing page")
        content = self.fetcher(url)[: self.max_evidence_chars]
        if not content.strip():
            return ()
        return StructuredAiCollector(
            extractor=self.extractor,
            evidence_level="ai_official_extract",
            ai_model=self.ai_model,
            prompt_version="official-page-extract-v1",
            collector_version="official-page-ai-v1",
            official_hosts=hosts,
            evidence_blocks=(f"SOURCE_URL={url}\nCONTENT={content}",),
        ).collect(model)
