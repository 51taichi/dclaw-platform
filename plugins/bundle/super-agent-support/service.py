# -*- coding: utf-8 -*-
"""Generic device routing and durable local task lifecycle."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from packaging.version import InvalidVersion, Version

from .contracts import ERRORS, PublicError, failure, success, trace_id
from .credentials import CredentialBroker, CredentialError
from .public_components import PublicComponentError, PublicComponentRegistry
from .session import SessionError, SessionSigner
from .store import StateStore

logger = logging.getLogger(__name__)
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
ACTIVE_STATES = {"queued", "running", "awaiting_input", "cancelling"}
PROTOCOL_VERSION = "2"
CATALOG_VERSION = "1"
MIN_RUNNER_VERSION = "1.1.0"
AIGC_TRANSFER_MIN_RUNNER_VERSION = "1.4.6"
PRIOR_OUTPUT_BIND_MIN_RUNNER_VERSION = "1.4.7"
LEGACY_RUNNER_VERSION = "1.0.0"
LOCAL_FILE_REF_PATTERN = re.compile(r"^lfr_[A-Za-z0-9_-]{32,156}$")
ARTIFACT_ID_PATTERN = re.compile(r"^artifact_[A-Za-z0-9_-]{32,156}$")
BINDING_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
FILE_EXTENSION_PATTERN = re.compile(r"^\.[A-Za-z0-9._+-]{1,31}$")
MIME_TYPE_PATTERN = re.compile(
    r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+*-]+$",
)
DEVICE_REQUEST_TIMEOUT_SECONDS = 180
FILE_CAPABILITY_ID = "interaction.file.select/1"


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
        *,
        public_components: PublicComponentRegistry | None = None,
    ) -> None:
        self.store = store
        self.signer = signer
        self.credential_broker = credential_broker
        self.public_components = public_components
        self._connections: dict[str, Any] = {}
        self._task_events: dict[str, asyncio.Event] = {}
        self._device_requests: dict[
            str,
            tuple[str, asyncio.Future[dict[str, Any]]],
        ] = {}
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

    @staticmethod
    def _scope(identity: dict[str, Any]) -> dict[str, str]:
        return {
            "tenant_id": str(identity.get("t") or "local"),
            "user_id": identity["u"],
            "session_id": identity["s"],
            "agent_id": identity["a"],
            "installation_id": identity["g"],
            "release_id": identity["r"],
            "invocation_id": identity["i"],
        }

    async def _request_device(
        self,
        device_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._device_requests[request_id] = (device_id, future)
        try:
            await self._send(device_id, {**message, "request_id": request_id})
            return await asyncio.wait_for(
                future,
                timeout=DEVICE_REQUEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise ERRORS["FILE_SELECTOR_DEVICE_OFFLINE"] from exc
        finally:
            self._device_requests.pop(request_id, None)

    def _identity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        token = arguments.get("dclaw_session_token")
        if not isinstance(token, str) or not token:
            raise ERRORS["AUTHENTICATION_FAILED"]
        try:
            return self.signer.verify(token)
        except SessionError as exc:
            raise ERRORS["AUTHENTICATION_FAILED"] from exc

    @staticmethod
    def _require_file_capability(identity: dict[str, Any]) -> None:
        if FILE_CAPABILITY_ID not in identity.get("c", []):
            raise ERRORS["FILE_SELECTOR_NOT_AUTHORIZED"]

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
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
        self,
        user_id: str,
        capability_id: str,
        *,
        require_file_support: bool = False,
        required_device_id: str | None = None,
    ) -> dict[str, Any]:
        for device in self._online_devices(user_id):
            if (
                required_device_id is not None
                and device["device_id"] != required_device_id
            ):
                continue
            if require_file_support and (
                device.get("protocol_version") != PROTOCOL_VERSION
                or not _runner_supports(device, MIN_RUNNER_VERSION)
            ):
                continue
            if any(
                item.get("capability_id") == capability_id
                for item in device["capabilities"]
                if isinstance(item, dict)
            ):
                return device
        raise ERRORS["DEVICE_NOT_READY"]

    def _select_aigc_transfer_device(self, user_id: str) -> dict[str, Any]:
        for device in self._online_devices(user_id):
            if (
                device.get("protocol_version") == PROTOCOL_VERSION
                and _runner_supports(
                    device,
                    AIGC_TRANSFER_MIN_RUNNER_VERSION,
                )
            ):
                return device
        raise ERRORS["DEVICE_NOT_READY"]

    def _task_protocol(self, task: dict[str, Any], user_id: str) -> str:
        if task.get("local_file_bindings"):
            return PROTOCOL_VERSION
        device = self.store.get_device_for_user(task["device_id"], user_id)
        return str((device or {}).get("protocol_version") or "1")

    def _require_file_device(
        self,
        user_id: str,
        device_id: str,
    ) -> dict[str, Any]:
        device = self.store.get_device_for_user(device_id, user_id)
        if (
            device is None
            or device.get("status") != "online"
            or device_id not in self._connections
            or device.get("protocol_version") != PROTOCOL_VERSION
            or not _runner_supports(device, MIN_RUNNER_VERSION)
        ):
            raise ERRORS["FILE_SELECTOR_DEVICE_OFFLINE"]
        return device

    async def _local_environment_status(self, arguments, identity, _trace):
        requested = arguments.get("agent_protocol_version")
        if not isinstance(requested, str) or not 1 <= len(requested) <= 32:
            raise ERRORS["INVALID_ARGUMENTS"]
        bootstrap_session_id = arguments.get("bootstrap_session_id")
        wait_seconds = arguments.get("wait_seconds", 0)
        if (
            (
                bootstrap_session_id is not None
                and (
                    not isinstance(bootstrap_session_id, str)
                    or len(bootstrap_session_id) > 128
                )
            )
            or type(wait_seconds) is not int
            or not 0 <= wait_seconds <= 25
        ):
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
                        self._device_event.wait(),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    break
                devices = self._online_devices(user_id)
        known_devices = self.store.list_devices(user_id)
        online_ids = {item["device_id"] for item in devices}
        supported_protocol = agent_protocol_version in {"1", PROTOCOL_VERSION}
        required_runner = (
            LEGACY_RUNNER_VERSION
            if agent_protocol_version == "1"
            else MIN_RUNNER_VERSION
        )
        compatible_devices = [
            item
            for item in devices
            if _runner_supports(item, required_runner)
            and (
                agent_protocol_version == "1"
                or item.get("protocol_version") == PROTOCOL_VERSION
            )
        ]
        if not supported_protocol:
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
            user_action = "update_local_helper"
        else:
            state = "device_not_ready"
            reason = "device_offline" if known_devices else "no_paired_device"
            user_action = "open_dclaw"
        return {
            "state": state,
            "reason": reason,
            "protocol_version": agent_protocol_version
            if supported_protocol
            else PROTOCOL_VERSION,
            "compatible": supported_protocol,
            "minimum_runner_version": required_runner,
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
            requested_device,
            str,
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
            ),
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
            and device.get("platform", "windows-x64")
            in descriptor.get("operating_systems", ["windows-x64"])
        ]
        if not compatible:
            device = online[0]
            return common | {
                "state": "runner_update_required",
                "device_id": device["device_id"],
                "runner_version": device["runner_version"],
                "user_action": "update_local_helper",
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
        requirements = descriptor.get("public_components", [])
        component_packages: list[dict[str, Any]] = []
        if requirements:
            if self.public_components is None:
                raise ERRORS["PUBLIC_COMPONENT_UNAVAILABLE"]
            try:
                component_packages = self.public_components.resolve(
                    requirements,
                    platform=str(device.get("platform") or "windows-x64"),
                )
            except PublicComponentError as exc:
                raise ERRORS["PUBLIC_COMPONENT_UNAVAILABLE"] from exc
        await self._send(
            device["device_id"],
            {
                "type": "runtime.prepare",
                "protocol_version": str(device.get("protocol_version") or "1"),
                "public_components": component_packages,
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
        local_file_bindings = arguments.get("local_file_bindings")
        if local_file_bindings is None:
            local_file_bindings = {}
        if (
            not isinstance(capability_id, str)
            or not isinstance(task_input, dict)
            or not isinstance(idempotency_key, str)
            or not idempotency_key
            or not isinstance(local_file_bindings, dict)
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        if local_file_bindings:
            self._require_file_capability(identity)
        package = self.store.get_package_for_capability(capability_id)
        if package is None:
            raise ERRORS["CAPABILITY_NOT_FOUND"]
        input_schema = package["descriptor"]["schemas"]["input"]["document"]
        if list(Draft202012Validator(input_schema).iter_errors(task_input)):
            raise ERRORS["INVALID_CAPABILITY_PAYLOAD"]
        replay = self.store.get_task_by_idempotency(
            identity["u"],
            identity["a"],
            idempotency_key,
        )
        if replay is not None:
            if (
                replay["capability_id"] != capability_id
                or replay["input"] != task_input
                or (replay.get("local_file_bindings") or {})
                != local_file_bindings
            ):
                raise ERRORS["IDEMPOTENCY_CONFLICT"]
            return self._public_task(replay) | {"idempotent_replay": True}
        (
            normalized_bindings,
            binding_device_id,
        ) = self._validate_local_file_bindings(
            local_file_bindings,
            identity=identity,
        )
        device = self._select_device(
            identity["u"],
            capability_id,
            require_file_support=bool(local_file_bindings),
            required_device_id=binding_device_id,
        )
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
                    package["descriptor"]["limits"]["max_concurrency"],
                ),
                tenant_id=str(identity.get("t") or "local"),
                session_id=identity["s"],
                installation_id=identity["g"],
                release_id=identity["r"],
                local_file_bindings=normalized_bindings,
            )
        except ValueError as exc:
            if str(exc) == "capacity":
                raise ERRORS["RESOURCE_EXHAUSTED"] from exc
            raise ERRORS["IDEMPOTENCY_CONFLICT"] from exc
        if created:
            task_payload = {
                "task_id": task["task_id"],
                "capability_id": capability_id,
                "input": task_input,
                "task_root_name": identity["n"],
            }
            if normalized_bindings:
                task_payload.update(
                    {
                        "local_file_bindings": normalized_bindings,
                        "scope": self._scope(identity),
                    },
                )
            await self._send(
                device["device_id"],
                {
                    "type": "task.start",
                    "protocol_version": (
                        PROTOCOL_VERSION
                        if local_file_bindings
                        else str(device.get("protocol_version") or "1")
                    ),
                    "trace_id": current_trace,
                    "task": task_payload,
                    "runtime_credentials": credentials,
                },
            )
        return self._public_task(task) | {"idempotent_replay": not created}

    async def _aigc_assets_localize(self, arguments, identity, current_trace):
        material_task_id = arguments.get("material_task_id")
        idempotency_key = arguments.get("idempotency_key")
        assets = arguments.get("assets")
        if (
            not isinstance(material_task_id, str) or not material_task_id
            or not isinstance(idempotency_key, str) or not idempotency_key
            or not isinstance(assets, list) or not assets
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        public_assets = [
            {key: value for key, value in item.items() if key != "download_url"}
            for item in assets if isinstance(item, dict)
        ]
        if len(public_assets) != len(assets):
            raise ERRORS["INVALID_ARGUMENTS"]
        task_input = {
            "material_task_id": material_task_id,
            "assets": public_assets,
        }
        replay = self.store.get_task_by_idempotency(
            identity["u"], identity["a"], idempotency_key,
        )
        if replay is not None:
            if (
                replay["capability_id"] != "aigc.task.assets.localize/1"
                or replay["input"] != task_input
            ):
                raise ERRORS["IDEMPOTENCY_CONFLICT"]
            return self._public_task(replay) | {"idempotent_replay": True}
        device = self._select_aigc_transfer_device(identity["u"])
        try:
            task, created = self.store.create_task(
                user_id=identity["u"],
                agent_id=identity["a"],
                agent_name=identity["n"],
                invocation_id=identity["i"],
                capability_id="aigc.task.assets.localize/1",
                task_input=task_input,
                idempotency_key=idempotency_key,
                device_id=device["device_id"],
                max_concurrency=4,
                tenant_id=str(identity.get("t") or "local"),
                session_id=identity["s"],
                installation_id=identity["g"],
                release_id=identity["r"],
            )
        except ValueError as exc:
            if str(exc) == "capacity":
                raise ERRORS["RESOURCE_EXHAUSTED"] from exc
            raise ERRORS["IDEMPOTENCY_CONFLICT"] from exc
        if created:
            try:
                await self._send(
                    device["device_id"],
                    {
                        "type": "aigc.assets.localize",
                        "protocol_version": PROTOCOL_VERSION,
                        "trace_id": current_trace,
                        "task": {
                            "task_id": task["task_id"],
                            "material_task_id": material_task_id,
                            "task_root_name": identity["n"],
                            "assets": assets,
                        },
                    },
                )
                try:
                    self.store.mark_task_dispatched(task["task_id"])
                except Exception:
                    logger.warning(
                        "AIGC local task dispatch marker unavailable task=%s",
                        task["task_id"],
                    )
            except PublicError as exc:
                self.store.update_task(
                    task["task_id"],
                    status="failed",
                    error={
                        "code": exc.code,
                        "message": exc.public_message,
                        "retryable": exc.retryable,
                        "user_action": exc.user_action,
                    },
                )
                self._task_events.setdefault(
                    task["task_id"], asyncio.Event(),
                ).set()
                raise
        return self._public_task(task) | {"idempotent_replay": not created}

    async def bind_localized_outputs(
        self,
        *,
        identity: dict[str, Any],
        source_task: dict[str, Any],
        files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        device = self._require_file_device(identity["u"], source_task["device_id"])
        if not _runner_supports(device, PRIOR_OUTPUT_BIND_MIN_RUNNER_VERSION):
            raise ERRORS["DEVICE_NOT_READY"]
        response = await self._request_device(
            device["device_id"],
            {
                "type": "aigc.assets.bind",
                "protocol_version": PROTOCOL_VERSION,
                "source_task_id": source_task["task_id"],
                "source_agent_name": source_task["agent_name"],
                "files": files,
                "scope": self._scope(identity),
            },
        )
        if response.get("status") == "rejected":
            code = response.get("error_code")
            allowed = {
                "LOCAL_SOURCE.FILE_MISSING", "LOCAL_SOURCE.FILE_CHANGED",
                "LOCAL_SOURCE.MANIFEST_INVALID", "LOCAL_SOURCE.UNAVAILABLE",
            }
            return {"status": "rejected", "error_code": code if code in allowed else "LOCAL_SOURCE.UNAVAILABLE"}
        returned = response.get("files")
        if response.get("status") != "bound" or not isinstance(returned, list) or len(returned) != len(files):
            return {"status": "unavailable"}
        for expected, item in zip(files, returned):
            if (
                not isinstance(item, dict)
                or set(item) != {"slot", "order", "file"}
                or item["slot"] != expected["slot"]
                or item["order"] != expected["order"]
                or not self._safe_file_metadata(item["file"], device["device_id"])
            ):
                return {"status": "unavailable"}
        if len({item["file"]["local_file_ref"] for item in returned}) != len(returned):
            return {"status": "unavailable"}
        expires_at = int(time.time()) + 3600
        if not self.store.save_local_file_refs(
            returned, scope=self._scope(identity),
            source_task_id=source_task["task_id"],
            device_id=device["device_id"], expires_at=expires_at,
        ):
            return {"status": "unavailable"}
        return {"status": "bound", "expires_at": expires_at, "files": returned}

    def _validate_local_file_bindings(
        self,
        bindings: dict[str, Any],
        *,
        identity: dict[str, Any],
    ) -> tuple[dict[str, dict[str, str]], str | None]:
        if len(bindings) > 20:
            raise ERRORS["INVALID_ARGUMENTS"]
        expected_scope = self._scope(identity)
        normalized: dict[str, dict[str, str]] = {}
        binding_device_id: str | None = None
        for name, value in bindings.items():
            if (
                not isinstance(name, str)
                or BINDING_NAME_PATTERN.fullmatch(name) is None
                or not isinstance(value, dict)
                or set(value) != {"local_file_ref", "access"}
                or value.get("access") != "read"
            ):
                raise ERRORS["INVALID_ARGUMENTS"]
            reference = value.get("local_file_ref")
            if (
                not isinstance(reference, str)
                or LOCAL_FILE_REF_PATTERN.fullmatch(reference) is None
            ):
                raise ERRORS["INVALID_ARGUMENTS"]
            record = self.store.get_local_file_ref(reference)
            if record is None:
                raise ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"]
            if (
                binding_device_id is not None
                and record["device_id"] != binding_device_id
            ):
                raise ERRORS["LOCAL_FILE_REF_WRONG_DEVICE"]
            binding_device_id = record["device_id"]
            if record["revoked_at"] is not None:
                raise ERRORS["LOCAL_FILE_REF_REVOKED"]
            if int(record["expires_at"]) <= int(time.time()):
                raise ERRORS["LOCAL_FILE_REF_EXPIRED"]
            for field in (
                "tenant_id",
                "user_id",
                "session_id",
                "agent_id",
                "installation_id",
                "release_id",
                "invocation_id",
            ):
                if record[field] != expected_scope[field]:
                    raise ERRORS["LOCAL_FILE_REF_SCOPE_MISMATCH"]
            normalized[name] = {
                "local_file_ref": reference,
                "access": "read",
            }
        return normalized, binding_device_id

    async def _local_file_select(self, arguments, identity, _trace):
        self._require_file_capability(identity)
        interaction_id = arguments.get("interaction_id")
        selector = arguments.get("selector")
        if (
            not isinstance(interaction_id, str)
            or not 1 <= len(interaction_id) <= 160
            or not isinstance(selector, dict)
            or set(selector)
            - {
                "accept_mime_types",
                "accept_extensions",
                "multiple",
                "min_files",
                "max_files",
                "max_file_size_bytes",
                "max_total_size_bytes",
            }
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        minimum = selector.get("min_files", 1)
        maximum = selector.get("max_files", 1)
        max_file_size = selector.get("max_file_size_bytes", 536_870_912)
        max_total_size = selector.get("max_total_size_bytes", 536_870_912)
        multiple = selector.get("multiple", False)
        mime_types = selector.get("accept_mime_types", [])
        extensions = selector.get("accept_extensions", [])
        if (
            type(minimum) is not int
            or type(maximum) is not int
            or not 1 <= minimum <= maximum <= 20
            or type(max_file_size) is not int
            or type(max_total_size) is not int
            or not 1 <= max_file_size <= max_total_size <= 1_099_511_627_776
            or type(multiple) is not bool
            or (not multiple and maximum != 1)
            or not isinstance(mime_types, list)
            or len(mime_types) > 32
            or not all(
                isinstance(item, str)
                and 3 <= len(item) <= 255
                and MIME_TYPE_PATTERN.fullmatch(item) is not None
                for item in mime_types
            )
            or not isinstance(extensions, list)
            or len(extensions) > 32
            or not all(
                isinstance(item, str)
                and FILE_EXTENSION_PATTERN.fullmatch(item)
                for item in extensions
            )
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        devices = [
            item
            for item in self._online_devices(identity["u"])
            if item.get("protocol_version") == PROTOCOL_VERSION
            and _runner_supports(item, MIN_RUNNER_VERSION)
        ]
        if not devices:
            raise ERRORS["FILE_SELECTOR_DEVICE_OFFLINE"]
        device = devices[0]
        response = await self._request_device(
            device["device_id"],
            {
                "type": "file.select",
                "protocol_version": PROTOCOL_VERSION,
                "interaction_id": interaction_id,
                "selector": selector,
                "scope": self._scope(identity),
            },
        )
        status = response.get("status")
        if status == "cancelled":
            return {"status": "cancelled", "files": []}
        if status != "selected" or not isinstance(response.get("files"), list):
            self._raise_device_file_error(response.get("error_code"))
        files = response["files"]
        if not minimum <= len(files) <= maximum:
            raise ERRORS["FILE_SELECTOR_FILE_COUNT_EXCEEDED"]
        expires_at = int(time.time()) + 3600
        scope = self._scope(identity)
        safe_files = []
        seen_references: set[str] = set()
        total_size = 0
        for item in files:
            if not self._safe_file_metadata(item, device["device_id"]):
                raise ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"]
            if item["local_file_ref"] in seen_references:
                raise ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"]
            seen_references.add(item["local_file_ref"])
            if item["size_bytes"] > max_file_size:
                raise ERRORS["FILE_SELECTOR_FILE_TOO_LARGE"]
            total_size += item["size_bytes"]
            if total_size > max_total_size:
                raise ERRORS["FILE_SELECTOR_FILE_TOO_LARGE"]
            if mime_types and not any(
                self._mime_type_matches(item["mime_type"], accepted)
                for accepted in mime_types
            ):
                raise ERRORS["FILE_SELECTOR_PERMISSION_DENIED"]
            lower_name = item["display_name"].lower()
            if extensions and not any(
                lower_name.endswith(value.lower()) for value in extensions
            ):
                raise ERRORS["FILE_SELECTOR_PERMISSION_DENIED"]
            inserted = self.store.save_local_file_ref(
                item,
                scope=scope,
                interaction_id=interaction_id,
                device_id=device["device_id"],
                expires_at=expires_at,
            )
            if not inserted:
                raise ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"]
            safe_files.append(item)
        return {
            "status": "selected",
            "files": safe_files,
            "expires_at": expires_at,
        }

    async def _local_file_upload(self, arguments, identity, _trace):
        self._require_file_capability(identity)
        reference = arguments.get("local_file_ref")
        upload = arguments.get("upload")
        if (
            not isinstance(reference, str)
            or LOCAL_FILE_REF_PATTERN.fullmatch(reference) is None
            or not isinstance(upload, dict)
            or set(upload)
            - {"url", "method", "headers", "allowed_domains", "max_size_bytes"}
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        url = upload.get("url")
        method = upload.get("method", "PUT")
        domains = upload.get("allowed_domains")
        headers = upload.get("headers", {})
        max_size = upload.get("max_size_bytes")
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (
            parsed is None
            or not 1 <= len(url) <= 8192
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or method not in {"PUT", "POST"}
            or not isinstance(domains, list)
            or not 1 <= len(domains) <= 16
            or not all(
                isinstance(domain, str) and 1 <= len(domain) <= 253
                for domain in domains
            )
            or len(set(domains)) != len(domains)
            or parsed.hostname.lower()
            not in {domain.lower() for domain in domains}
            or not isinstance(headers, dict)
            or len(headers) > 16
            or not all(
                isinstance(name, str)
                and name
                and self._allowed_upload_header(name)
                and isinstance(value, str)
                and len(value) <= 2048
                and "\r" not in value
                and "\n" not in value
                for name, value in headers.items()
            )
            or (
                max_size is not None
                and (
                    type(max_size) is not int
                    or not 1 <= max_size <= 1_099_511_627_776
                )
            )
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        record = self.store.get_local_file_ref(reference)
        self._validate_ref_scope(record, identity)
        self._require_file_device(identity["u"], record["device_id"])
        if max_size is not None and record["size_bytes"] > max_size:
            raise ERRORS["FILE_SELECTOR_FILE_TOO_LARGE"]
        response = await self._request_device(
            record["device_id"],
            {
                "type": "file.upload",
                "protocol_version": PROTOCOL_VERSION,
                "local_file_ref": reference,
                "upload": upload,
                "scope": self._scope(identity),
            },
        )
        if response.get("status") != "uploaded":
            self._raise_device_file_error(response.get("error_code"))
        result = {
            "status": "uploaded",
            "local_file_ref": reference,
            "size_bytes": int(
                response.get("size_bytes") or record["size_bytes"],
            ),
        }
        if response.get("sha256"):
            result["sha256"] = str(response["sha256"])
        return result

    async def _managed_artifacts_list(self, arguments, identity, _trace):
        self._require_file_capability(identity)
        if arguments:
            raise ERRORS["INVALID_ARGUMENTS"]
        devices = self._online_devices(identity["u"])
        for device in devices:
            if device.get(
                "protocol_version",
            ) != PROTOCOL_VERSION or not _runner_supports(
                device,
                MIN_RUNNER_VERSION,
            ):
                continue
            response = await self._request_device(
                device["device_id"],
                {
                    "type": "managed_artifacts.list",
                    "protocol_version": PROTOCOL_VERSION,
                },
            )
            artifacts = response.get("artifacts")
            if isinstance(artifacts, list) and all(
                self._safe_artifact_metadata(item) for item in artifacts
            ):
                self.store.replace_managed_artifacts(
                    str(identity.get("t") or "local"),
                    identity["u"],
                    device["device_id"],
                    artifacts,
                )
        return {
            "artifacts": [
                {
                    key: item[key]
                    for key in (
                        "artifact_id",
                        "device_id",
                        "task_id",
                        "display_name",
                        "mime_type",
                        "size_bytes",
                        "created_at",
                    )
                }
                for item in self.store.list_managed_artifacts(
                    str(identity.get("t") or "local"),
                    identity["u"],
                )
            ],
        }

    async def _managed_artifact_action(self, arguments, identity, _trace):
        self._require_file_capability(identity)
        artifact_id = arguments.get("artifact_id")
        action = arguments.get("action")
        if (
            not isinstance(artifact_id, str)
            or ARTIFACT_ID_PATTERN.fullmatch(artifact_id) is None
            or action not in {"preview", "select", "open_directory", "delete"}
        ):
            raise ERRORS["INVALID_ARGUMENTS"]
        tenant_id = str(identity.get("t") or "local")
        artifact = self.store.get_managed_artifact(
            artifact_id,
            tenant_id,
            identity["u"],
        )
        if artifact is None:
            raise ERRORS["TASK_NOT_FOUND"]
        self._require_file_device(identity["u"], artifact["device_id"])
        response = await self._request_device(
            artifact["device_id"],
            {
                "type": "managed_artifact.action",
                "protocol_version": PROTOCOL_VERSION,
                "artifact_id": artifact_id,
                "action": action,
                "scope": self._scope(identity),
            },
        )
        if response.get("status") != "ok":
            self._raise_device_file_error(response.get("error_code"))
        if action == "delete":
            self.store.delete_managed_artifact(
                artifact_id,
                tenant_id,
                identity["u"],
            )
        result = {"status": "ok", "artifact_id": artifact_id, "action": action}
        if action == "select" and not isinstance(response.get("file"), dict):
            raise ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"]
        if action == "select":
            selected = response["file"]
            if not self._safe_file_metadata(selected, artifact["device_id"]):
                raise ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"]
            expires_at = int(time.time()) + 3600
            inserted = self.store.save_local_file_ref(
                selected,
                scope=self._scope(identity),
                interaction_id=f"managed-artifact:{artifact_id}",
                device_id=artifact["device_id"],
                expires_at=expires_at,
            )
            if not inserted:
                raise ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"]
            result["file"] = selected
            result["expires_at"] = expires_at
        return result

    @staticmethod
    def _safe_file_metadata(value: Any, device_id: str) -> bool:
        return bool(
            isinstance(value, dict)
            and set(value)
            == {
                "local_file_ref",
                "display_name",
                "mime_type",
                "size_bytes",
                "device_id",
                "last_modified_ms",
            }
            and isinstance(value.get("local_file_ref"), str)
            and LOCAL_FILE_REF_PATTERN.fullmatch(value["local_file_ref"])
            and isinstance(value.get("display_name"), str)
            and len(value["display_name"]) <= 255
            and value["display_name"] not in {"", ".", ".."}
            and not any(
                char in value["display_name"] for char in ("/", "\\", "\x00")
            )
            and isinstance(value.get("mime_type"), str)
            and 1 <= len(value["mime_type"]) <= 255
            and type(value.get("size_bytes")) is int
            and 0 <= value["size_bytes"] <= 1_099_511_627_776
            and value.get("device_id") == device_id
            and len(device_id) <= 128
            and type(value.get("last_modified_ms")) is int
            and value["last_modified_ms"] >= 0,
        )

    @staticmethod
    def _safe_artifact_metadata(value: Any) -> bool:
        return bool(
            isinstance(value, dict)
            and set(value)
            == {
                "artifact_id",
                "task_id",
                "display_name",
                "mime_type",
                "size_bytes",
                "created_at",
            }
            and isinstance(value.get("artifact_id"), str)
            and ARTIFACT_ID_PATTERN.fullmatch(value["artifact_id"])
            and isinstance(value.get("task_id"), str)
            and 1 <= len(value["task_id"]) <= 128
            and isinstance(value.get("display_name"), str)
            and 1 <= len(value["display_name"]) <= 255
            and isinstance(value.get("mime_type"), str)
            and 1 <= len(value["mime_type"]) <= 255
            and not any(
                char in value["display_name"] for char in ("/", "\\", "\x00")
            )
            and type(value.get("size_bytes")) is int
            and value["size_bytes"] >= 0
            and type(value.get("created_at")) is int
            and value["created_at"] >= 0,
        )

    @staticmethod
    def _allowed_upload_header(name: str) -> bool:
        normalized = name.lower()
        return normalized in {
            "content-type",
            "content-md5",
        } or normalized.startswith(("x-amz-", "x-oss-", "x-goog-"))

    @staticmethod
    def _mime_type_matches(actual: str, accepted: str) -> bool:
        actual = actual.lower()
        accepted = accepted.lower()
        return actual == accepted or (
            accepted.endswith("/*") and actual.startswith(accepted[:-1])
        )

    def _validate_ref_scope(
        self,
        record: Any,
        identity: dict[str, Any],
    ) -> None:
        if not isinstance(record, dict):
            raise ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"]
        if record["revoked_at"] is not None:
            raise ERRORS["LOCAL_FILE_REF_REVOKED"]
        if int(record["expires_at"]) <= int(time.time()):
            raise ERRORS["LOCAL_FILE_REF_EXPIRED"]
        scope = self._scope(identity)
        for field in (
            "tenant_id",
            "user_id",
            "session_id",
            "agent_id",
            "installation_id",
            "release_id",
            "invocation_id",
        ):
            if record[field] != scope[field]:
                raise ERRORS["LOCAL_FILE_REF_SCOPE_MISMATCH"]

    @staticmethod
    def _raise_device_file_error(code: Any) -> None:
        mapping = {
            error.code: error
            for key, error in ERRORS.items()
            if key.startswith("FILE_SELECTOR_")
            or key.startswith("LOCAL_FILE_REF_")
        }
        raise mapping.get(str(code), ERRORS["LOCAL_FILE_REF_RESOLVE_FAILED"])

    async def _local_task_continue(self, arguments, identity, current_trace):
        task = self._owned_task(arguments.get("task_id"), identity["u"])
        checkpoint_id = arguments.get("checkpoint_id")
        continuation = arguments.get("input")
        local_file_bindings = arguments.get("local_file_bindings")
        if local_file_bindings is None:
            local_file_bindings = {}
        if not isinstance(local_file_bindings, dict):
            raise ERRORS["INVALID_ARGUMENTS"]
        checkpoint = task.get("checkpoint") or {}
        if checkpoint.get("checkpoint_id") != checkpoint_id:
            raise ERRORS["CHECKPOINT_MISMATCH"]
        if task["status"] != "awaiting_input" or not isinstance(
            continuation,
            dict,
        ):
            raise ERRORS["TASK_NOT_ACTIVE"]
        if local_file_bindings:
            self._require_file_capability(identity)
        (
            normalized_bindings,
            binding_device_id,
        ) = self._validate_local_file_bindings(
            local_file_bindings,
            identity=identity,
        )
        if binding_device_id is not None:
            if binding_device_id != task["device_id"]:
                raise ERRORS["LOCAL_FILE_REF_WRONG_DEVICE"]
            self._select_device(
                identity["u"],
                task["capability_id"],
                require_file_support=True,
                required_device_id=task["device_id"],
            )
        command = {
            "type": "task.continue",
            "protocol_version": (
                PROTOCOL_VERSION
                if normalized_bindings
                else self._task_protocol(task, identity["u"])
            ),
            "trace_id": current_trace,
            "task_id": task["task_id"],
            "checkpoint_id": checkpoint_id,
            "input": continuation,
        }
        if normalized_bindings:
            command.update(
                {
                    "local_file_bindings": normalized_bindings,
                    "scope": self._scope(identity),
                },
            )
        await self._send(task["device_id"], command)
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
                task["task_id"],
                asyncio.Event(),
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
                "protocol_version": self._task_protocol(task, identity["u"]),
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

    @staticmethod
    def _valid_aigc_localize_result(
        task: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        files = payload.get("files")
        expected = task.get("input", {}).get("assets")
        if (
            set(payload) != {"files"}
            or not isinstance(files, list)
            or not isinstance(expected, list)
            or len(files) != len(expected)
        ):
            return False
        expected_by_id = {
            item.get("asset_id"): item
            for item in expected
            if isinstance(item, dict) and isinstance(item.get("asset_id"), str)
        }
        result_by_id = {
            item.get("asset_id"): item
            for item in files
            if isinstance(item, dict) and isinstance(item.get("asset_id"), str)
        }
        if (
            len(expected_by_id) != len(expected)
            or len(result_by_id) != len(files)
            or set(result_by_id) != set(expected_by_id)
        ):
            return False
        for asset_id, source in expected_by_id.items():
            result = result_by_id[asset_id]
            if (
                not isinstance(result, dict)
                or set(result) != {
                    "asset_id", "relative_path", "sha256", "size_bytes",
                    "usage", "slot", "order",
                }
                or any(result.get(key) != source.get(key) for key in (
                    "asset_id", "usage", "slot", "order",
                ))
                or not isinstance(result.get("relative_path"), str)
                or result["relative_path"].startswith(("/", "\\"))
                or ".." in result["relative_path"].replace("\\", "/").split("/")
                or (
                    source.get("destination") == "res"
                    and not result["relative_path"].startswith("res/")
                )
                or (
                    source.get("destination") == "task_root"
                    and "/" in result["relative_path"]
                )
                or not isinstance(result.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", result["sha256"]) is None
                or (
                    isinstance(source.get("sha256"), str)
                    and bool(source["sha256"])
                    and result["sha256"] != source["sha256"].lower()
                )
                or not isinstance(result.get("size_bytes"), int)
                or isinstance(result["size_bytes"], bool)
                or result["size_bytes"] < 0
                or (
                    isinstance(source.get("size_bytes"), int)
                    and not isinstance(source["size_bytes"], bool)
                    and source["size_bytes"] > 0
                    and result["size_bytes"] != source["size_bytes"]
                )
            ):
                return False
        return True

    async def handle_device_message(
        self,
        device_id: str,
        user_id: str,
        message: dict[str, Any],
    ) -> None:
        message_type = message.get("type")
        if message_type in {
            "file.select.result",
            "file.upload.result",
            "managed_artifacts.result",
            "managed_artifact.result",
            "aigc.assets.bind.result",
        }:
            request_id = message.get("request_id")
            pending = self._device_requests.get(str(request_id))
            if pending is None:
                return
            expected_device_id, future = pending
            if expected_device_id == device_id and not future.done():
                future.set_result(message)
            return
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
        if task["capability_id"] == "aigc.task.assets.localize/1":
            from .super_agent.local_task_diagnostics import sanitize_localize_event
            payload = sanitize_localize_event(event_type, payload)
        if not self.store.append_event(task_id, sequence, event_type, payload):
            return
        schema_name = {
            "checkpoint": "checkpoint",
            "completed": "result",
        }.get(event_type)
        if schema_name:
            package = self.store.get_package_for_capability(
                task["capability_id"],
            )
            schema = (
                package["descriptor"]["schemas"][schema_name]["document"]
                if package
                else None
            )
            built_in_localize_result = (
                task["capability_id"] == "aigc.task.assets.localize/1"
                and event_type == "completed"
                and self._valid_aigc_localize_result(task, payload)
            )
            if not built_in_localize_result and (
                schema is None or list(
                    Draft202012Validator(schema).iter_errors(payload),
                )
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
