# -*- coding: utf-8 -*-
"""Atomic persistence and state transitions for basic interaction cards."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from ..storage.json_file_lock import JsonFileLock
from .interaction_contract import (
    InteractionAnswer,
    InteractionCard,
    InteractionComponentType,
    InteractionCreateRequest,
    InteractionInputPolicy,
    InteractionLocalFile,
    InteractionResolvedAnswer,
    InteractionResolvedOption,
    InteractionStatus,
    MultiSelectCard,
    FileSelectorCard,
    QuestionFormCard,
    SingleSelectCard,
    validate_card,
)


class InteractionError(ValueError):
    """Public-safe interaction failure with a stable machine code."""

    def __init__(
        self,
        code: str,
        *,
        field: str | None = None,
        retryable: bool = True,
        guidance: str = "",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.field = field
        self.retryable = retryable
        self.guidance = guidance


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InteractionBinding(_StrictFrozenModel):
    installation_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    agent_task_id: str = Field(min_length=1)


class InteractionTransition(_StrictFrozenModel):
    event_id: str = Field(min_length=1)
    action: Literal["create", "replace", "cancel", "expire", "submit"]
    from_status: InteractionStatus | None
    to_status: InteractionStatus
    occurred_at: datetime


class InteractionCardRecord(_StrictFrozenModel):
    interaction_id: str = Field(min_length=1)
    binding: InteractionBinding
    task_key: str = Field(min_length=1, max_length=160)
    interaction_revision: int = Field(ge=1)
    component_type: InteractionComponentType
    input_policy: InteractionInputPolicy
    card: InteractionCard
    status: InteractionStatus
    version: int = Field(ge=1)
    transitions: tuple[InteractionTransition, ...]
    answer: InteractionAnswer | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def parse_exact_card(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        component_type = value.get("component_type")
        if isinstance(component_type, InteractionComponentType):
            component_type = component_type.value
        card = value.get("card")
        if isinstance(
            card,
            (
                SingleSelectCard,
                MultiSelectCard,
                QuestionFormCard,
                FileSelectorCard,
            ),
        ):
            return value
        return {
            **value,
            "card": validate_card(str(component_type or ""), card),
        }


class _OperationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_digest: str
    interaction_id: str


class _InteractionDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    cards: dict[str, InteractionCardRecord] = Field(default_factory=dict)
    operations: dict[str, _OperationRecord] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_continuation_state(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "continuation_receipts" not in value:
            return value
        migrated = dict(value)
        migrated.pop("continuation_receipts", None)
        return migrated


def _identity(*parts: Any) -> str:
    encoded = json.dumps(
        parts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _operation_digest(action: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"action": action, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InteractionError(
            "INVALID_INTERACTION_REQUEST",
            field="expires_at",
            guidance="Use an RFC 3339 timestamp with a timezone.",
        )
    return value.astimezone(timezone.utc)


class InteractionCardRepository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "interaction_cards.json"
        self._lock = threading.RLock()
        self._file_lock = JsonFileLock(self.root)

    def create(
        self,
        *,
        installation_id: str,
        conversation_id: str,
        request: InteractionCreateRequest,
        idempotency_key: str,
        now: datetime,
    ) -> InteractionCardRecord:
        now = _utc(now)
        if not idempotency_key:
            raise InteractionError(
                "INVALID_OPERATION_KEY",
                field="idempotency_key",
            )
        request_payload = request.model_dump(mode="json")
        operation_payload = {
            "installation_id": installation_id,
            "conversation_id": conversation_id,
            "request": request_payload,
        }
        digest = _operation_digest("create", operation_payload)
        with self._lock, self._file_lock.hold(self.path):
            document = self._read()
            dirty = self._expire(document, now)
            replay = self._replay(document, idempotency_key, digest)
            if replay is not None:
                if dirty:
                    self._write(document)
                return replay

            interaction_id = "interaction-" + _identity(
                installation_id,
                conversation_id,
                request.task_key,
                request.interaction_revision,
            )
            existing = document.cards.get(interaction_id)
            if existing is not None:
                expected = self._create_fingerprint(existing)
                candidate = self._request_fingerprint(
                    installation_id,
                    conversation_id,
                    request,
                )
                if expected != candidate:
                    raise InteractionError(
                        "IDEMPOTENCY_CONFLICT",
                        retryable=False,
                    )
                document.operations[idempotency_key] = _OperationRecord(
                    operation_digest=digest,
                    interaction_id=interaction_id,
                )
                self._write(document)
                return existing

            active = self._active_blocking(
                document,
                installation_id=installation_id,
                conversation_id=conversation_id,
            )
            replacement = request.replaces_interaction_id
            if active is not None:
                if replacement != active.interaction_id:
                    raise InteractionError(
                        "ACTIVE_BLOCKING_INTERACTION_EXISTS",
                        guidance=(
                            "Cancel the active card or pass its exact ID in "
                            "replaces_interaction_id."
                        ),
                    )
                replaced = self._transition(
                    active,
                    action="replace",
                    target=InteractionStatus.REPLACED,
                    event_id="replace-"
                    + _identity(idempotency_key, active.interaction_id),
                    now=now,
                )
                document.cards[active.interaction_id] = replaced
            elif replacement:
                raise InteractionError(
                    "INTERACTION_NOT_PENDING",
                    field="replaces_interaction_id",
                )

            expires_at = (
                _utc(request.expires_at) if request.expires_at else None
            )
            if expires_at is not None and expires_at <= now:
                raise InteractionError(
                    "INVALID_INTERACTION_REQUEST",
                    field="expires_at",
                    guidance="expires_at must be in the future.",
                )
            binding = InteractionBinding(
                installation_id=installation_id,
                conversation_id=conversation_id,
                agent_task_id="interaction-task-"
                + _identity(
                    installation_id,
                    conversation_id,
                    request.task_key,
                ),
            )
            event = InteractionTransition(
                event_id="create-"
                + _identity(idempotency_key, interaction_id),
                action="create",
                from_status=None,
                to_status=InteractionStatus.PENDING,
                occurred_at=now,
            )
            card = InteractionCardRecord(
                interaction_id=interaction_id,
                binding=binding,
                task_key=request.task_key,
                interaction_revision=request.interaction_revision,
                component_type=request.component_type,
                input_policy=request.input_policy,
                card=request.card,
                status=InteractionStatus.PENDING,
                version=1,
                transitions=(event,),
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            document.cards[interaction_id] = card
            document.operations[idempotency_key] = _OperationRecord(
                operation_digest=digest,
                interaction_id=interaction_id,
            )
            self._write(document)
            return card

    def cancel(
        self,
        *,
        interaction_id: str,
        installation_id: str,
        conversation_id: str,
        operation_key: str,
        now: datetime,
    ) -> InteractionCardRecord:
        now = _utc(now)
        payload = {
            "interaction_id": interaction_id,
            "installation_id": installation_id,
            "conversation_id": conversation_id,
        }
        digest = _operation_digest("cancel", payload)
        with self._lock, self._file_lock.hold(self.path):
            document = self._read()
            dirty = self._expire(document, now)
            replay = self._replay(document, operation_key, digest)
            if replay is not None:
                if dirty:
                    self._write(document)
                return replay
            current = self._owned(
                document,
                interaction_id,
                installation_id,
                conversation_id,
            )
            if current.status is not InteractionStatus.PENDING:
                raise InteractionError("INTERACTION_NOT_PENDING")
            result = self._transition(
                current,
                action="cancel",
                target=InteractionStatus.CANCELLED,
                event_id="cancel-" + _identity(operation_key, interaction_id),
                now=now,
            )
            document.cards[interaction_id] = result
            document.operations[operation_key] = _OperationRecord(
                operation_digest=digest,
                interaction_id=interaction_id,
            )
            self._write(document)
            return result

    def submit(
        self,
        *,
        interaction_id: str,
        installation_id: str,
        conversation_id: str,
        version: int,
        idempotency_key: str,
        now: datetime,
        selected: list[dict[str, Any]] | None = None,
        supplement: str | None = None,
        answers: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> InteractionCardRecord:
        now = _utc(now)
        payload = {
            "interaction_id": interaction_id,
            "installation_id": installation_id,
            "conversation_id": conversation_id,
            "version": version,
            "selected": selected,
            "supplement": supplement,
            "answers": answers,
            "files": files,
        }
        digest = _operation_digest("submit", payload)
        with self._lock, self._file_lock.hold(self.path):
            document = self._read()
            dirty = self._expire(document, now)
            replay = self._replay(document, idempotency_key, digest)
            if replay is not None:
                if dirty:
                    self._write(document)
                return replay
            current = self._owned(
                document,
                interaction_id,
                installation_id,
                conversation_id,
            )
            if current.status is not InteractionStatus.PENDING:
                raise InteractionError("INTERACTION_NOT_PENDING")
            if type(version) is not int or current.version != version:
                raise InteractionError(
                    "INTERACTION_VERSION_CONFLICT",
                    field="version",
                )
            if (
                current.component_type
                is InteractionComponentType.FILE_SELECTOR
            ):
                if (
                    selected is not None
                    or supplement is not None
                    or answers is not None
                ):
                    raise InteractionError(
                        "INVALID_INTERACTION_REQUEST",
                        field="files",
                    )
                answer = InteractionAnswer(
                    interaction_id=interaction_id,
                    component_type=current.component_type,
                    files=self._resolve_files(current, files),
                    submitted_at=now,
                )
            elif (
                current.component_type
                is InteractionComponentType.QUESTION_FORM
            ):
                if (
                    selected is not None
                    or supplement is not None
                    or files is not None
                ):
                    raise InteractionError(
                        "INVALID_INTERACTION_REQUEST",
                        field="files"
                        if files is not None
                        else (
                            "selected"
                            if selected is not None
                            else "supplement"
                        ),
                    )
                resolved_answers = self._resolve_answers(current, answers)
                answer = InteractionAnswer(
                    interaction_id=interaction_id,
                    component_type=current.component_type,
                    answers=resolved_answers,
                    submitted_at=now,
                )
            else:
                if answers is not None or files is not None:
                    raise InteractionError(
                        "INVALID_INTERACTION_REQUEST",
                        field="files" if files is not None else "answers",
                    )
                resolved = self._resolve_selection(current, selected)
                normalized_supplement = self._validate_supplement(
                    current,
                    supplement,
                )
                answer = InteractionAnswer(
                    interaction_id=interaction_id,
                    component_type=current.component_type,
                    selected=tuple(resolved),
                    supplement=normalized_supplement,
                    submitted_at=now,
                )
            event = InteractionTransition(
                event_id="submit-"
                + _identity(idempotency_key, interaction_id),
                action="submit",
                from_status=current.status,
                to_status=InteractionStatus.SUBMITTED,
                occurred_at=now,
            )
            result = current.model_copy(
                update={
                    "status": InteractionStatus.SUBMITTED,
                    "version": current.version + 1,
                    "answer": answer,
                    "transitions": (*current.transitions, event),
                    "updated_at": now,
                },
            )
            document.cards[interaction_id] = result
            document.operations[idempotency_key] = _OperationRecord(
                operation_digest=digest,
                interaction_id=interaction_id,
            )
            self._write(document)
            return result

    def get_owned(
        self,
        interaction_id: str,
        *,
        installation_id: str,
        conversation_id: str,
        now: datetime,
    ) -> InteractionCardRecord:
        now = _utc(now)
        with self._lock, self._file_lock.hold(self.path):
            document = self._read()
            dirty = self._expire(document, now)
            result = self._owned(
                document,
                interaction_id,
                installation_id,
                conversation_id,
            )
            if dirty:
                self._write(document)
            return result

    def list_owned(
        self,
        *,
        installation_id: str,
        conversation_ids: set[str],
        now: datetime,
    ) -> tuple[InteractionCardRecord, ...]:
        now = _utc(now)
        with self._lock, self._file_lock.hold(self.path):
            document = self._read()
            dirty = self._expire(document, now)
            result = tuple(
                card
                for card in document.cards.values()
                if card.binding.installation_id == installation_id
                and card.binding.conversation_id in conversation_ids
            )
            if dirty:
                self._write(document)
            return result

    def resolve_for_authorization(
        self,
        interaction_id: str,
        *,
        now: datetime,
    ) -> InteractionCardRecord:
        """Resolve identity only; callers must authorize its persisted binding."""
        now = _utc(now)
        with self._lock, self._file_lock.hold(self.path):
            document = self._read()
            dirty = self._expire(document, now)
            result = document.cards.get(interaction_id)
            if dirty:
                self._write(document)
            if result is None:
                raise InteractionError("INTERACTION_NOT_FOUND")
            return result

    def _replay(
        self,
        document: _InteractionDocument,
        operation_key: str,
        digest: str,
    ) -> InteractionCardRecord | None:
        if not operation_key:
            raise InteractionError(
                "INVALID_OPERATION_KEY",
                field="idempotency_key",
            )
        existing = document.operations.get(operation_key)
        if existing is None:
            return None
        if existing.operation_digest != digest:
            raise InteractionError("IDEMPOTENCY_CONFLICT", retryable=False)
        result = document.cards.get(existing.interaction_id)
        if result is None:
            raise InteractionError(
                "INTERACTION_REPOSITORY_INVALID",
                retryable=False,
            )
        return result

    @staticmethod
    def _owned(
        document: _InteractionDocument,
        interaction_id: str,
        installation_id: str,
        conversation_id: str,
    ) -> InteractionCardRecord:
        card = document.cards.get(interaction_id)
        if (
            card is None
            or card.binding.installation_id != installation_id
            or card.binding.conversation_id != conversation_id
        ):
            raise InteractionError("INTERACTION_NOT_FOUND")
        return card

    @staticmethod
    def _active_blocking(
        document: _InteractionDocument,
        *,
        installation_id: str,
        conversation_id: str,
    ) -> InteractionCardRecord | None:
        for card in document.cards.values():
            if (
                card.binding.installation_id == installation_id
                and card.binding.conversation_id == conversation_id
                and card.status is InteractionStatus.PENDING
                and card.input_policy is InteractionInputPolicy.CARD_ONLY
            ):
                return card
        return None

    @staticmethod
    def _transition(
        card: InteractionCardRecord,
        *,
        action: Literal["replace", "cancel", "expire"],
        target: InteractionStatus,
        event_id: str,
        now: datetime,
    ) -> InteractionCardRecord:
        event = InteractionTransition(
            event_id=event_id,
            action=action,
            from_status=card.status,
            to_status=target,
            occurred_at=now,
        )
        return card.model_copy(
            update={
                "status": target,
                "version": card.version + 1,
                "transitions": (*card.transitions, event),
                "updated_at": now,
            },
        )

    def _expire(self, document: _InteractionDocument, now: datetime) -> bool:
        dirty = False
        for interaction_id, card in tuple(document.cards.items()):
            if (
                card.status is InteractionStatus.PENDING
                and card.expires_at is not None
                and _utc(card.expires_at) <= now
            ):
                document.cards[interaction_id] = self._transition(
                    card,
                    action="expire",
                    target=InteractionStatus.EXPIRED,
                    event_id="expire-"
                    + _identity(interaction_id, card.version),
                    now=now,
                )
                dirty = True
        return dirty

    @staticmethod
    def _resolve_selection(
        record: InteractionCardRecord,
        selected: Any,
    ) -> tuple[InteractionResolvedOption, ...]:
        if not isinstance(selected, list):
            raise InteractionError("INVALID_SELECTION", field="selected")
        resolved: list[InteractionResolvedOption] = []
        seen: set[tuple[str | None, str]] = set()
        for index, reference in enumerate(selected):
            if not isinstance(reference, dict):
                raise InteractionError(
                    "INVALID_SELECTION",
                    field=f"selected[{index}]",
                )
            option_id = reference.get("id")
            option_text = reference.get("text")
            option = None
            if isinstance(option_id, str) and option_id.strip():
                option = next(
                    (
                        candidate
                        for candidate in record.card.options
                        if candidate.id == option_id.strip()
                    ),
                    None,
                )
            elif isinstance(option_text, str) and option_text.strip():
                option = next(
                    (
                        candidate
                        for candidate in record.card.options
                        if candidate.text == option_text.strip()
                    ),
                    None,
                )
            if option is None:
                raise InteractionError(
                    "INVALID_SELECTION",
                    field=f"selected[{index}]",
                )
            identity = (option.id, option.text)
            if identity in seen:
                raise InteractionError("INVALID_SELECTION", field="selected")
            seen.add(identity)
            resolved.append(
                InteractionResolvedOption(id=option.id, text=option.text),
            )
        count = len(resolved)
        if record.component_type is InteractionComponentType.SINGLE_SELECT:
            valid = count == 1
        else:
            card = record.card
            valid = card.min_selections <= count <= card.max_selections
        if not valid:
            raise InteractionError("INVALID_SELECTION", field="selected")
        return tuple(resolved)

    @staticmethod
    def _resolve_files(
        record: InteractionCardRecord,
        files: Any,
    ) -> tuple[InteractionLocalFile, ...]:
        if not isinstance(files, list):
            raise InteractionError(
                "INVALID_INTERACTION_REQUEST",
                field="files",
            )
        card = record.card
        if not card.min_files <= len(files) <= card.max_files:
            raise InteractionError(
                "FILE_SELECTOR.FILE_COUNT_EXCEEDED",
                field="files",
            )
        resolved: list[InteractionLocalFile] = []
        seen: set[str] = set()
        total_size = 0
        for index, value in enumerate(files):
            try:
                item = InteractionLocalFile.model_validate(value)
            except ValidationError as exc:
                raise InteractionError(
                    "INVALID_INTERACTION_REQUEST",
                    field=f"files[{index}]",
                ) from exc
            if item.local_file_ref in seen:
                raise InteractionError(
                    "INVALID_INTERACTION_REQUEST",
                    field="files",
                )
            if item.size_bytes > card.max_file_size_bytes:
                raise InteractionError(
                    "FILE_SELECTOR.FILE_TOO_LARGE",
                    field=f"files[{index}].size_bytes",
                )
            mime_type = item.mime_type.lower()
            if card.accept_mime_types and not any(
                mime_type == accepted
                or (
                    accepted.endswith("/*")
                    and mime_type.startswith(accepted[:-1])
                )
                for accepted in card.accept_mime_types
            ):
                raise InteractionError(
                    "FILE_SELECTOR.PERMISSION_DENIED",
                    field=f"files[{index}].mime_type",
                )
            name = item.display_name.lower()
            if card.accept_extensions and not any(
                name.endswith(extension)
                for extension in card.accept_extensions
            ):
                raise InteractionError(
                    "FILE_SELECTOR.PERMISSION_DENIED",
                    field=f"files[{index}].display_name",
                )
            seen.add(item.local_file_ref)
            total_size += item.size_bytes
            resolved.append(item)
        if total_size > card.max_total_size_bytes:
            raise InteractionError(
                "FILE_SELECTOR.FILE_TOO_LARGE",
                field="files",
            )
        return tuple(resolved)

    @staticmethod
    def _validate_supplement(
        record: InteractionCardRecord,
        supplement: Any,
    ) -> str | None:
        config = record.card.supplement
        if supplement is not None and not isinstance(supplement, str):
            raise InteractionError(
                "INVALID_INTERACTION_REQUEST",
                field="supplement",
            )
        normalized = supplement.strip() if isinstance(supplement, str) else ""
        if not config.enabled:
            if normalized:
                raise InteractionError(
                    "INVALID_INTERACTION_REQUEST",
                    field="supplement",
                )
            return None
        if config.required and not normalized:
            raise InteractionError("SUPPLEMENT_REQUIRED", field="supplement")
        if len(normalized) > config.max_length:
            raise InteractionError(
                "INVALID_INTERACTION_REQUEST",
                field="supplement",
            )
        return normalized or None

    @staticmethod
    def _resolve_answers(
        record: InteractionCardRecord,
        answers: Any,
    ) -> tuple[InteractionResolvedAnswer, ...]:
        if not isinstance(answers, list):
            raise InteractionError("INVALID_ANSWER_REFERENCE", field="answers")
        card = record.card
        if not isinstance(card, QuestionFormCard):
            raise InteractionError(
                "INVALID_INTERACTION_REQUEST",
                field="answers",
            )
        supplied: dict[tuple[str | None, str], str | None] = {}
        for index, reference in enumerate(answers):
            field = f"answers[{index}]"
            if not isinstance(reference, dict) or not set(reference).issubset(
                {"id", "question", "value"},
            ):
                raise InteractionError("INVALID_ANSWER_REFERENCE", field=field)
            item_id = reference.get("id")
            question = reference.get("question")
            item = None
            if isinstance(item_id, str) and item_id.strip():
                item = next(
                    (
                        candidate
                        for candidate in card.items
                        if candidate.id == item_id.strip()
                    ),
                    None,
                )
            elif isinstance(question, str) and question.strip():
                item = next(
                    (
                        candidate
                        for candidate in card.items
                        if candidate.question == question.strip()
                    ),
                    None,
                )
            if item is None:
                raise InteractionError("INVALID_ANSWER_REFERENCE", field=field)
            identity = (item.id, item.question)
            if identity in supplied:
                raise InteractionError("INVALID_ANSWER_REFERENCE", field=field)
            value = reference.get("value")
            if value is not None and not isinstance(value, str):
                raise InteractionError("INVALID_ANSWER_REFERENCE", field=field)
            normalized = value.strip() if isinstance(value, str) else ""
            if len(normalized) > item.max_length:
                raise InteractionError(
                    "ANSWER_TOO_LONG",
                    field=f"{field}.value",
                )
            supplied[identity] = normalized or None

        resolved: list[InteractionResolvedAnswer] = []
        for index, item in enumerate(card.items):
            identity = (item.id, item.question)
            value = supplied.get(identity)
            if item.required and value is None:
                raise InteractionError(
                    "REQUIRED_ANSWER_MISSING",
                    field=f"answers[{index}]",
                )
            resolved.append(
                InteractionResolvedAnswer(
                    id=item.id,
                    question=item.question,
                    value=value,
                ),
            )
        return tuple(resolved)

    @staticmethod
    def _request_fingerprint(
        installation_id: str,
        conversation_id: str,
        request: InteractionCreateRequest,
    ) -> str:
        return _operation_digest(
            "semantic-create",
            {
                "installation_id": installation_id,
                "conversation_id": conversation_id,
                "request": request.model_dump(mode="json"),
            },
        )

    @staticmethod
    def _create_fingerprint(card: InteractionCardRecord) -> str:
        request = InteractionCreateRequest(
            task_key=card.task_key,
            interaction_revision=card.interaction_revision,
            component_type=card.component_type,
            input_policy=card.input_policy,
            card=card.card,
            replaces_interaction_id=None,
            expires_at=card.expires_at,
        )
        return InteractionCardRepository._request_fingerprint(
            card.binding.installation_id,
            card.binding.conversation_id,
            request,
        )

    def _read(self) -> _InteractionDocument:
        if not self.path.exists():
            return _InteractionDocument()
        try:
            return _InteractionDocument.model_validate_json(
                self.path.read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise InteractionError(
                "INTERACTION_REPOSITORY_INVALID",
                retryable=False,
            ) from exc

    def _write(self, document: _InteractionDocument) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                document.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


class InteractionService:
    """Small application boundary around the atomic repository."""

    def __init__(
        self,
        repository: InteractionCardRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def create(self, **kwargs: Any) -> InteractionCardRecord:
        return self.repository.create(now=self.clock(), **kwargs)

    def cancel(self, **kwargs: Any) -> InteractionCardRecord:
        return self.repository.cancel(now=self.clock(), **kwargs)

    def submit(self, **kwargs: Any) -> InteractionCardRecord:
        return self.repository.submit(now=self.clock(), **kwargs)

    def get_owned(
        self,
        interaction_id: str,
        **scope: str,
    ) -> InteractionCardRecord:
        return self.repository.get_owned(
            interaction_id,
            now=self.clock(),
            **scope,
        )

    def list_owned(
        self,
        *,
        installation_id: str,
        conversation_ids: Iterable[str],
    ) -> tuple[InteractionCardRecord, ...]:
        return self.repository.list_owned(
            installation_id=installation_id,
            conversation_ids=set(conversation_ids),
            now=self.clock(),
        )

    def resolve_for_authorization(
        self,
        interaction_id: str,
    ) -> InteractionCardRecord:
        return self.repository.resolve_for_authorization(
            interaction_id,
            now=self.clock(),
        )


__all__ = [
    "InteractionBinding",
    "InteractionCardRecord",
    "InteractionCardRepository",
    "InteractionError",
    "InteractionService",
    "InteractionTransition",
]
