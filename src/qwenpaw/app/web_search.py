# -*- coding: utf-8 -*-
"""Platform-level web-search configuration and Aliyun IQS integration."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from ..constant import WORKING_DIR
from ..security.secret_store import (
    PROVIDER_SECRET_FIELDS,
    decrypt_dict_fields,
    encrypt_dict_fields,
)

logger = logging.getLogger(__name__)

MASKED_SECRET = "********"
ALIYUN_IQS_PROVIDER_ID = "aliyun_iqs"
ALIYUN_IQS_ENGINE = "LiteAdvanced"
ALIYUN_IQS_ENDPOINT = "https://cloud-iqs.aliyuncs.com/search/unified"
ALIYUN_IQS_READ_PAGE_ENDPOINT = (
    "https://cloud-iqs.aliyuncs.com/readpage/basic"
)
DEFAULT_CONFIG_PATH = Path(WORKING_DIR) / "web_search" / "aliyun_iqs.json"

FRESHNESS_TO_IQS = {
    "no_limit": "NoLimit",
    "day": "OneDay",
    "week": "OneWeek",
    "month": "OneMonth",
    "year": "OneYear",
}


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _bounded_float(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _normalize_endpoint(value: Any) -> str:
    endpoint = _clean(value) or ALIYUN_IQS_ENDPOINT
    endpoint = endpoint.rstrip("/")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "cloud-iqs.aliyuncs.com"
        or parsed.path.rstrip("/") != "/search/unified"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "IQS endpoint must be https://cloud-iqs.aliyuncs.com/search/unified",
        )
    return ALIYUN_IQS_ENDPOINT


def normalize_freshness(value: Any) -> str:
    normalized = _clean(value).lower().replace("-", "_") or "no_limit"
    aliases = {
        "nolimit": "no_limit",
        "one_day": "day",
        "oneday": "day",
        "one_week": "week",
        "oneweek": "week",
        "one_month": "month",
        "onemonth": "month",
        "one_year": "year",
        "oneyear": "year",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in FRESHNESS_TO_IQS:
        allowed = ", ".join(FRESHNESS_TO_IQS)
        raise ValueError(f"Unsupported freshness '{value}'. Use one of: {allowed}.")
    return normalized


def normalize_public_url(value: Any) -> str:
    """Validate a URL before asking the external parsing service to read it."""
    url = _clean(value).split("#", 1)[0]
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").strip("[]").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Web page URL must be a public http:// or https:// URL.")
    if hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("Local and private network URLs cannot be parsed.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Local and private network URLs cannot be parsed.")
    return url


@dataclass
class WebSearchConfig:
    """Shared configuration for the Aliyun IQS web-search provider."""

    enabled: bool = False
    api_key: str = ""
    endpoint: str = ALIYUN_IQS_ENDPOINT
    engine_type: str = ALIYUN_IQS_ENGINE
    default_max_results: int = 5
    timeout_seconds: float = 8.0
    cache_ttl_seconds: int = 300
    provider: str = ALIYUN_IQS_PROVIDER_ID
    updated_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.provider = ALIYUN_IQS_PROVIDER_ID
        self.api_key = _clean(self.api_key)
        self.endpoint = _normalize_endpoint(self.endpoint)
        self.engine_type = _clean(self.engine_type) or ALIYUN_IQS_ENGINE
        if self.engine_type != ALIYUN_IQS_ENGINE:
            raise ValueError("The first release only supports IQS LiteAdvanced.")
        self.default_max_results = _bounded_int(
            self.default_max_results,
            default=5,
            minimum=1,
            maximum=10,
        )
        self.timeout_seconds = _bounded_float(
            self.timeout_seconds,
            default=8.0,
            minimum=5.0,
            maximum=30.0,
        )
        self.cache_ttl_seconds = _bounded_int(
            self.cache_ttl_seconds,
            default=300,
            minimum=0,
            maximum=3600,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.configured)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "WebSearchConfig":
        raw = raw or {}
        return cls(
            enabled=bool(raw.get("enabled", False)),
            api_key=str(raw.get("api_key") or ""),
            endpoint=str(raw.get("endpoint") or ALIYUN_IQS_ENDPOINT),
            engine_type=str(raw.get("engine_type") or ALIYUN_IQS_ENGINE),
            default_max_results=raw.get("default_max_results", 5),
            timeout_seconds=raw.get("timeout_seconds", 8.0),
            cache_ttl_seconds=raw.get("cache_ttl_seconds", 300),
            updated_at=str(raw.get("updated_at") or _utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "api_key": self.api_key,
            "endpoint": self.endpoint,
            "engine_type": self.engine_type,
            "default_max_results": self.default_max_results,
            "timeout_seconds": self.timeout_seconds,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "updated_at": self.updated_at,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "api_key": MASKED_SECRET if self.api_key else "",
            "endpoint": self.endpoint,
            "engine_type": self.engine_type,
            "default_max_results": self.default_max_results,
            "timeout_seconds": self.timeout_seconds,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "configured": self.configured,
            "available": self.available,
            "updated_at": self.updated_at,
        }


class WebSearchConfigStore:
    """Encrypted JSON-backed storage for the shared search provider."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or DEFAULT_CONFIG_PATH)

    def get_config(self) -> WebSearchConfig:
        if not self.path.is_file():
            return WebSearchConfig()
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            if not isinstance(raw, dict):
                raw = {}
            raw = decrypt_dict_fields(raw, PROVIDER_SECRET_FIELDS)
            return WebSearchConfig.from_dict(raw)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Failed to load web search config: %s", exc)
            return WebSearchConfig()

    def save_config(self, config: WebSearchConfig) -> WebSearchConfig:
        config.updated_at = _utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        data = encrypt_dict_fields(config.to_dict(), PROVIDER_SECRET_FIELDS)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            "utf-8",
        )
        try:
            temporary_path.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary_path, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return config

    def config_from_payload(self, payload: dict[str, Any]) -> WebSearchConfig:
        existing = self.get_config()
        api_key = payload.get("api_key")
        if api_key in {None, MASKED_SECRET}:
            api_key = existing.api_key
        return WebSearchConfig(
            enabled=bool(payload.get("enabled", False)),
            api_key=str(api_key or ""),
            endpoint=str(payload.get("endpoint") or ALIYUN_IQS_ENDPOINT),
            engine_type=str(payload.get("engine_type") or ALIYUN_IQS_ENGINE),
            default_max_results=payload.get("default_max_results", 5),
            timeout_seconds=payload.get("timeout_seconds", 8.0),
            cache_ttl_seconds=payload.get("cache_ttl_seconds", 300),
        )

    def update_config(self, payload: dict[str, Any]) -> WebSearchConfig:
        config = self.config_from_payload(payload)
        if config.enabled and not config.configured:
            raise ValueError("Configure an IQS API Key before enabling web search.")
        return self.save_config(config)


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    published_at: str = ""
    content: str = ""
    source: str = ""
    score: float | None = None


