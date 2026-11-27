# -*- coding: utf-8 -*-
"""Embedding protocol adapter tests for Mindspace knowledge search."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from qwenpaw.mindspace.embeddings import (
    EmbeddingConfig,
    EmbeddingError,
    MindspaceEmbedder,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_openai_compatible_embedding_request(monkeypatch):
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured.update(
            url=url,
            json=json,
            headers=headers,
            timeout=timeout,
        )
        return _Response(
            {"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
        )

    monkeypatch.setattr("qwenpaw.mindspace.embeddings.httpx.post", fake_post)
    embedder = MindspaceEmbedder(
        EmbeddingConfig(
            api_key="sk-test",
            base_url="https://example.com/v1",
            model_name="text-embedding-v4",
            dimensions=1024,
            use_dimensions=True,
        ),
    )

    assert embedder.embed_query("hello") == [0.1, 0.2]
    assert captured["url"] == "https://example.com/v1/embeddings"
    assert captured["json"] == {
        "model": "text-embedding-v4",
        "input": ["hello"],
        "dimensions": 1024,
    }


def test_dashscope_multimodal_text_embedding_request(monkeypatch):
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured.update(url=url, json=json)
        return _Response(
            {
                "output": {
                    "embeddings": [
                        {"index": 1, "embedding": [0.3, 0.4]},
                        {"index": 0, "embedding": [0.1, 0.2]},
                    ],
                },
            },
        )

    monkeypatch.setattr("qwenpaw.mindspace.embeddings.httpx.post", fake_post)
    endpoint = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    )
    embedder = MindspaceEmbedder(
        EmbeddingConfig(
            api_key="sk-test",
            base_url=endpoint,
            model_name="qwen3-vl-embedding",
            dimensions=1024,
            use_dimensions=True,
            protocol="dashscope_multimodal",
        ),
    )

    vectors = embedder.embed_documents(["first", "second"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["url"] == endpoint
    assert captured["json"] == {
        "model": "qwen3-vl-embedding",
        "input": {
            "contents": [{"text": "first"}, {"text": "second"}],
        },
        "parameters": {"dimension": 1024},
    }


def test_embedding_http_error_exposes_provider_message(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(
            400,
            request=request,
            json={
                "code": "BadRequest",
                "message": (
                    "dimension must be one of [64, 128, 256, 512, 768], "
                    "got 1024"
                ),
            },
        )

    monkeypatch.setattr("qwenpaw.mindspace.embeddings.httpx.post", fake_post)
    embedder = MindspaceEmbedder(
        EmbeddingConfig(
            api_key="sk-test",
            base_url="https://example.com/embedding",
            model_name="tongyi-embedding-vision-flash-2026-03-06",
            dimensions=1024,
            use_dimensions=True,
            protocol="dashscope_multimodal",
        ),
    )

    with pytest.raises(
        EmbeddingError,
        match="dimension must be one of",
    ):
        embedder.embed_query("hello")


def test_provider_model_builds_native_dashscope_client():
    provider = SimpleNamespace(
        id="dashscope",
        api_key="sk-provider",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model = SimpleNamespace(
        id="qwen3-vl-embedding",
        embedding_dimensions=1024,
        embedding_protocol="dashscope_multimodal",
        embedding_base_url="https://native.example/embedding",
    )

    embedder = MindspaceEmbedder.from_provider_model(provider, model)

    assert embedder.config.api_key == "sk-provider"
    assert embedder.config.base_url == "https://native.example/embedding"
    assert embedder.config.protocol == "dashscope_multimodal"
    assert embedder.storage_key == "dashscope/qwen3-vl-embedding"


def test_provider_model_derives_native_endpoint_from_dashscope_region():
    provider = SimpleNamespace(
        id="dashscope",
        api_key="sk-provider",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        custom_headers={"X-Workspace": "knowledge"},
    )
    model = SimpleNamespace(
        id="qwen3-vl-embedding",
        embedding_dimensions=1024,
        embedding_protocol="dashscope_multimodal",
        embedding_base_url=None,
    )

    embedder = MindspaceEmbedder.from_provider_model(provider, model)

    assert embedder.config.base_url == (
        "https://dashscope-intl.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    )
    assert embedder.config.custom_headers == {"X-Workspace": "knowledge"}


def test_embedding_batches_run_with_bounded_concurrency_and_keep_order(
    monkeypatch,
):
    embedder = MindspaceEmbedder(
        EmbeddingConfig(
            base_url="https://example.com/v1",
            model_name="text-embedding-v4",
            max_batch_size=2,
            max_concurrency=2,
        )
    )
    lock = threading.Lock()
    state = {"active": 0, "max_active": 0}
    progress = []

    def fake_embed(batch):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        try:
            time.sleep(0.04)
            return [[float(value)] for value in batch]
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(embedder, "_embed", fake_embed)

    vectors = embedder.embed_documents_with_progress(
        ["1", "2", "3", "4"],
        progress_callback=lambda completed, total: progress.append(
            (completed, total)
        ),
    )

    assert vectors == [[1.0], [2.0], [3.0], [4.0]]
    assert state["max_active"] == 2
    assert progress[-1] == (2, 2)
