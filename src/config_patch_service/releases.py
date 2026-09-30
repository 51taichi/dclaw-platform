"""Immutable releases and stable baseline export orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from .audit import AuditService
from .db import ConfigPatchDatabase
from .models import (
    DclawConfigurationContext,
    DclawSnapshotArchive,
    OmnichannelBotSnapshot,
)
from .upstreams import (
    UpstreamBootstrapRequiredError,
    UpstreamContractError,
)

if TYPE_CHECKING:
    from .bundles import BuiltWorkspaceBundle, WorkspaceBundleBuilder
    from .upstreams.dclaw import DclawClient
    from .upstreams.omnichannel import OmnichannelClient


BaselineSource = Literal["initial_baseline", "external_baseline"]
_UNSET = object()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class BaselineExportError(RuntimeError):
    def __init__(
        self, code: str, *, missing_items: list[str] | None = None
    ) -> None:
        self.code = code
        self.missing_items = _unique(missing_items or [])
        super().__init__(code)


class ReleaseConflictError(RuntimeError):
    """The release head changed after the caller read its export sources."""


class ContentAddressedObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes) -> str:
        data = bytes(content)
        digest = hashlib.sha256(data).hexdigest()
        relative = PurePosixPath("sha256", digest[:2], digest).as_posix()
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise OSError("content-addressed object digest mismatch")
            return relative

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            directory_descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary.unlink(missing_ok=True)
        return relative

    def get(self, object_key: str) -> bytes:
        relative = PurePosixPath(object_key)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise ValueError("invalid object key")
        target = (self.root / relative.as_posix()).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("invalid object key")
        return target.read_bytes()


@dataclass(frozen=True)
class AggregatedSnapshot:
    omnichannel: OmnichannelBotSnapshot
    dclaw: DclawSnapshotArchive
    snapshot_digest: str
    component_digests: dict[str, str]

    @classmethod
    def from_sources(
        cls,
        *,
        omnichannel: OmnichannelBotSnapshot,
        dclaw: DclawSnapshotArchive,
    ) -> "AggregatedSnapshot":
        if omnichannel.agent.agent_id != dclaw.agent_id:
            raise BaselineExportError("TARGET_BINDING_CHANGED")
        components = {
            "agent": dclaw.agent_digest,
            "knowledge": dclaw.knowledge_digest,
            "flowMachine": omnichannel.digests.get("flowMachine", ""),
            "tags": omnichannel.digests.get("tags", ""),
        }
        if any(not value for value in components.values()):
            raise BaselineExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                missing_items=["source_fingerprints"],
            )
        identity = {
            "botId": omnichannel.bot.bot_id,
            "agentId": dclaw.agent_id,
            "agentProfileId": dclaw.profile_id,
            "sourceVersion": dclaw.source_version,
            "components": components,
        }
        return cls(
            omnichannel=omnichannel,
            dclaw=dclaw,
            snapshot_digest=_sha256(_canonical_json(identity)),
            component_digests=components,
        )


@dataclass(frozen=True)
class ConfigurationRelease:
    bot_id: str
    release_id: str
    version: int
    source: BaselineSource
    actor_token_id: str
    bot_name: str
    agent_id: str
    agent_profile_id: str
    source_version: str
    snapshot_digest: str
    component_digests: dict[str, str]
    omnichannel_snapshot_object_key: str
    dclaw_snapshot_object_key: str
    created_at: datetime


class ReleaseRepository:
    def __init__(
        self,
        database: ConfigPatchDatabase,
        *,
        object_store: ContentAddressedObjectStore,
        audit: AuditService,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._database = database
        self.object_store = object_store
        self._audit = audit
        self._clock = clock

    @staticmethod
    def _release(row) -> ConfigurationRelease:
        return ConfigurationRelease(
            bot_id=row["bot_id"],
            release_id=row["release_id"],
            version=int(row["version"]),
            source=row["source"],
            actor_token_id=row["actor_token_id"],
            bot_name=row["bot_name"],
            agent_id=row["agent_id"],
            agent_profile_id=row["agent_profile_id"],
            source_version=row["source_version"],
            snapshot_digest=row["snapshot_digest"],
            component_digests=json.loads(row["component_digests_json"]),
            omnichannel_snapshot_object_key=row[
                "omnichannel_snapshot_object_key"
            ],
            dclaw_snapshot_object_key=row["dclaw_snapshot_object_key"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def create_or_get_baseline(
        self,
        snapshot: AggregatedSnapshot,
        *,
        actor_token_id: str,
        source: BaselineSource,
        expected_previous_snapshot_digest: str | None | object = _UNSET,
    ) -> ConfigurationRelease:
        omni_bytes = _canonical_json(
            snapshot.omnichannel.model_dump(by_alias=True, mode="json"),
        )
        omni_key = self.object_store.put(omni_bytes)
        dclaw_key = self.object_store.put(snapshot.dclaw.archive)
        bot_id = snapshot.omnichannel.bot.bot_id
        created = False
        previous_release_id: str | None = None
        with self._database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT * FROM configuration_releases
                WHERE bot_id = ? AND snapshot_digest = ?
                """,
                (bot_id, snapshot.snapshot_digest),
            ).fetchone()
            if existing is not None:
                return self._release(existing)

            latest = connection.execute(
                """
                SELECT * FROM configuration_releases
                WHERE bot_id = ? ORDER BY version DESC LIMIT 1
                """,
                (bot_id,),
            ).fetchone()
            actual_previous_digest = (
                latest["snapshot_digest"] if latest is not None else None
            )
            if (
                expected_previous_snapshot_digest is not _UNSET
                and actual_previous_digest
                != expected_previous_snapshot_digest
            ):
                raise ReleaseConflictError("release baseline changed")
            version = int(latest["version"]) + 1 if latest else 1
            previous_release_id = latest["release_id"] if latest else None
            expected_source = (
                "external_baseline" if latest else "initial_baseline"
            )
            if source != expected_source:
                raise ReleaseConflictError(
                    f"baseline source must be {expected_source}"
                )
            release_id = f"R{version}"
            created_at = self._clock().astimezone(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO configuration_releases (
                    row_id, bot_id, release_id, version, source,
                    actor_token_id,
                    bot_name, agent_id, agent_profile_id, source_version,
                    snapshot_digest, component_digests_json,
                    omnichannel_snapshot_object_key, dclaw_snapshot_object_key,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    bot_id,
                    release_id,
                    version,
                    source,
                    actor_token_id,
                    snapshot.omnichannel.bot.bot_name,
                    snapshot.dclaw.agent_id,
                    snapshot.dclaw.profile_id,
                    snapshot.dclaw.source_version,
                    snapshot.snapshot_digest,
                    json.dumps(snapshot.component_digests, sort_keys=True),
                    omni_key,
                    dclaw_key,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM configuration_releases
                WHERE bot_id = ? AND release_id = ?
                """,
                (bot_id, release_id),
            ).fetchone()
            created = True

        release = self._release(row)
        if created:
            self._audit.record(
                "release.baseline.create",
                token_id=actor_token_id,
                result="success",
                metadata={
                    "botId": bot_id,
                    "releaseId": release.release_id,
                    "source": source,
                    "snapshotDigest": snapshot.snapshot_digest,
                },
            )
            if previous_release_id is not None:
                self._audit.record(
                    "release.external_drift",
                    token_id=actor_token_id,
                    result="success",
                    metadata={
                        "botId": bot_id,
                        "fromReleaseId": previous_release_id,
                        "toReleaseId": release.release_id,
                    },
                )
        return release

    def list_for_bot(self, bot_id: str) -> list[ConfigurationRelease]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM configuration_releases
                WHERE bot_id = ? ORDER BY version ASC
                """,
                (bot_id,),
            ).fetchall()
        return [self._release(row) for row in rows]

    def get(self, bot_id: str, release_id: str) -> ConfigurationRelease | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM configuration_releases
                WHERE bot_id = ? AND release_id = ?
                """,
                (bot_id, release_id),
            ).fetchone()
        return self._release(row) if row is not None else None

    def latest(self, bot_id: str) -> ConfigurationRelease | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM configuration_releases
                WHERE bot_id = ? ORDER BY version DESC LIMIT 1
                """,
                (bot_id,),
            ).fetchone()
        return self._release(row) if row is not None else None


