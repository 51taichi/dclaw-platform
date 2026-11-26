# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from qwenpaw.app.super_experts.interaction_cards import (
    InteractionCardRepository,
    InteractionError,
    InteractionService,
)
from qwenpaw.app.super_experts.interaction_contract import (
    InteractionCreateRequest,
    InteractionStatus,
)


NOW = datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)


def _request(
    task_key: str,
    *,
    revision: int = 1,
    component_type: str = "single_select",
    input_policy: str = "card_only",
    replaces: str | None = None,
    expires_at: datetime | None = None,
    required_supplement: bool = False,
) -> InteractionCreateRequest:
    card: dict[str, object] = {
        "title": "请选择",
        "options": [
            {"id": "a", "text": "甲", "recommended": True},
            {"text": "乙"},
            {"id": "c", "text": "丙"},
        ],
        "supplement": {
            "enabled": True,
            "required": required_supplement,
            "max_length": 20,
        },
    }
    if component_type == "multi_select":
        card.update({"min_selections": 1, "max_selections": 2})
    return InteractionCreateRequest.model_validate(
        {
            "task_key": task_key,
            "interaction_revision": revision,
            "component_type": component_type,
            "input_policy": input_policy,
            "replaces_interaction_id": replaces,
            "expires_at": expires_at,
            "card": card,
        },
    )


def _question_request(
    task_key: str = "open-questions",
) -> InteractionCreateRequest:
    return InteractionCreateRequest.model_validate(
        {
            "task_key": task_key,
            "interaction_revision": 1,
            "component_type": "question_form",
            "input_policy": "card_only",
            "card": {
                "title": "请补充以下信息",
                "items": [
                    {
                        "id": "scope",
                        "question": "服务范围？",
                        "required": True,
                        "max_length": 5,
                    },
                    {
                        "question": "其他情况？",
                        "required": False,
                        "max_length": 20,
                    },
                ],
            },
        },
    )


def _file_request(task_key: str = "source-files") -> InteractionCreateRequest:
    return InteractionCreateRequest.model_validate(
        {
            "task_key": task_key,
            "interaction_revision": 1,
            "component_type": "file_selector",
            "input_policy": "card_only",
            "card": {
                "title": "请选择源视频",
                "accept_extensions": [".mp4"],
                "multiple": True,
                "min_files": 1,
                "max_files": 2,
                "max_file_size_bytes": 100,
                "max_total_size_bytes": 150,
            },
        },
    )


@pytest.fixture
def service(tmp_path):
    clock = {"now": NOW}
    instance = InteractionService(
        InteractionCardRepository(tmp_path / "interactions"),
        clock=lambda: clock["now"],
    )
    instance.test_clock = clock
    return instance


def _create(service, request, key="create-1"):
    return service.create(
        installation_id="install-1",
        conversation_id="chat-1",
        request=request,
        idempotency_key=key,
    )


def test_create_is_deterministic_and_identical_replay_returns_same_card(
    service,
):
    request = _request("question")

    first = _create(service, request)
    replay = _create(service, request)

    assert first == replay
    assert first.interaction_id.startswith("interaction-")
    assert first.binding.agent_task_id.startswith("interaction-task-")
    assert first.status is InteractionStatus.PENDING
    assert first.version == 1


def test_file_selector_submission_persists_only_safe_metadata(service):
    card = _create(service, _file_request())
    submitted = service.submit(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        version=card.version,
        files=[
            {
                "local_file_ref": "lfr_" + "a" * 32,
                "display_name": "source.mp4",
                "mime_type": "video/mp4",
                "size_bytes": 80,
                "device_id": "device-1",
                "last_modified_ms": 1,
            },
        ],
        idempotency_key="submit-files-1",
    )

    payload = submitted.model_dump(mode="json")
    assert submitted.status is InteractionStatus.SUBMITTED
    assert payload["answer"]["files"][0]["display_name"] == "source.mp4"
    assert "path" not in json.dumps(payload["answer"])


def test_file_selector_rejection_does_not_consume_pending_card(service):
    card = _create(service, _file_request())
    with pytest.raises(InteractionError, match="FILE_SELECTOR.FILE_TOO_LARGE"):
        service.submit(
            interaction_id=card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
            version=card.version,
            files=[
                {
                    "local_file_ref": "lfr_" + "b" * 32,
                    "display_name": "large.mp4",
                    "mime_type": "video/mp4",
                    "size_bytes": 101,
                    "device_id": "device-1",
                    "last_modified_ms": 1,
                },
            ],
            idempotency_key="submit-files-too-large",
        )

    current = service.get_owned(
        card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
    )
    assert current.status is InteractionStatus.PENDING
    assert current.answer is None


