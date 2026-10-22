"""Generic device routing and durable local task lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from jsonschema import Draft202012Validator
from packaging.version import InvalidVersion, Version

from .contracts import ERRORS, PublicError, failure, success, trace_id
from .credentials import CredentialBroker, CredentialError
from .session import SessionError, SessionSigner
from .store import StateStore

logger = logging.getLogger(__name__)
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
ACTIVE_STATES = {"queued", "running", "awaiting_input", "cancelling"}
PROTOCOL_VERSION = "1"
CATALOG_VERSION = "1"
MIN_RUNNER_VERSION = "1.0.0"


def _parsed_version(value: Any) -> Version | None:
    try:
        return Version(str(value))
    except (InvalidVersion, TypeError):
        return None


def _runner_supports(device: dict[str, Any], minimum: str) -> bool:
    current = _parsed_version(device.get("runner_version"))
    required = _parsed_version(minimum)
    return current is not None and required is not None and current >= required


class LocalExecutionService:
    """Route generic capability work to the current user's local helper."""

    def __init__(
        self,
        store: StateStore,
        signer: SessionSigner,
        credential_broker: CredentialBroker,
    ) -> None:
        self.store = store
        self.signer = signer
        self.credential_broker = credential_broker
        self._connections: dict[str, Any] = {}
        self._task_events: dict[str, asyncio.Event] = {}
        self._device_event = asyncio.Event()
        self._lock = asyncio.Lock()

    async def attach(self, device_id: str, websocket: Any) -> None:
        async with self._lock:
            previous = self._connections.get(device_id)
            self._connections[device_id] = websocket
            self._device_event.set()
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="device_reconnected")
            except Exception:
                pass

    async def detach(self, device_id: str, websocket: Any) -> None:
        async with self._lock:
            if self._connections.get(device_id) is websocket:
                self._connections.pop(device_id, None)
                self.store.set_device_status(device_id, "offline")
                self._device_event.set()

    async def _send(self, device_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            websocket = self._connections.get(device_id)
        if websocket is None:
            raise ERRORS["DEVICE_NOT_READY"]
        try:
            await websocket.send_json(message)
        except Exception as exc:
            await self.detach(device_id, websocket)
            raise ERRORS["DEVICE_NOT_READY"] from exc

    def _identity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        token = arguments.get("dclaw_session_token")
        if not isinstance(token, str) or not token:
            raise ERRORS["AUTHENTICATION_FAILED"]
        try:
            return self.signer.verify(token)
        except SessionError as exc:
            raise ERRORS["AUTHENTICATION_FAILED"] from exc

    async def call(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        current_trace = trace_id()
        try:
            if not isinstance(arguments, dict):
                raise ERRORS["INVALID_ARGUMENTS"]
            identity = self._identity(arguments)
            clean = {
                key: value
                for key, value in arguments.items()
                if key != "dclaw_session_token"
            }
            handler = getattr(self, f"_{name}", None)
            if handler is None:
                raise ERRORS["INVALID_ARGUMENTS"]
            data = await handler(clean, identity, current_trace)
            return success(data, current_trace)
        except PublicError as exc:
            return failure(exc, current_trace, name)
        except Exception:
            logger.exception(
                "Super Agent Support failure trace_id=%s tool=%s",
                current_trace,
                name,
            )
            return failure(ERRORS["INTERNAL"], current_trace, name)

    def _online_devices(self, user_id: str) -> list[dict[str, Any]]:
        return [
            item
            for item in self.store.list_devices(user_id)
            if item["status"] == "online"
            and item["device_id"] in self._connections
        ]

    def _select_device(
        self, user_id: str, capability_id: str
    ) -> dict[str, Any]:
        for device in self._online_devices(user_id):
            if any(
                item.get("capability_id") == capability_id
                for item in device["capabilities"]
                if isinstance(item, dict)
            ):
                return device
        raise ERRORS["DEVICE_NOT_READY"]

    async def _local_environment_status(self, arguments, identity, _trace):
        requested = arguments.get("agent_protocol_version")
        if not isinstance(requested, str) or not 1 <= len(requested) <= 32:
            raise ERRORS["INVALID_ARGUMENTS"]
        bootstrap_session_id = arguments.get("bootstrap_session_id")
        wait_seconds = arguments.get("wait_seconds", 0)
        if (
            bootstrap_session_id is not None
            and (
                not isinstance(bootstrap_session_id, str)
                or len(bootstrap_session_id) > 128
            )
        ) or type(wait_seconds) is not int or not 0 <= wait_seconds <= 25:
            raise ERRORS["INVALID_ARGUMENTS"]
        return await self.environment_status(
            user_id=identity["u"],
            agent_protocol_version=requested,
            bootstrap_session_id=bootstrap_session_id,
            wait_seconds=wait_seconds,
        )

    async def environment_status(
        self,
        *,
        user_id: str,
        agent_protocol_version: str,
        bootstrap_session_id: str | None = None,
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        """Return the authenticated user's Runner compatibility status."""
        devices = self._online_devices(user_id)
        if not devices and wait_seconds:
            deadline = time.monotonic() + wait_seconds
            while not devices:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._device_event.clear()
                devices = self._online_devices(user_id)
                if devices:
                    break
                try:
                    await asyncio.wait_for(
                        self._device_event.wait(), timeout=remaining
                    )
                except asyncio.TimeoutError:
                    break
                devices = self._online_devices(user_id)
        known_devices = self.store.list_devices(user_id)
        online_ids = {item["device_id"] for item in devices}
        compatible_devices = [
            item
            for item in devices
            if _runner_supports(item, MIN_RUNNER_VERSION)
        ]
        if agent_protocol_version != PROTOCOL_VERSION:
            state = "protocol_incompatible"
            reason = "protocol_version_mismatch"
            user_action = "contact_administrator"
        elif compatible_devices:
            state = "ready"
            reason = "none"
            user_action = "none"
        elif devices:
            state = "runner_update_required"
            reason = "runner_version_too_old"
            user_action = "update_dclaw"
        else:
            state = "device_not_ready"
            reason = "device_offline" if known_devices else "no_paired_device"
            user_action = "open_dclaw"
        return {
            "state": state,
            "reason": reason,
            "protocol_version": PROTOCOL_VERSION,
            "compatible": agent_protocol_version == PROTOCOL_VERSION,
            "minimum_runner_version": MIN_RUNNER_VERSION,
            "bootstrap_session_id": bootstrap_session_id,
            "user_action": user_action,
            "devices": [
                {
                    "device_id": item["device_id"],
                    "display_name": item["display_name"],
                    "runner_version": item["runner_version"],
                    "online": item["device_id"] in online_ids,
                    "last_seen": item["last_seen"],
                }
                for item in known_devices
            ],
        }

    async def _local_capabilities_list(self, arguments, identity, _trace):
        requested_device = arguments.get("device_id")
        if requested_device is not None and not isinstance(
            requested_device, str
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        devices = self._online_devices(identity["u"])
        if requested_device:
            devices = [
                item
                for item in devices
                if item["device_id"] == requested_device
            ]
        seen: set[tuple[str, str]] = set()
        capabilities = []
        for device in devices:
            for capability in device["capabilities"]:
                if not isinstance(capability, dict):
                    continue
                key = (
                    str(capability.get("capability_id") or ""),
                    str(capability.get("version") or ""),
                )
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                capabilities.append(capability)
        capabilities.sort(
            key=lambda item: (
                str(item.get("capability_id") or ""),
                str(item.get("version") or ""),
            )
        )
        return {
            "catalog_version": CATALOG_VERSION,
            "availability": "available" if devices else "device_not_ready",
            "capabilities": capabilities,
            "device_count": len(devices),
        }

    async def _local_runtime_prepare(self, arguments, identity, _trace):
        capability_id = arguments.get("capability")
        if not isinstance(capability_id, str) or not capability_id:
            raise ERRORS["INVALID_ARGUMENTS"]
        package = self.store.get_package_for_capability(capability_id)
        if package is None:
            raise ERRORS["CAPABILITY_NOT_FOUND"]
        descriptor = package["descriptor"]
        common = {
            "capability_id": capability_id,
            "package_id": descriptor["package_id"],
            "package_version": descriptor["package_version"],
            "min_runner_version": descriptor["min_runner_version"],
        }
        online = self._online_devices(identity["u"])
        if not online:
            return common | {
                "state": "device_not_ready",
                "device_id": None,
                "runner_version": None,
                "user_action": "open_dclaw",
            }
        compatible = [
            device
            for device in online
            if _runner_supports(device, descriptor["min_runner_version"])
        ]
        if not compatible:
            device = online[0]
            return common | {
                "state": "runner_update_required",
                "device_id": device["device_id"],
                "runner_version": device["runner_version"],
                "user_action": "update_dclaw",
            }
        for device in compatible:
            installed = any(
                item.get("capability_id") == capability_id
                and item.get("package_id") == descriptor["package_id"]
                and item.get("package_version")
                == descriptor["package_version"]
                for item in device["capabilities"]
                if isinstance(item, dict)
            )
            if installed:
                return common | {
                    "state": "ready",
                    "device_id": device["device_id"],
                    "runner_version": device["runner_version"],
                    "user_action": "none",
                }
        device = compatible[0]
        await self._send(
            device["device_id"],
            {
                "type": "runtime.prepare",
                "protocol_version": PROTOCOL_VERSION,
                "capability_package": package,
            },
        )
        return common | {
            "state": "preparing",
            "device_id": device["device_id"],
            "runner_version": device["runner_version"],
            "user_action": "wait",
        }

    def _runtime_credentials(
        self,
        task_input: dict[str, Any],
        descriptor: dict[str, Any],
        identity: dict[str, Any],
    ) -> dict[str, Any]:
        required = descriptor.get("credential_scopes", [])
        references = task_input.get("credential_refs", {})
        if not required:
            return {}
        if not isinstance(references, dict):
            raise ERRORS["INVALID_ARGUMENTS"]
        resolved = {}
        try:
            for scope in required:
                reference = references.get(scope)
                if not isinstance(reference, str):
                    raise CredentialError("missing credential reference")
                resolved[scope] = self.credential_broker.resolve(
                    reference,
                    user_id=identity["u"],
                    agent_id=identity["a"],
                    installation_id=identity["g"],
                    required_scope=scope,
                )
        except CredentialError as exc:
            raise ERRORS["AUTHENTICATION_FAILED"] from exc
        return resolved

    async def _local_task_start(self, arguments, identity, current_trace):
        capability_id = arguments.get("capability_id")
        task_input = arguments.get("input")
        idempotency_key = arguments.get("idempotency_key")
        if (
            not isinstance(capability_id, str)
            or not isinstance(task_input, dict)
            or not isinstance(idempotency_key, str)
            or not idempotency_key
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        package = self.store.get_package_for_capability(capability_id)
        if package is None:
            raise ERRORS["CAPABILITY_NOT_FOUND"]
        input_schema = package["descriptor"]["schemas"]["input"]["document"]
        if list(Draft202012Validator(input_schema).iter_errors(task_input)):
            raise ERRORS["INVALID_CAPABILITY_PAYLOAD"]
        device = self._select_device(identity["u"], capability_id)
        credentials = self._runtime_credentials(
            task_input,
            package["descriptor"],
            identity,
        )
        try:
            task, created = self.store.create_task(
                user_id=identity["u"],
                agent_id=identity["a"],
                agent_name=identity["n"],
                invocation_id=identity["i"],
                capability_id=capability_id,
                task_input=task_input,
                idempotency_key=idempotency_key,
                device_id=device["device_id"],
                max_concurrency=int(
                    package["descriptor"]["limits"]["max_concurrency"]
                ),
            )
        except ValueError as exc:
            if str(exc) == "capacity":
                raise ERRORS["RESOURCE_EXHAUSTED"] from exc
            raise ERRORS["IDEMPOTENCY_CONFLICT"] from exc
        if created:
            await self._send(
                device["device_id"],
                {
                    "type": "task.start",
                    "protocol_version": "1",
                    "trace_id": current_trace,
                    "task": {
                        "task_id": task["task_id"],
                        "capability_id": capability_id,
                        "input": task_input,
                        "task_root_name": identity["n"],
                    },
                    "runtime_credentials": credentials,
                },
            )
        return self._public_task(task) | {"idempotent_replay": not created}

    async def _local_task_continue(self, arguments, identity, current_trace):
        task = self._owned_task(arguments.get("task_id"), identity["u"])
        checkpoint_id = arguments.get("checkpoint_id")
        continuation = arguments.get("input")
        checkpoint = task.get("checkpoint") or {}
        if checkpoint.get("checkpoint_id") != checkpoint_id:
            raise ERRORS["CHECKPOINT_MISMATCH"]
        if task["status"] != "awaiting_input" or not isinstance(
            continuation, dict
        ):
            raise ERRORS["TASK_NOT_ACTIVE"]
        await self._send(
            task["device_id"],
            {
                "type": "task.continue",
                "protocol_version": "1",
                "trace_id": current_trace,
                "task_id": task["task_id"],
                "checkpoint_id": checkpoint_id,
                "input": continuation,
            },
        )
        task = (
            self.store.update_task(task["task_id"], status="running") or task
        )
        return self._public_task(task)

    async def _local_task_status(self, arguments, identity, _trace):
        task_id = arguments.get("task_id")
        current = arguments.get("current_task") is True
        if bool(task_id) == current:
            raise ERRORS["INVALID_ARGUMENTS"]
        task = (
            self.store.current_task(identity["u"], identity["a"])
            if current
            else self.store.get_task(str(task_id), identity["u"])
        )
        if task is None:
            raise ERRORS["TASK_NOT_FOUND"]
        wait_seconds = arguments.get("wait_seconds", 0)
        if (
            isinstance(wait_seconds, int)
            and 0 < wait_seconds <= 25
            and task["status"] in ACTIVE_STATES
        ):
            event = self._task_events.setdefault(
                task["task_id"], asyncio.Event()
            )
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass
            task = self._owned_task(task["task_id"], identity["u"])
        return self._public_task(task)

    async def _local_task_cancel(self, arguments, identity, current_trace):
        task = self._owned_task(arguments.get("task_id"), identity["u"])
        if task["status"] in TERMINAL_STATES:
            return self._public_task(task)
        await self._send(
            task["device_id"],
            {
                "type": "task.cancel",
                "protocol_version": "1",
                "trace_id": current_trace,
                "task_id": task["task_id"],
            },
        )
        task = (
            self.store.update_task(task["task_id"], status="cancelling")
            or task
        )
        return self._public_task(task)

    async def _local_task_result(self, arguments, identity, _trace):
        task = self._owned_task(arguments.get("task_id"), identity["u"])
        return self._public_task(task)

    def _owned_task(self, task_id: Any, user_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id:
            raise ERRORS["INVALID_ARGUMENTS"]
        task = self.store.get_task(task_id, user_id)
        if task is None:
            raise ERRORS["TASK_NOT_FOUND"]
        return task

    @staticmethod
    def _public_task(task: dict[str, Any]) -> dict[str, Any]:
        return {
            key: task.get(key)
            for key in (
                "task_id",
                "capability_id",
                "device_id",
                "status",
                "checkpoint",
                "result",
                "error",
                "created_at",
                "updated_at",
            )
        }

    async def handle_device_message(
        self,
        device_id: str,
        user_id: str,
        message: dict[str, Any],
    ) -> None:
        message_type = message.get("type")
        if message_type == "heartbeat":
            self.store.set_device_status(device_id, "online")
            return
        if message_type == "capabilities.report":
            capabilities = message.get("capabilities")
            if isinstance(capabilities, list):
                self.store.update_device_capabilities(device_id, capabilities)
            return
        if message_type != "task.event":
            return
        task_id = message.get("task_id")
        sequence = message.get("sequence")
        event_type = message.get("event_type")
        payload = message.get("payload", {})
        if (
            not isinstance(task_id, str)
            or not isinstance(sequence, int)
            or sequence < 1
            or not isinstance(event_type, str)
            or not isinstance(payload, dict)
        ):
            return
        task = self.store.get_task(task_id, user_id)
        if task is None or task["device_id"] != device_id:
            return
        allowed_events = {
            "queued": {"started", "failed", "cancelled"},
            "running": {
                "started",
                "progress",
                "checkpoint",
                "completed",
                "failed",
                "cancelled",
            },
            "awaiting_input": {"cancelled", "failed"},
            "cancelling": {"completed", "failed", "cancelled"},
        }
        if event_type not in allowed_events.get(task["status"], set()):
            return
        if not self.store.append_event(task_id, sequence, event_type, payload):
            return
        schema_name = {
            "checkpoint": "checkpoint",
            "completed": "result",
        }.get(event_type)
        if schema_name:
            package = self.store.get_package_for_capability(
                task["capability_id"]
            )
            schema = (
                package["descriptor"]["schemas"][schema_name]["document"]
                if package
                else None
            )
            if schema is None or list(
                Draft202012Validator(schema).iter_errors(payload)
            ):
                self.store.update_task(
                    task_id,
                    status="failed",
                    error={
                        "code": "CAPABILITY.INVALID_PAYLOAD",
                        "message": "Capability output failed signed schema validation.",
                    },
                )
                self._task_events.setdefault(task_id, asyncio.Event()).set()
                return
        status_map = {
            "started": "running",
            "progress": "running",
            "checkpoint": "awaiting_input",
            "completed": "succeeded",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        status = status_map.get(event_type)
        if status:
            self.store.update_task(
                task_id,
                status=status,
                checkpoint=payload if event_type == "checkpoint" else None,
                result=payload if event_type == "completed" else None,
                error=payload if event_type == "failed" else None,
            )
            self._task_events.setdefault(task_id, asyncio.Event()).set()
