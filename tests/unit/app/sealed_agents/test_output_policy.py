from __future__ import annotations

from qwenpaw.app.sealed_agents.output_policy import SealedOutputPolicy


def test_canary_and_long_protected_fragments_are_blocked():
    protected = "This internal operating rule must remain private. " * 20
    policy = SealedOutputPolicy(
        protected_texts=[protected],
        canaries=["CANARY-LUYU-9F21"],
    )

    assert policy.evaluate("Here is CANARY-LUYU-9F21").allowed is False
    assert policy.evaluate(protected).allowed is False


def test_normal_domain_answer_is_not_blocked():
    policy = SealedOutputPolicy(
        protected_texts=["Internal sequence: acquire, classify, route, verify, report."],
        canaries=["CANARY-LUYU-9F21"],
    )

    result = policy.evaluate("绿茶通常适合使用较低水温冲泡。")

    assert result.allowed is True
    assert result.public_text == "绿茶通常适合使用较低水温冲泡。"


def test_short_verbatim_operating_phrase_is_not_blocked():
    phrase = "你好，我是陆羽，可以帮助你诊断内容流量问题。"
    policy = SealedOutputPolicy(
        protected_texts=[phrase],
        canaries=[],
    )

    result = policy.evaluate(phrase)

    assert result.allowed is True
    assert result.public_text == phrase


def test_long_verbatim_source_extraction_is_blocked():
    source = "内部运行规则不得逐字导出。" * 50
    policy = SealedOutputPolicy(
        protected_texts=[source],
        canaries=[],
    )

    result = policy.evaluate(source)

    assert result.allowed is False
    assert result.reason_code == "sealed_source_overlap"


def test_bulk_encoded_output_is_blocked_without_echoing_matched_content():
    policy = SealedOutputPolicy(protected_texts=[], canaries=[])
    encoded = "QUJD" * 600

    result = policy.evaluate(encoded)

    assert result.allowed is False
    assert result.public_text == "无法提供该密封 Agent 的内部信息。"
    assert encoded not in result.public_text