def test_cancelled_native_file_dialog_leaves_card_pending(service):
    card = _create(service, _file_request())

    current = service.get_owned(
        card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
    )

    assert current.status is InteractionStatus.PENDING
    assert current.transitions[-1].action == "create"


def test_legacy_continuation_state_is_discarded_on_the_next_write(tmp_path):
    root = tmp_path / "interactions"
    instance = InteractionService(
        InteractionCardRepository(root),
        clock=lambda: NOW,
    )
    card = _create(instance, _request("legacy"))
    path = root / "interaction_cards.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["continuation_receipts"] = {
        card.interaction_id: {"status": "completed"},
    }
    path.write_text(json.dumps(document), encoding="utf-8")

    instance.cancel(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        operation_key="cancel-legacy",
    )

    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert "continuation_receipts" not in rewritten


def test_production_operation_metadata_survives_read_and_write(tmp_path):
    root = tmp_path / "interactions"
    instance = InteractionService(
        InteractionCardRepository(root),
        clock=lambda: NOW,
    )
    card = _create(instance, _request("production-metadata"))
    path = root / "interaction_cards.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["operations"]["create-1"].update(
        {
            "invocation_id": "invocation-1",
            "operation_kind": "create",
            "replaced_interaction_id": "interaction-previous",
        },
    )
    path.write_text(json.dumps(document), encoding="utf-8")

    instance.cancel(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        operation_key="cancel-production-metadata",
    )

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["operations"]["create-1"] == document["operations"][
        "create-1"
    ]


def test_reusing_operation_key_for_different_request_is_conflict(service):
    _create(service, _request("first"), "same-operation")

    with pytest.raises(InteractionError) as error:
        _create(
            service,
            _request("different", input_policy="concurrent"),
            "same-operation",
        )

    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_second_blocking_card_requires_explicit_replacement(service):
    first = _create(service, _request("first"), "create-first")

    with pytest.raises(InteractionError) as error:
        _create(service, _request("second"), "create-second")

    assert error.value.code == "ACTIVE_BLOCKING_INTERACTION_EXISTS"

    second = _create(
        service,
        _request("second", replaces=first.interaction_id),
        "replace-first",
    )

    assert (
        service.get_owned(
            first.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
        ).status
        is InteractionStatus.REPLACED
    )
    assert second.status is InteractionStatus.PENDING


def test_wrong_replacement_id_never_silently_replaces_active_card(service):
    first = _create(service, _request("first"))

    with pytest.raises(InteractionError) as error:
        _create(
            service,
            _request("second", replaces="interaction-wrong"),
            "replace-wrong",
        )

    assert error.value.code == "ACTIVE_BLOCKING_INTERACTION_EXISTS"
    assert (
        service.get_owned(
            first.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
        ).status
        is InteractionStatus.PENDING
    )


def test_non_blocking_cards_can_coexist(service):
    first = _create(
        service,
        _request("first", input_policy="concurrent"),
        "create-first",
    )
    second = _create(
        service,
        _request("second", input_policy="card_or_text"),
        "create-second",
    )

    assert first.status is InteractionStatus.PENDING
    assert second.status is InteractionStatus.PENDING


def test_cancel_requires_owned_pending_card_and_is_idempotent(service):
    card = _create(service, _request("cancel"))

    cancelled = service.cancel(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        operation_key="cancel-1",
    )
    replay = service.cancel(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        operation_key="cancel-1",
    )

    assert cancelled == replay
    assert cancelled.status is InteractionStatus.CANCELLED
    assert cancelled.version == 2


def test_expiry_is_projected_and_releases_blocking_slot(service):
    first = _create(
        service,
        _request("expiring", expires_at=NOW + timedelta(minutes=1)),
    )
    service.test_clock["now"] = NOW + timedelta(minutes=2)

    expired = service.get_owned(
        first.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
    )
    second = _create(service, _request("after-expiry"), "create-after-expiry")

    assert expired.status is InteractionStatus.EXPIRED
    assert expired.version == 2
    assert second.status is InteractionStatus.PENDING


