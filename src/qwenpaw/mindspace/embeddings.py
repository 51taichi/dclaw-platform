# -*- coding: utf-8 -*-
"""Embedding helpers for Mindspace semantic search."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..config.config import load_agent_config
from ..constant import EnvVarLoader


class EmbeddingError(RuntimeError):
    """Raised when semantic embedding is configured but cannot be produced."""


class EmbeddingBackend(Protocol):
    model_name: str
    storage_key: str

    def is_configured(self) -> bool:
        """Return whether this backend has enough configuration to run."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return vectors for document chunks."""

    def embed_query(self, text: str) -> list[float]:
        """Return a vector for a search query."""


@dataclass
class EmbeddingConfig:
    api_key: str = ""
    base_url: str = ""
    model_name: str = ""
    dimensions: int = 1024
    use_dimensions: bool = False
    max_input_length: int = 8192
    max_batch_size: int = 10
    max_concurrency: int = 2
    protocol: str = "openai_compatible"
    custom_headers: dict[str, str] = field(default_factory=dict)
    storage_key: str = ""


class MindspaceEmbedder:
    """Knowledge Embedding client with provider and legacy-config support."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config
        self.model_name = config.model_name
        self.storage_key = config.storage_key or config.model_name

    @classmethod
    def from_agent_config(cls, agent_id: str) -> "MindspaceEmbedder":
        provider_embedder = cls.from_active_provider()
        if provider_embedder is not None:
            return provider_embedder
        try:
            cfg = load_agent_config(
                agent_id,
            ).running.reme_light_memory_config.embedding_model_config
        except Exception:
            return cls.from_env()
        return cls(
            EmbeddingConfig(
                api_key=cfg.api_key or EnvVarLoader.get_str("EMBEDDING_API_KEY", ""),
                base_url=cfg.base_url or EnvVarLoader.get_str("EMBEDDING_BASE_URL", ""),
                model_name=(
                    cfg.model_name
                    or EnvVarLoader.get_str("EMBEDDING_MODEL_NAME", "")
                ),
                dimensions=cfg.dimensions,
                use_dimensions=cfg.use_dimensions,
                max_input_length=cfg.max_input_length,
                max_batch_size=cfg.max_batch_size,
                max_concurrency=EnvVarLoader.get_int(
                    "QWENPAW_KNOWLEDGE_EMBEDDING_CONCURRENCY",
                    2,
                    min_value=1,
                    max_value=8,
                ),
            )
        )

    @classmethod
    def from_active_provider(cls) -> "MindspaceEmbedder" | None:
        """Resolve the globally selected Embedding model from Model settings."""
        try:
            from ..providers.provider_manager import ProviderManager

            manager = ProviderManager.get_instance()
            slot = manager.get_active_embedding_model()
            if not slot:
                return None
            provider = manager.get_provider(slot.provider_id)
            if not provider or provider.disabled:
                return None
            model = next(
                (
                    item
                    for item in provider.models + provider.extra_models
                    if item.id == slot.model and item.model_type == "embedding"
                ),
                None,
            )
            if not model:
                return None
            return cls.from_provider_model(provider, model)
        except Exception:
            return None

    @classmethod
    def from_provider_model(cls, provider, model) -> "MindspaceEmbedder":
        """Build an Embedding client from provider and classified model data."""
        dimensions = int(model.embedding_dimensions or 1024)
        protocol = model.embedding_protocol or "openai_compatible"
        base_url = str(model.embedding_base_url or provider.base_url or "")
        if protocol == "dashscope_multimodal" and not model.embedding_base_url:
            base_url = cls._dashscope_multimodal_endpoint(base_url)
        return cls(
            EmbeddingConfig(
                api_key=str(provider.api_key or ""),
                base_url=base_url,
                model_name=str(model.id),
                dimensions=dimensions,
                use_dimensions=model.embedding_dimensions is not None,
                max_batch_size=10,
                max_concurrency=EnvVarLoader.get_int(
                    "QWENPAW_KNOWLEDGE_EMBEDDING_CONCURRENCY",
                    2,
                    min_value=1,
                    max_value=8,
                ),
                protocol=protocol,
                custom_headers=dict(
                    getattr(provider, "custom_headers", None) or {},
                ),
                storage_key=f"{provider.id}/{model.id}",
            ),
        )

    @classmethod
    def from_env(cls) -> "MindspaceEmbedder":
        return cls(
            EmbeddingConfig(
                api_key=EnvVarLoader.get_str("EMBEDDING_API_KEY", ""),
                base_url=EnvVarLoader.get_str("EMBEDDING_BASE_URL", ""),
                model_name=EnvVarLoader.get_str("EMBEDDING_MODEL_NAME", ""),
                max_concurrency=EnvVarLoader.get_int(
                    "QWENPAW_KNOWLEDGE_EMBEDDING_CONCURRENCY",
                    2,
                    min_value=1,
                    max_value=8,
                ),
            )
        )

    def is_configured(self) -> bool:
        return bool(self.config.base_url and self.config.model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents_with_progress(texts)

    def embed_documents_with_progress(
        self,
        texts: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        batch_size = max(1, int(self.config.max_batch_size or 10))
        batches = [
            texts[start : start + batch_size]
            for start in range(0, len(texts), batch_size)
        ]
        batch_results: list[list[list[float]] | None] = [None] * len(batches)
        worker_count = min(
            len(batches),
            max(1, int(self.config.max_concurrency or 1)),
        )
        completed = 0

        if worker_count == 1:
            for batch_index, batch in enumerate(batches):
                batch_results[batch_index] = self._embed(batch)
                completed += 1
                if progress_callback:
                    progress_callback(completed, len(batches))
        else:
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="knowledge-embedding",
            ) as executor:
                futures = {
                    executor.submit(self._embed, batch): batch_index
                    for batch_index, batch in enumerate(batches)
                }
                for future in as_completed(futures):
                    batch_results[futures[future]] = future.result()
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(batches))

        vectors: list[list[float]] = []
        for batch_result in batch_results:
            if batch_result is None:
                raise EmbeddingError("Embedding batch did not return a result.")
            vectors.extend(batch_result)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embed([text])
        if not vectors:
            raise EmbeddingError("Embedding API returned no query vector.")
        return vectors[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not self.is_configured():
            raise EmbeddingError("Embedding model is not configured.")
        trimmed = [self._trim_text(text) for text in texts]
        if self.config.protocol == "dashscope_multimodal":
            parameters: dict[str, object] = {}
            if self.config.use_dimensions and self.config.dimensions > 0:
                parameters["dimension"] = self.config.dimensions
            payload: dict[str, object] = {
                "model": self.config.model_name,
                "input": {
                    "contents": [{"text": text} for text in trimmed],
                },
            }
            if parameters:
                payload["parameters"] = parameters
        else:
            payload = {
                "model": self.config.model_name,
                "input": trimmed,
            }
            if self.config.use_dimensions and self.config.dimensions > 0:
                payload["dimensions"] = self.config.dimensions

        headers = {
            "Content-Type": "application/json",
            **self.config.custom_headers,
        }
        if self.config.api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        try:
            response = httpx.post(
                self._endpoint(),
                json=payload,
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            detail = self._http_error_detail(exc.response)
            raise EmbeddingError(
                "Embedding API request failed "
                f"({exc.response.status_code}): {detail}",
            ) from exc
        except Exception as exc:
            raise EmbeddingError(f"Embedding API request failed: {exc}") from exc

        if self.config.protocol == "dashscope_multimodal":
            output = raw.get("output") if isinstance(raw, dict) else None
            data = output.get("embeddings") if isinstance(output, dict) else None
        else:
            data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(data, list):
            raise EmbeddingError("Embedding API response missing data list.")

        vectors: list[list[float]] = []
        ordered_data = sorted(
            data,
            key=lambda item: (
                int(item.get("index", 0)) if isinstance(item, dict) else 0
            ),
        )
        for item in ordered_data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list):
                raise EmbeddingError(
                    "Embedding API response contains an invalid vector.",
                )
            try:
                vectors.append([float(value) for value in embedding])
            except (TypeError, ValueError) as exc:
                raise EmbeddingError(
                    "Embedding API vector contains a non-numeric value.",
                ) from exc
        if len(vectors) != len(texts):
            raise EmbeddingError(
                "Embedding API returned a different number of vectors.",
            )
        return vectors

    def _endpoint(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        if self.config.protocol == "dashscope_multimodal":
            return base_url
        if base_url.endswith("/embeddings"):
            return base_url
        return f"{base_url}/embeddings"

    @staticmethod
    def _dashscope_multimodal_endpoint(base_url: str) -> str:
        parsed = urlsplit(base_url.strip())
        if not parsed.scheme or not parsed.netloc:
            return base_url.strip().rstrip("/")
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                "/api/v1/services/embeddings/multimodal-embedding/"
                "multimodal-embedding",
                "",
                "",
            ),
        )

    @staticmethod
    def _http_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            code = str(payload.get("code") or "").strip()
            message = str(payload.get("message") or "").strip()
            if code and message:
                return f"{code}: {message}"
            if message:
                return message
        text = response.text.strip()
        return text[:500] if text else response.reason_phrase

    def _trim_text(self, text: str) -> str:
        max_len = max(1, int(self.config.max_input_length or 8192))
        return text[:max_len]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
