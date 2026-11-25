"""AgentScope 2/ReMe 0.4 adapter preserving the existing memory files."""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Callable

from agentscope.credential import OpenAICredential
from agentscope.embedding import OpenAIEmbeddingModel
from agentscope.message import TextBlock
from agentscope.middleware._longterm_memory._reme._config import (
    _build_reme_app_config,
)
from agentscope.tool import ToolResponse
from reme import ReMe


class ReMeV2Adapter:
    """Expose the old manager contract through ReMe's supported 0.4 jobs."""

    def __init__(
        self,
        working_dir: str,
        model_factory: Callable,
        embedding_config: dict,
        rebuild_index: bool,
    ) -> None:
        self.working_dir = Path(working_dir)
        self.model_factory = model_factory
        self.embedding_config = embedding_config
        self.rebuild_index = rebuild_index
        self._app: ReMe | None = None
        self._started = False
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            embedding = self._embedding_model()
            config = _build_reme_app_config(
                workspace_dir=str(self.working_dir),
                embedding_dimensions=(
                    embedding.dimensions if embedding is not None else None
                ),
            )
            # DClaw already schedules its own memory consolidation pass.
            config["jobs"].pop("dream_cron", None)
            app = ReMe(**config)
            await app.update_component(
                "as_llm", "default", model=self.model_factory(),
            )
            if embedding is not None:
                await app.update_component(
                    "as_embedding", "default", model=embedding,
                )
            await app.start()
            try:
                if self.rebuild_index:
                    response = await app.run_job("reindex")
                    if not response.success:
                        raise RuntimeError("ReMe index rebuild failed")
            except BaseException:
                await app.close()
                raise
            self._app = app
            self._started = True

    def _embedding_model(self) -> OpenAIEmbeddingModel | None:
        cfg = self.embedding_config
        if not cfg.get("base_url") or not cfg.get("model_name"):
            return None
        if cfg.get("backend") != "openai":
            raise ValueError("ReMe 0.4 embedding backend is not supported")
        return OpenAIEmbeddingModel(
            credential=OpenAICredential(
                api_key=cfg.get("api_key") or "",
                base_url=cfg["base_url"],
            ),
            model=cfg["model_name"],
            dimensions=cfg.get("dimensions"),
            pass_dimensions=bool(cfg.get("use_dimensions")),
        )

    async def close(self) -> bool:
        if self._app is not None:
            await self._app.close()
        self._app = None
        self._started = False
        return True

    async def memory_search(
        self, query: str, max_results: int = 5, min_score: float = 0.1,
    ) -> ToolResponse:
        if not self._started or self._app is None:
            raise RuntimeError("ReMe memory search requested before start")
        response = await self._app.run_job(
            "search", query=query, limit=max_results, min_score=min_score,
        )
        if not response.success:
            raise RuntimeError("ReMe memory search failed")
        results = self._search_legacy_files(query, max_results)
        for item in response.metadata.get("results", []):
            if isinstance(item, dict) and item.get("text"):
                path = item.get("path", "")
                results.append(f"{path}: {item['text']}")
        return ToolResponse(
            content=[
                TextBlock(type="text", text="\n\n".join(results[:max_results]))
            ],
        )

    def _search_legacy_files(self, query: str, limit: int) -> list[str]:
        # ReMe 0.4 indexes daily/digest cards; legacy MEMORY.md remains readable.
        terms = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", query.lower())
        if not terms:
            return []
        paths = [self.working_dir / "MEMORY.md"]
        paths.extend(sorted((self.working_dir / "memory").glob("*.md")))
        matches: list[tuple[int, str]] = []
        for path in paths[:501]:
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            with path.open(encoding="utf-8", errors="replace") as source:
                for line_number, line in enumerate(source, 1):
                    candidate = line.strip()
                    if not candidate:
                        continue
                    score = sum(term in candidate.lower() for term in terms)
                    if score:
                        matches.append(
                            (score, f"{path.relative_to(self.working_dir)}:{line_number}: {candidate[:400]}")
                        )
        matches.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in matches[:limit]]

    async def summary_memory(self, messages: list, **_kwargs) -> str:
        if not self._started or self._app is None:
            raise RuntimeError("ReMe summary requested before start")
        response = await self._app.run_job(
            "auto_memory",
            messages=[msg.model_dump(mode="json") for msg in messages],
            session_id=uuid.uuid4().hex,
        )
        if not response.success:
            raise RuntimeError("ReMe auto_memory failed")
        return str(response.answer or "")
