"""FastAPI routes for the stable DClaw agent protocol."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse


class AgentHttpApi:
    def __init__(
        self,
        *,
        runner: Any,
        endpoint_path: str = "/process",
        enable_stream_task: bool = True,
        stream_task_queue: str = "stream_query",
        stream_task_timeout: float | None = 300,
        **_: Any,
    ) -> None:
        self.runner = runner
        self.endpoint_path = endpoint_path
        self.enable_stream_task = enable_stream_task
        self.stream_task_queue = stream_task_queue
        self.stream_task_timeout = stream_task_timeout
        self.active_tasks: dict[str, dict[str, Any]] = {}
        self.router = APIRouter()
        self._register_routes()

    async def _sse(self, request: dict[str, Any]):
        try:
            async for event in self.runner.stream_query(request):
                if hasattr(event, "model_dump_json"):
                    payload = event.model_dump_json()
                elif hasattr(event, "model_dump"):
                    payload = json.dumps(event.model_dump(), ensure_ascii=False)
                else:
                    payload = json.dumps({"data": str(event)}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"error": str(exc)}) + "\n\n"

    async def _execute_task(self, task_id: str, request: dict[str, Any]) -> None:
        task = self.active_tasks[task_id]
        task.update(status="running", started_at=time.time())
        final_response = None

        async def collect() -> None:
            nonlocal final_response
            async for event in self.runner.stream_query(request):
                final_response = (
                    event.model_dump()
                    if hasattr(event, "model_dump")
                    else {"data": str(event)}
                )

        try:
            if self.stream_task_timeout is None:
                await collect()
            else:
                await asyncio.wait_for(collect(), timeout=self.stream_task_timeout)
            if final_response is None:
                raise RuntimeError("Agent stream yielded no events")
            task.update(
                status="completed",
                result=final_response,
                completed_at=time.time(),
            )
        except Exception as exc:
            task.update(
                status="failed",
                error=str(exc),
                error_type=type(exc).__name__,
                failed_at=time.time(),
            )

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        task = self.active_tasks.get(task_id)
        if task is None:
            return {"error": f"Task {task_id} not found"}
        status = task.get("status")
        if status == "submitted":
            return {"status": "pending", "result": None}
        if status == "running":
            return {
                "status": "running",
                "started_at": task.get("started_at"),
                "result": None,
            }
        if status == "completed":
            return {"status": "finished", "result": task.get("result")}
        if status == "failed":
            return {"status": "error", "result": task.get("error")}
        return {"status": status or "unknown", "result": None}

    def _register_routes(self) -> None:
        async def process(request: dict[str, Any]):
            return StreamingResponse(
                self._sse(request),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        self.router.add_api_route(
            self.endpoint_path,
            process,
            methods=["POST"],
            tags=["agent-api"],
        )

        if not self.enable_stream_task:
            return

        async def submit_task(request: dict[str, Any]):
            task_id = str(uuid4())
            self.active_tasks[task_id] = {
                "task_id": task_id,
                "status": "submitted",
                "queue": self.stream_task_queue,
                "submitted_at": time.time(),
            }
            asyncio.create_task(self._execute_task(task_id, request))
            return {
                "task_id": task_id,
                "status": "submitted",
                "queue": self.stream_task_queue,
                "message": "Stream query task submitted successfully",
            }

        async def task_status(task_id: str):
            return self.get_task_status(task_id)

        self.router.add_api_route(
            f"{self.endpoint_path}/task",
            submit_task,
            methods=["POST"],
            tags=["agent-api"],
        )
        self.router.add_api_route(
            f"{self.endpoint_path}/task/{{task_id}}",
            task_status,
            methods=["GET"],
            tags=["agent-api"],
        )