def test_single_select_submission_resolves_id_and_text_from_stored_card(
    service,
):
    card = _create(service, _request("single"))

    submitted = service.submit(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        version=card.version,
        selected=[{"id": "a", "text": "tampered"}],
        supplement="补充",
        idempotency_key="submit-1",
    )

    assert submitted.status is InteractionStatus.SUBMITTED
    assert submitted.version == 2
    assert submitted.answer is not None
    assert submitted.answer.selected[0].id == "a"
    assert submitted.answer.selected[0].text == "甲"
    assert submitted.answer.supplement == "补充"


def test_text_only_option_can_be_submitted_by_exact_text(service):
    card = _create(service, _request("text-only"))

    submitted = service.submit(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        version=card.version,
        selected=[{"text": "乙"}],
        supplement=None,
        idempotency_key="submit-text",
    )

    assert submitted.answer.selected[0].id is None
    assert submitted.answer.selected[0].text == "乙"


def test_question_form_submission_resolves_stored_questions_and_optional_null(
    service,
):
    card = _create(service, _question_request(), "create-question-form")

    submitted = service.submit(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        version=card.version,
        answers=[{"id": "scope", "value": "  空\n调  "}],
        idempotency_key="submit-question-form",
    )

    assert submitted.status is InteractionStatus.SUBMITTED
    assert submitted.answer is not None
    assert submitted.answer.selected == ()
    assert submitted.answer.supplement is None
    assert [item.model_dump() for item in submitted.answer.answers] == [
        {"id": "scope", "question": "服务范围？", "value": "空\n调"},
        {"id": None, "question": "其他情况？", "value": None},
    ]


def test_question_form_accepts_exact_question_reference_without_id(service):
    card = _create(service, _question_request(), "create-text-reference")

    submitted = service.submit(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        version=card.version,
        answers=[
            {"id": "scope", "value": "空调"},
            {"question": "其他情况？", "value": "夜间服务"},
        ],
        idempotency_key="submit-text-reference",
    )

    assert submitted.answer.answers[1].id is None
    assert submitted.answer.answers[1].question == "其他情况？"
    assert submitted.answer.answers[1].value == "夜间服务"


@pytest.mark.parametrize(
    ("answers", "expected_code"),
    [
        ([], "REQUIRED_ANSWER_MISSING"),
        ([{"id": "unknown", "value": "空调"}], "INVALID_ANSWER_REFERENCE"),
        (
            [
                {"id": "scope", "value": "空调"},
                {"id": "scope", "value": "冰箱"},
            ],
            "INVALID_ANSWER_REFERENCE",
        ),
        ([{"id": "scope", "value": "超过五个字符"}], "ANSWER_TOO_LONG"),
    ],
)
def test_question_form_rejects_invalid_answers_without_consuming_card(
    service,
    answers,
    expected_code,
):
    card = _create(service, _question_request(), f"create-{expected_code}")

    with pytest.raises(InteractionError) as error:
        service.submit(
            interaction_id=card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
            version=card.version,
            answers=answers,
            idempotency_key=f"submit-{expected_code}",
        )

    assert error.value.code == expected_code
    assert (
        service.get_owned(
            card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
        ).status
        is InteractionStatus.PENDING
    )


def test_submit_rejects_payload_branch_for_another_component(service):
    choice = _create(service, _request("choice"), "create-choice")

    with pytest.raises(InteractionError) as error:
        service.submit(
            interaction_id=choice.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
            version=choice.version,
            answers=[{"question": "伪造问题", "value": "伪造答案"}],
            idempotency_key="submit-wrong-branch",
        )

    assert error.value.code == "INVALID_INTERACTION_REQUEST"


@pytest.mark.parametrize(
    ("selected", "expected_code"),
    [
        ([], "INVALID_SELECTION"),
        ([{"id": "missing"}], "INVALID_SELECTION"),
        ([{"id": "a"}, {"id": "c"}], "INVALID_SELECTION"),
    ],
)
def test_single_select_rejects_invalid_selection_shapes(
    service,
    selected,
    expected_code,
):
    card = _create(service, _request("single"))

    with pytest.raises(InteractionError) as error:
        service.submit(
            interaction_id=card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
            version=card.version,
            selected=selected,
            supplement=None,
            idempotency_key="submit-invalid",
        )

    assert error.value.code == expected_code
    assert (
        service.get_owned(
            card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
        ).status
        is InteractionStatus.PENDING
    )