@dataclass(frozen=True)
class WebSearchResponse:
    query: str
    results: tuple[WebSearchResult, ...]
    request_id: str = ""
    search_time_ms: int | None = None
    provider: str = ALIYUN_IQS_PROVIDER_ID
    engine_type: str = ALIYUN_IQS_ENGINE
    cached: bool = False


@dataclass(frozen=True)
class WebPageResponse:
    url: str
    final_url: str
    title: str = ""
    markdown: str = ""
    text: str = ""
    content_type: str = ""
    published_at: str = ""
    last_modified: str = ""
    author: str = ""
    site_name: str = ""
    language: str = ""
    page_type: str = ""
    request_id: str = ""
    pdf_parsed: bool = False
    provider: str = ALIYUN_IQS_PROVIDER_ID

    @property
    def content(self) -> str:
        return self.markdown or self.text


class WebSearchError(RuntimeError):
    """Readable provider or configuration error."""


def _safe_text(value: Any, *, limit: int) -> str:
    text = _clean(value).replace("\x00", "")
    if len(text) > limit:
        return f"{text[:limit]}…"
    return text


def _safe_url(value: Any) -> str:
    url = _clean(value)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _provider_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        code = _clean(
            body.get("code")
            or body.get("errorCode")
            or body.get("Code")
        )
        message = _clean(
            body.get("message")
            or body.get("errorMessage")
            or body.get("Message")
        )
        if code or message:
            suffix = " ".join(part for part in (code, message) if part)
            return f"IQS request failed: HTTP {response.status_code} {suffix}"
    text = _safe_text(response.text, limit=500)
    if text:
        return f"IQS request failed: HTTP {response.status_code} {text}"
    return f"IQS request failed: HTTP {response.status_code}"