def _dclaw_context_fingerprint(context: DclawConfigurationContext) -> bytes:
    return _canonical_json(context.model_dump(by_alias=True, mode="json"))


def _dclaw_snapshot_fingerprint(snapshot: DclawSnapshotArchive) -> bytes:
    return _canonical_json(
        {
            "agentId": snapshot.agent_id,
            "profileId": snapshot.profile_id,
            "sourceVersion": snapshot.source_version,
            "agentDigest": snapshot.agent_digest,
            "knowledgeDigest": snapshot.knowledge_digest,
            "archiveDigest": _sha256(snapshot.archive),
        }
    )


def _omnichannel_configuration_fingerprint(
    snapshot: OmnichannelBotSnapshot,
) -> bytes:
    return _canonical_json(
        {
            "bot": snapshot.bot.model_dump(by_alias=True, mode="json"),
            "agent": snapshot.agent.model_dump(by_alias=True, mode="json"),
            "flowMachine": snapshot.digests.get("flowMachine"),
            "tags": snapshot.digests.get("tags"),
        },
    )


class BaselineExportService:
    def __init__(
        self,
        *,
        omnichannel: "OmnichannelClient",
        dclaw: "DclawClient",
        releases: ReleaseRepository,
        bundle_builder: "WorkspaceBundleBuilder",
    ) -> None:
        self._omnichannel = omnichannel
        self._dclaw = dclaw
        self._releases = releases
        self._bundle_builder = bundle_builder

    def export(
        self,
        bot_id: str,
        *,
        actor_token_id: str,
        correlation_id: str,
    ) -> "BuiltWorkspaceBundle":
        expected_previous = self._releases.latest(bot_id)
        expected_previous_digest = (
            expected_previous.snapshot_digest
            if expected_previous is not None
            else None
        )
        first_omni = self._omnichannel.get_bot_snapshot(
            bot_id,
            correlation_id=correlation_id,
        )
        if (
            not first_omni.agent.agent_id
            or not first_omni.agent.dclaw.base_url
        ):
            raise BaselineExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                missing_items=first_omni.readiness.missing_items,
            )
        first_context = self._dclaw.get_context(
            first_omni.agent.dclaw.base_url,
            first_omni.agent.agent_id,
            correlation_id=correlation_id,
        )
        if (
            first_context.agent_id != first_omni.agent.agent_id
            or first_context.openapi_public_id
            != first_omni.agent.dclaw.public_id
        ):
            raise BaselineExportError("TARGET_BINDING_CHANGED")
        missing = _unique(
            first_omni.readiness.missing_items
            + first_context.readiness.missing_items,
        )
        if missing:
            raise BaselineExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                missing_items=missing,
            )
        try:
            first_dclaw_snapshot = self._dclaw.download_snapshot(
                first_omni.agent.dclaw.base_url,
                first_omni.agent.agent_id,
                correlation_id=correlation_id,
            )
        except UpstreamBootstrapRequiredError as exc:
            raise BaselineExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                missing_items=exc.missing_items,
            ) from exc

        second_omni = self._omnichannel.get_bot_snapshot(
            bot_id,
            correlation_id=correlation_id,
        )
        if (
            second_omni.agent.agent_id != first_omni.agent.agent_id
            or second_omni.agent.dclaw.base_url
            != first_omni.agent.dclaw.base_url
        ):
            raise BaselineExportError("TARGET_BINDING_CHANGED")
        if _omnichannel_configuration_fingerprint(
            first_omni
        ) != _omnichannel_configuration_fingerprint(second_omni):
            raise BaselineExportError("OMNICHANNEL_CONFIGURATION_CHANGED")

        second_context = self._dclaw.get_context(
            second_omni.agent.dclaw.base_url,
            second_omni.agent.agent_id,
            correlation_id=correlation_id,
        )
        if (
            second_context.agent_id != second_omni.agent.agent_id
            or second_context.openapi_public_id
            != second_omni.agent.dclaw.public_id
        ):
            raise BaselineExportError("TARGET_BINDING_CHANGED")
        try:
            second_dclaw_snapshot = self._dclaw.download_snapshot(
                second_omni.agent.dclaw.base_url,
                second_omni.agent.agent_id,
                correlation_id=correlation_id,
            )
        except UpstreamBootstrapRequiredError as exc:
            raise BaselineExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                missing_items=exc.missing_items,
            ) from exc
        if (
            _dclaw_context_fingerprint(first_context)
            != _dclaw_context_fingerprint(second_context)
            or _dclaw_snapshot_fingerprint(first_dclaw_snapshot)
            != _dclaw_snapshot_fingerprint(second_dclaw_snapshot)
            or second_dclaw_snapshot.agent_id != second_context.agent_id
            or second_dclaw_snapshot.profile_id
            != second_context.agent_profile_id
            or second_dclaw_snapshot.source_version
            != second_context.source_version
        ):
            raise BaselineExportError("DCLAW_SOURCE_CHANGED")

        snapshot = AggregatedSnapshot.from_sources(
            omnichannel=second_omni,
            dclaw=second_dclaw_snapshot,
        )
        try:
            self._bundle_builder.validate_snapshot(snapshot)
        except ValueError as exc:
            raise UpstreamContractError(
                "DCLAW_SNAPSHOT_CONTRACT_INVALID"
            ) from exc
        source: BaselineSource = (
            "external_baseline"
            if expected_previous is not None
            else "initial_baseline"
        )
        try:
            release = self._releases.create_or_get_baseline(
                snapshot,
                actor_token_id=actor_token_id,
                source=source,
                expected_previous_snapshot_digest=expected_previous_digest,
            )
        except ReleaseConflictError as exc:
            raise BaselineExportError("BASELINE_CHANGED_RETRY") from exc
        return self._bundle_builder.build(release)
