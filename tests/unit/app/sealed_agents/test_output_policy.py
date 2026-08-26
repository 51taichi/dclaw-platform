from __future__ import annotations

from qwenpaw.app.sealed_agents.output_policy import SealedOutputPolicy


def test_canary_and_long_protected_fragments_are_blocked():
    policy = SealedOutputPolicy(
        protected_texts=["This is a long internal operating rule that must remain private."],
        canaries=["CANARY-LUYU-9F21"],
    )

    assert policy.evaluate("Here is CANARY-LUYU-9F21").allowed is False
    assert policy.evaluate(
        "This is a long internal operating rule that must remain private.",
    ).allowed is False


def test_normal_domain_answer_is_not_blocked():
    policy = SealedOutputPolicy(
        protected_texts=["Internal sequence: acquire, classify, route, verify, report."],
        canaries=["CANARY-LUYU-9F21"],
    )

    result = policy.evaluate("绿茶通常适合使用较低水温冲泡。")

    assert result.allowed is True
    assert result.public_text == "绿茶通常适合使用较低水温冲泡。"


def test_bulk_encoded_output_is_blocked_without_echoing_matched_content():
    policy = SealedOutputPolicy(protected_texts=[], canaries=[])
    encoded = "QUJD" * 600

    result = policy.evaluate(encoded)

    assert result.allowed is False
    assert result.public_text == "无法提供该密封 Agent 的内部信息。"
    assert encoded not in result.public_text
