"""Authoritative Bot-to-Agent configuration context aggregation."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import (
    BotConfigurationContext,
    BotConfigurationTarget,
    ConfigurationReadiness,
    DclawConfigurationContext,
    OmnichannelBotSnapshot,
    OmnichannelBotSummary,
)
from .upstreams import UpstreamError, UpstreamNotFoundError
from .upstreams.dclaw import DclawClient
from .upstreams.omnichannel import OmnichannelClient


class BotNotFoundError(KeyError):
    pass


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _readiness(
    missing_items: list[str],
    *,
    unavailable_code: str | None = None,
) -> ConfigurationReadiness:
    missing = _unique(missing_items)
    status = "unavailable" if unavailable_code else "ready" if not missing else "not_ready"
    return ConfigurationReadiness(
        status=status,
        ready=status == "ready",
        missing_items=missing,
        code=unavailable_code,
    )


def _target(
    bot: OmnichannelBotSummary,
    dclaw: DclawConfigurationContext | None,
    *,
    unavailable_code: str | None = None,
) -> BotConfigurationTarget:
    missing = list(bot.readiness.missing_items)
    if dclaw is None:
        if not bot.agent_id:
            missing.append("agent_bound")
        if not bot.dclaw.base_url:
            missing.append("dclaw_location_configured")
    else:
        missing.extend(dclaw.readiness.missing_items)
    return BotConfigurationTarget(
        bot_id=bot.bot_id,
        bot_name=bot.bot_name,
        enabled=bot.enabled,
        bound_agent_id=bot.agent_id,
        agent_profile_id=dclaw.agent_profile_id if dclaw else None,
        openapi_publication_id=dclaw.publication_id if dclaw else None,
        openapi_public_id=dclaw.openapi_public_id if dclaw else None,
        knowledge_base_id=dclaw.knowledge_base_id if dclaw else None,
        readiness=_readiness(missing, unavailable_code=unavailable_code),
    )


class ConfigurationContextService:
    def __init__(self, *, omnichannel: OmnichannelClient, dclaw: DclawClient) -> None:
        self._omnichannel = omnichannel
        self._dclaw = dclaw

    def list_bots(
        self,
        *,
        correlation_id: str | None = None,
    ) -> list[BotConfigurationTarget]:
        request_id = correlation_id or uuid.uuid4().hex
        bots = self._omnichannel.list_bots(correlation_id=request_id)
        keys = {
            (bot.dclaw.base_url, bot.agent_id)
            for bot in bots
            if bot.dclaw.base_url and bot.agent_id
        }
        contexts: dict[tuple[str, str], DclawConfigurationContext] = {}
        failures: dict[tuple[str, str], str] = {}
        if keys:
            with ThreadPoolExecutor(max_workers=min(8, len(keys))) as executor:
                futures = {
                    executor.submit(
                        self._dclaw.get_context,
                        base_url,
                        agent_id,
                        correlation_id=request_id,
                    ): (base_url, agent_id)
                    for base_url, agent_id in keys
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        contexts[key] = future.result()
                    except UpstreamError as exc:
                        failures[key] = exc.code

        return [
            _target(
                bot,
                contexts.get((bot.dclaw.base_url, bot.agent_id)),
                unavailable_code=failures.get((bot.dclaw.base_url, bot.agent_id)),
            )
            for bot in bots
        ]

    def get(
        self,
        bot_id: str,
        *,
        correlation_id: str | None = None,
    ) -> BotConfigurationContext:
        request_id = correlation_id or uuid.uuid4().hex
        try:
            snapshot = self._omnichannel.get_bot_snapshot(
                bot_id,
                correlation_id=request_id,
            )
        except UpstreamNotFoundError as exc:
            raise BotNotFoundError(bot_id) from exc
        dclaw_context: DclawConfigurationContext | None = None
        unavailable_code: str | None = None
        if snapshot.agent.agent_id and snapshot.agent.dclaw.base_url:
            try:
                dclaw_context = self._dclaw.get_context(
                    snapshot.agent.dclaw.base_url,
                    snapshot.agent.agent_id,
                    correlation_id=request_id,
                )
            except UpstreamError as exc:
                unavailable_code = exc.code

        summary = OmnichannelBotSummary(
            bot_id=snapshot.bot.bot_id,
            bot_name=snapshot.bot.bot_name,
            enabled=snapshot.bot.enabled,
            agent_id=snapshot.agent.agent_id,
            agent_name=snapshot.agent.agent_name,
            dclaw=snapshot.agent.dclaw,
            readiness=snapshot.readiness,
            configuration_digest=snapshot.digests.get("snapshot", ""),
        )
        target = _target(summary, dclaw_context, unavailable_code=unavailable_code)
        return BotConfigurationContext(
            **target.model_dump(),
            agent_type=dclaw_context.agent_type if dclaw_context else None,
            source_version=dclaw_context.source_version if dclaw_context else None,
            flow_machine=snapshot.flow_machine,
            tags=snapshot.tags,
        )
