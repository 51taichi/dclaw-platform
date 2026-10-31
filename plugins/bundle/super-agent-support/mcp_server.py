# -*- coding: utf-8 -*-
"""Official Streamable HTTP MCP endpoint for generic local tools."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .agent_outbound import AgentOutboundError, AgentOutboundManager
from .agent_outbound_stream import (
    AgentOutboundStreamError,
    AgentOutboundStreamManager,
)
from .business_identity import BusinessIdentityError, BusinessIdentityManager
from .service import LocalExecutionService
from .temporary_resources import (
    TemporaryResourceBroker,
    TemporaryResourceError,
)


class LocalExecutionMcp:
    def __init__(
        self,
        service: LocalExecutionService,
        business_identity: BusinessIdentityManager | None = None,
        agent_outbound: AgentOutboundManager | None = None,
        temporary_resources: TemporaryResourceBroker | None = None,
        agent_outbound_stream: AgentOutboundStreamManager | None = None,
    ) -> None:
        self.service = service
        self.business_identity = business_identity
        self.agent_outbound = agent_outbound
        self.temporary_resources = temporary_resources
        self.agent_outbound_stream = agent_outbound_stream
        self.server = FastMCP(
            "DClaw Local Execution",
            instructions=(
                "Generic DClaw local execution tools. Business decisions and "
                "third-party API selection remain in the Super Agent."
            ),
            stateless_http=True,
            json_response=True,
            streamable_http_path="/",
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
            ),
        )
        self.app = self.server.streamable_http_app()
        self._runner_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._register_tools()

    async def start(self) -> None:
        if self._runner_task is not None:
            return
        stop_event = asyncio.Event()
        ready = asyncio.get_running_loop().create_future()

        async def run() -> None:
            try:
                async with self.server.session_manager.run():
                    if not ready.done():
                        ready.set_result(None)
                    await stop_event.wait()
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(exc)
                raise

        task = asyncio.create_task(
            run(),
            name="dclaw-super-agent-support-mcp",
        )
        self._runner_task = task
        self._stop_event = stop_event
        try:
            await ready
        except BaseException:
            self._runner_task = None
            self._stop_event = None
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def stop(self) -> None:
        task, self._runner_task = self._runner_task, None
        stop_event, self._stop_event = self._stop_event, None
        if task is None:
            return
        if stop_event is not None:
            stop_event.set()
        await task

    def _register_tools(self) -> None:
        service = self.service

        @self.server.tool(
            description="Check local helper connection and protocol compatibility.",
        )
        async def local_environment_status(
            agent_protocol_version: str,
            dclaw_session_token: str,
            bootstrap_session_id: str | None = None,
            wait_seconds: int = 0,
        ) -> dict[str, Any]:
            return await service.call("local_environment_status", locals())

        @self.server.tool(
            description="List generic capabilities reported by the user's local helper.",
        )
        async def local_capabilities_list(
            dclaw_session_token: str,
            output_type: str | None = None,
            device_id: str | None = None,
        ) -> dict[str, Any]:
            return await service.call("local_capabilities_list", locals())

        @self.server.tool(
            description="Prepare a signed capability package on the local helper.",
        )
        async def local_runtime_prepare(
            capability: str,
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_runtime_prepare", locals())

        @self.server.tool(
            description="Start one schema-validated local capability task.",
        )
        async def local_task_start(
            capability_id: str,
            input: dict[str, Any],
            idempotency_key: str,
            dclaw_session_token: str,
            local_file_bindings: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return await service.call("local_task_start", locals())

        @self.server.tool(
            description="Select local files and return opaque references only.",
        )
        async def local_file_select(
            interaction_id: str,
            selector: dict[str, Any],
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_file_select", locals())

        @self.server.tool(
            description="Upload a referenced file directly to a constrained presigned URL.",
        )
        async def local_file_upload(
            local_file_ref: str,
            upload: dict[str, Any],
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_file_upload", locals())

        @self.server.tool(
            description="List persistent managed local artifacts.",
        )
        async def managed_artifacts_list(
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("managed_artifacts_list", locals())

        @self.server.tool(
            description="Preview, select, reveal, or delete a managed artifact.",
        )
        async def managed_artifact_action(
            artifact_id: str,
            action: str,
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("managed_artifact_action", locals())

        @self.server.tool(
            description="Continue a waiting local task at its current checkpoint.",
        )
        async def local_task_continue(
            task_id: str,
            checkpoint_id: str,
            input: dict[str, Any],
            dclaw_session_token: str,
            local_file_bindings: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return await service.call("local_task_continue", locals())

        @self.server.tool(
            description="Read durable task status without advancing the task.",
        )
        async def local_task_status(
            dclaw_session_token: str,
            task_id: str | None = None,
            current_task: bool = False,
            wait_seconds: int = 0,
        ) -> dict[str, Any]:
            return await service.call("local_task_status", locals())

        @self.server.tool(description="Idempotently cancel one local task.")
        async def local_task_cancel(
            task_id: str,
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_task_cancel", locals())

        @self.server.tool(
            description="Read terminal result, error, and local artifact metadata.",
        )
        async def local_task_result(
            task_id: str,
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_task_result", locals())

        if self.business_identity is not None:
            identity = self.business_identity

            @self.server.tool(
                description=(
                    "Issue a one-time installation-bound reference for a registered "
                    "business service. No bearer credential is returned."
                ),
            )
            async def business_service_identity_issue(
                service_id: str,
                audience: str,
                scopes: list[str],
                idempotency_key: str,
                dclaw_session_token: str,
                ttl_seconds: int = 120,
            ) -> dict[str, Any]:
                try:
                    return identity.issue(
                        service_id=service_id,
                        audience=audience,
                        scopes=scopes,
                        idempotency_key=idempotency_key,
                        dclaw_session_token=dclaw_session_token,
                        ttl_seconds=ttl_seconds,
                    )
                except BusinessIdentityError as exc:
                    return {
                        "error": {
                            "code": exc.code,
                            "retryable": exc.reason == "RATE_LIMITED",
                        },
                    }
            @self.server.tool(
                description=(
                    "Send one HTTPS request through the platform transport using a "
                    "one-time business identity reference."
                ),
            )
            async def business_service_outbound_request(
                binding_ref: str,
                method: str,
                url: str,
                dclaw_session_token: str,
                headers: dict[str, str] | None = None,
                json_body: Any | None = None,
                text_body: str | None = None,
                timeout_seconds: int = 30,
            ) -> dict[str, Any]:
                try:
                    return await identity.outbound_request(
                        binding_ref=binding_ref,
                        method=method,
                        url=url,
                        dclaw_session_token=dclaw_session_token,
                        headers=headers,
                        json_body=json_body,
                        text_body=text_body,
                        timeout_seconds=timeout_seconds,
                    )
                except BusinessIdentityError as exc:
                    return {
                        "error": {
                            "code": exc.code,
                            "retryable": exc.reason == "UPSTREAM_FAILED",
                        },
                    }

        if self.agent_outbound is not None:
            outbound = self.agent_outbound

            @self.server.tool(
                description=(
                    "Send one provider-neutral HTTPS request selected by the "
                    "Super Agent. Installation credentials are injected only at "
                    "the transport boundary."
                ),
            )
            async def agent_outbound_request(
                credential_scope: str,
                method: str,
                url: str,
                dclaw_session_token: str,
                credential_ref: str | None = None,
                credential_slot: str | None = None,
                headers: dict[str, str] | None = None,
                json_body: Any | None = None,
                text_body: str | None = None,
                timeout_seconds: int = 30,
            ) -> dict[str, Any]:
                try:
                    return await outbound.request(
                        credential_ref=credential_ref,
                        credential_slot=credential_slot,
                        credential_scope=credential_scope,
                        method=method,
                        url=url,
                        dclaw_session_token=dclaw_session_token,
                        headers=headers,
                        json_body=json_body,
                        text_body=text_body,
                        timeout_seconds=timeout_seconds,
                    )
                except AgentOutboundError as exc:
                    return {
                        "error": {
                            "code": exc.code,
                            "retryable": exc.reason == "UPSTREAM_FAILED",
                        },
                    }

        if self.temporary_resources is not None:
            resources = self.temporary_resources

            @self.server.tool(
                description=(
                    "Create an installation-scoped short-lived object-storage "
                    "upload slot for a local file."
                ),
            )
            async def agent_resource_upload_create(
                mime_type: str,
                max_size_bytes: int,
                purpose: str,
                dclaw_session_token: str,
                ttl_seconds: int = 900,
            ) -> dict[str, Any]:
                try:
                    return resources.create_upload(
                        mime_type=mime_type,
                        max_size_bytes=max_size_bytes,
                        purpose=purpose,
                        dclaw_session_token=dclaw_session_token,
                        ttl_seconds=ttl_seconds,
                    )
                except TemporaryResourceError as exc:
                    return {"error": {"code": exc.code, "retryable": False}}

            @self.server.tool(
                description="Finalize a direct upload using the trusted local digest.",
            )
            async def agent_resource_upload_complete(
                resource_ref: str,
                size_bytes: int,
                sha256: str,
                dclaw_session_token: str,
            ) -> dict[str, Any]:
                try:
                    return resources.complete_upload(
                        resource_ref=resource_ref,
                        size_bytes=size_bytes,
                        sha256=sha256,
                        dclaw_session_token=dclaw_session_token,
                    )
                except TemporaryResourceError as exc:
                    return {"error": {"code": exc.code, "retryable": False}}

            @self.server.tool(
                description="Resolve a ready resource to a short-lived HTTPS read URL.",
            )
            async def agent_resource_read(
                resource_ref: str,
                dclaw_session_token: str,
                ttl_seconds: int = 300,
            ) -> dict[str, Any]:
                try:
                    return resources.read(
                        resource_ref=resource_ref,
                        dclaw_session_token=dclaw_session_token,
                        ttl_seconds=ttl_seconds,
                    )
                except TemporaryResourceError as exc:
                    return {"error": {"code": exc.code, "retryable": False}}

            @self.server.tool(description="Revoke a short-lived resource immediately.")
            async def agent_resource_revoke(
                resource_ref: str,
                dclaw_session_token: str,
            ) -> dict[str, Any]:
                try:
                    return resources.revoke(
                        resource_ref=resource_ref,
                        dclaw_session_token=dclaw_session_token,
                    )
                except TemporaryResourceError as exc:
                    return {"error": {"code": exc.code, "retryable": False}}

        if self.agent_outbound_stream is not None:
            outbound_stream = self.agent_outbound_stream

            @self.server.tool(
                description=(
                    "Run one restricted streaming HTTPS or WebSocket exchange and "
                    "return an opaque short-lived resource reference."
                ),
            )
            async def agent_outbound_stream_request(
                protocol: str,
                url: str,
                credential_scope: str,
                output_mime_type: str,
                purpose: str,
                dclaw_session_token: str,
                credential_ref: str | None = None,
                credential_slot: str | None = None,
                method: str = "GET",
                headers: dict[str, str] | None = None,
                json_body: Any | None = None,
                text_body: str | None = None,
                send_frames: list[dict[str, Any]] | None = None,
                completion_text: str | None = None,
                binary_filter_contains: str | None = None,
                binary_strip_through: str | None = None,
                response_transform: dict[str, Any] | None = None,
                timeout_seconds: int = 60,
                max_output_bytes: int = 33_554_432,
            ) -> dict[str, Any]:
                try:
                    return await outbound_stream.request(**locals())
                except AgentOutboundStreamError as exc:
                    return {
                        "error": {
                            "code": exc.code,
                            "retryable": exc.reason
                            in {"UPSTREAM_FAILED", "UPSTREAM_TIMEOUT"},
                        },
                    }