class AliyunIQSClient:
    """Small direct HTTP adapter for IQS UnifiedSearch."""

    def __init__(
        self,
        config: WebSearchConfig,
        *,
        http_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config = config
        self._http_client_factory = (
            http_client_factory or self._default_http_client
        )

    def _default_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds, connect=5.0),
            follow_redirects=False,
        )

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        freshness: str,
        include_content: bool,
    ) -> WebSearchResponse:
        if not self.config.configured:
            raise WebSearchError("Aliyun IQS API Key is not configured.")

        normalized_query = _clean(query)
        if not normalized_query:
            raise ValueError("Search query must not be empty.")
        if len(normalized_query) > 500:
            raise ValueError("Search query must be 500 characters or fewer.")
        normalized_freshness = normalize_freshness(freshness)
        result_limit = _bounded_int(
            max_results,
            default=self.config.default_max_results,
            minimum=1,
            maximum=10,
        )
        payload = {
            "query": normalized_query,
            "engineType": ALIYUN_IQS_ENGINE,
            "timeRange": FRESHNESS_TO_IQS[normalized_freshness],
            "contents": {
                "mainText": bool(include_content),
                "markdownText": False,
                "summary": False,
                "rerankScore": True,
            },
            "advancedParams": {"numResults": str(result_limit)},
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            async with self._http_client_factory() as client:
                response = await self._post_with_retry(
                    client,
                    endpoint=self.config.endpoint,
                    headers=headers,
                    payload=payload,
                    timeout_seconds=self.config.timeout_seconds,
                )
        except httpx.TimeoutException as exc:
            raise WebSearchError(
                f"IQS request timed out after {self.config.timeout_seconds:g}s.",
            ) from exc
        except httpx.RequestError as exc:
            raise WebSearchError(
                f"IQS request failed: {exc.__class__.__name__}: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise WebSearchError(_provider_error_detail(response))
        try:
            body = response.json()
        except ValueError as exc:
            raise WebSearchError("IQS returned an invalid JSON response.") from exc
        if not isinstance(body, dict):
            raise WebSearchError("IQS returned an unexpected response shape.")
        return self._parse_response(normalized_query, body)

    async def read_page(
        self,
        url: str,
        *,
        max_age_seconds: int,
    ) -> WebPageResponse:
        """Parse one public URL with IQS ReadPageBasic."""
        if not self.config.configured:
            raise WebSearchError("Aliyun IQS API Key is not configured.")
        normalized_url = normalize_public_url(url)
        payload = {
            "url": normalized_url,
            "pageTimeout": 8000,
            "formats": ["markdown", "text"],
            "maxAge": _bounded_int(
                max_age_seconds,
                default=300,
                minimum=0,
                maximum=86400,
            ),
            "readability": {"readabilityMode": "normal"},
            "excludeAllImages": True,
            "excludeAllLinks": False,
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with self._http_client_factory() as client:
                response = await self._post_with_retry(
                    client,
                    endpoint=ALIYUN_IQS_READ_PAGE_ENDPOINT,
                    headers=headers,
                    payload=payload,
                    timeout_seconds=max(15.0, self.config.timeout_seconds),
                )
        except httpx.TimeoutException as exc:
            raise WebSearchError("IQS ReadPageBasic request timed out.") from exc
        except httpx.RequestError as exc:
            raise WebSearchError(
                f"IQS ReadPageBasic request failed: "
                f"{exc.__class__.__name__}: {exc}",
            ) from exc
        if response.status_code >= 400:
            raise WebSearchError(_provider_error_detail(response))
        try:
            body = response.json()
        except ValueError as exc:
            raise WebSearchError(
                "IQS ReadPageBasic returned an invalid JSON response.",
            ) from exc
        if not isinstance(body, dict):
            raise WebSearchError(
                "IQS ReadPageBasic returned an unexpected response shape.",
            )
        return self._parse_page_response(normalized_url, body)

    async def _post_with_retry(
        self,
        client: Any,
        *,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> httpx.Response:
        """Retry one transient HTTP response without retrying timeouts."""
        response: httpx.Response | None = None
        transient_statuses = {429, 500, 502, 503, 504}
        for attempt in range(2):
            response = await client.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            if response.status_code not in transient_statuses or attempt > 0:
                return response
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = 0.25
            await asyncio.sleep(max(0.0, min(delay, 2.0)))
        assert response is not None
        return response

    @staticmethod
    def _parse_page_response(
        url: str,
        body: dict[str, Any],
    ) -> WebPageResponse:
        raw_data = body.get("data")
        data = raw_data if isinstance(raw_data, dict) else body
        redirected_url = _safe_url(data.get("redirectedUrl")) or url
        markdown = _safe_text(data.get("markdown"), limit=50000)
        text = _safe_text(data.get("text"), limit=50000)
        if not markdown and not text:
            text = _safe_text(data.get("html"), limit=20000)
        return WebPageResponse(
            url=url,
            final_url=redirected_url,
            title=_safe_text(data.get("title"), limit=500),
            markdown=markdown,
            text=text,
            content_type=_safe_text(data.get("contentType"), limit=200),
            published_at=_safe_text(data.get("publishedDate"), limit=100),
            last_modified=_safe_text(data.get("lastModified"), limit=100),
            author=_safe_text(data.get("author"), limit=300),
            site_name=_safe_text(data.get("siteName"), limit=300),
            language=_safe_text(data.get("language"), limit=100),
            page_type=_safe_text(data.get("pageType"), limit=100),
            request_id=_safe_text(
                body.get("requestId") or data.get("requestId"),
                limit=200,
            ),
            pdf_parsed=bool(data.get("pdfParse", False)),
        )

    @staticmethod
    def _parse_response(query: str, body: dict[str, Any]) -> WebSearchResponse:
        raw_items = body.get("pageItems")
        if not isinstance(raw_items, list):
            raw_items = []
        results: list[WebSearchResult] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            url = _safe_url(item.get("link"))
            if not url:
                continue
            raw_score = item.get("rerankScore")
            try:
                score = float(raw_score) if raw_score is not None else None
            except (TypeError, ValueError):
                score = None
            results.append(
                WebSearchResult(
                    title=_safe_text(item.get("title"), limit=300)
                    or "Untitled result",
                    url=url,
                    snippet=_safe_text(item.get("snippet"), limit=1500),
                    published_at=_safe_text(
                        item.get("publishedTime"),
                        limit=100,
                    ),
                    content=_safe_text(item.get("mainText"), limit=3000),
                    source=_safe_text(
                        item.get("hostname") or urlparse(url).netloc,
                        limit=200,
                    ),
                    score=score,
                )
            )

        search_info = body.get("searchInformation")
        search_time: int | None = None
        if isinstance(search_info, dict):
            try:
                search_time = int(search_info.get("searchTime"))
            except (TypeError, ValueError):
                search_time = None
        return WebSearchResponse(
            query=query,
            results=tuple(results),
            request_id=_safe_text(body.get("requestId"), limit=200),
            search_time_ms=search_time,
        )


class _RequestPacer:
    """Single-process request pacing for the default IQS 10 QPS quota."""

    def __init__(self, requests_per_second: float = 10.0) -> None:
        self._interval = 1.0 / max(requests_per_second, 1.0)
        self._lock = asyncio.Lock()
        self._last_dispatched = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            remaining = self._interval - (now - self._last_dispatched)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_dispatched = time.monotonic()


class WebSearchService:
    """Shared provider service with bounded caching and request pacing."""

    def __init__(
        self,
        store: WebSearchConfigStore | None = None,
        *,
        client_factory: Callable[[WebSearchConfig], AliyunIQSClient] | None = None,
    ) -> None:
        self.store = store or WebSearchConfigStore()
        self._client_factory = client_factory or AliyunIQSClient
        self._cache: dict[tuple[Any, ...], tuple[float, WebSearchResponse]] = {}
        self._cache_lock = asyncio.Lock()
        self._pacer = _RequestPacer()

    async def search(
        self,
        query: str,
        *,
        max_results: int | None = None,
        freshness: str = "no_limit",
        include_content: bool = False,
        config: WebSearchConfig | None = None,
        require_enabled: bool = True,
        use_cache: bool = True,
    ) -> WebSearchResponse:
        resolved = config or self.store.get_config()
        if require_enabled and not resolved.enabled:
            raise WebSearchError("Public web search is disabled by the administrator.")
        if not resolved.configured:
            raise WebSearchError("Aliyun IQS API Key is not configured.")

        normalized_query = _clean(query)
        normalized_freshness = normalize_freshness(freshness)
        resolved_limit = _bounded_int(
            max_results,
            default=resolved.default_max_results,
            minimum=1,
            maximum=10,
        )
        cache_key = (
            normalized_query.casefold(),
            normalized_freshness,
            resolved_limit,
            bool(include_content),
        )
        if use_cache and resolved.cache_ttl_seconds > 0:
            cached = await self._get_cached(cache_key, resolved.cache_ttl_seconds)
            if cached is not None:
                return WebSearchResponse(
                    query=cached.query,
                    results=cached.results,
                    request_id=cached.request_id,
                    search_time_ms=cached.search_time_ms,
                    provider=cached.provider,
                    engine_type=cached.engine_type,
                    cached=True,
                )

        await self._pacer.wait()
        response = await self._client_factory(resolved).search(
            normalized_query,
            max_results=resolved_limit,
            freshness=normalized_freshness,
            include_content=include_content,
        )
        if use_cache and resolved.cache_ttl_seconds > 0:
            async with self._cache_lock:
                self._cache[cache_key] = (time.monotonic(), response)
                if len(self._cache) > 256:
                    oldest = min(self._cache, key=lambda key: self._cache[key][0])
                    self._cache.pop(oldest, None)
        return response

    async def _get_cached(
        self,
        cache_key: tuple[Any, ...],
        ttl_seconds: int,
    ) -> WebSearchResponse | None:
        async with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is None:
                return None
            created_at, response = cached
            if time.monotonic() - created_at > ttl_seconds:
                self._cache.pop(cache_key, None)
                return None
            return response

    async def read_page(
        self,
        url: str,
        *,
        config: WebSearchConfig | None = None,
        require_enabled: bool = True,
    ) -> WebPageResponse:
        resolved = config or self.store.get_config()
        if require_enabled and not resolved.enabled:
            raise WebSearchError("Public web access is disabled by the administrator.")
        if not resolved.configured:
            raise WebSearchError("Aliyun IQS API Key is not configured.")
        await self._pacer.wait()
        return await self._client_factory(resolved).read_page(
            url,
            max_age_seconds=resolved.cache_ttl_seconds,
        )

    async def clear_cache(self) -> None:
        async with self._cache_lock:
            self._cache.clear()


_default_service: WebSearchService | None = None


def get_web_search_service() -> WebSearchService:
    global _default_service  # noqa: PLW0603
    if _default_service is None:
        _default_service = WebSearchService()
    return _default_service


def reset_web_search_service() -> None:
    global _default_service  # noqa: PLW0603
    _default_service = None