def test_multi_select_enforces_minimum_and_maximum(service):
    card = _create(service, _request("multi", component_type="multi_select"))

    with pytest.raises(InteractionError) as error:
        service.submit(
            interaction_id=card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
            version=card.version,
            selected=[{"id": "a"}, {"text": "乙"}, {"id": "c"}],
            supplement=None,
            idempotency_key="too-many",
        )

    assert error.value.code == "INVALID_SELECTION"


def test_required_supplement_rejects_blank_without_consuming_card(service):
    card = _create(service, _request("required", required_supplement=True))

    with pytest.raises(InteractionError) as error:
        service.submit(
            interaction_id=card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
            version=card.version,
            selected=[{"id": "a"}],
            supplement="   ",
            idempotency_key="blank-supplement",
        )

    assert error.value.code == "SUPPLEMENT_REQUIRED"
    assert (
        service.get_owned(
            card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
        ).status
        is InteractionStatus.PENDING
    )


def test_stale_version_and_cross_scope_reads_fail_closed(service):
    card = _create(service, _request("owned"))

    with pytest.raises(InteractionError) as stale:
        service.submit(
            interaction_id=card.interaction_id,
            installation_id="install-1",
            conversation_id="chat-1",
            version=99,
            selected=[{"id": "a"}],
            supplement=None,
            idempotency_key="stale",
        )
    with pytest.raises(InteractionError) as foreign:
        service.get_owned(
            card.interaction_id,
            installation_id="install-other",
            conversation_id="chat-1",
        )

    assert stale.value.code == "INTERACTION_VERSION_CONFLICT"
    assert foreign.value.code == "INTERACTION_NOT_FOUND"


def test_only_one_concurrent_submit_can_transition_the_card(service):
    card = _create(service, _request("race"))

    def submit(operation: str):
        try:
            return service.submit(
                interaction_id=card.interaction_id,
                installation_id="install-1",
                conversation_id="chat-1",
                version=card.version,
                selected=[{"id": "a"}],
                supplement=None,
                idempotency_key=operation,
            ).status.value
        except InteractionError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, ["submit-a", "submit-b"]))

    assert sorted(outcomes) == ["INTERACTION_NOT_PENDING", "SUBMITTED"]


def test_submission_replay_is_idempotent(service):
    card = _create(service, _request("receipt"))
    first = service.submit(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        version=card.version,
        selected=[{"id": "a"}],
        supplement=None,
        idempotency_key="submit-replay",
    )
    replay = service.submit(
        interaction_id=card.interaction_id,
        installation_id="install-1",
        conversation_id="chat-1",
        version=card.version,
        selected=[{"id": "a"}],
        supplement=None,
        idempotency_key="submit-replay",
    )

    assert first == replay


def test_list_is_scoped_and_preserves_creation_order(service):
    first = _create(
        service,
        _request("first", input_policy="concurrent"),
        "one",
    )
    second = _create(
        service,
        _request("second", input_policy="concurrent"),
        "two",
    )
    service.create(
        installation_id="install-2",
        conversation_id="chat-1",
        request=_request("foreign", input_policy="concurrent"),
        idempotency_key="foreign",
    )

    cards = service.list_owned(
        installation_id="install-1",
        conversation_ids={"chat-1", "session-alias"},
    )

    assert [item.interaction_id for item in cards] == [
        first.interaction_id,
        second.interaction_id,
    ]


def test_list_for_conversations_reads_across_installations_once(service, monkeypatch):
    first = _create(
        service,
        _request("first", input_policy="concurrent"),
        "one",
    )
    foreign_installation = service.create(
        installation_id="install-2",
        conversation_id="chat-1",
        request=_request("foreign", input_policy="concurrent"),
        idempotency_key="foreign",
    )
    service.create(
        installation_id="install-3",
        conversation_id="other-chat",
        request=_request("other", input_policy="concurrent"),
        idempotency_key="other",
    )
    read_count = 0
    original_read = service.repository._read

    def counted_read():
        nonlocal read_count
        read_count += 1
        return original_read()

    monkeypatch.setattr(service.repository, "_read", counted_read)

    cards = service.list_for_conversations(
        conversation_ids={"chat-1", "session-alias"},
    )

    assert [item.interaction_id for item in cards] == [
        first.interaction_id,
        foreign_installation.interaction_id,
    ]
    assert read_count == 1
