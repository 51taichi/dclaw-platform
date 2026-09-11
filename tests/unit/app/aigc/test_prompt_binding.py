import pytest
from qwenpaw.app.aigc.prompt_binding import resolve_prompt, PromptBindingError


def canvas(text="茶杯桌面"):
    return {
        "nodes": [
            {
                "id": "p",
                "type": "prompt",
                "data": {"workflowLogicalNodeId": "cover_prompt", "text": text},
            },
            {"id": "i", "type": "image_generate", "data": {}},
            {"id": "v", "type": "video_generate", "data": {}},
        ],
        "edges": [
            {"source": "p", "target": "i", "data": {"role": "prompt"}},
            {"source": "p", "target": "v", "data": {"role": "prompt"}},
        ],
    }


@pytest.mark.parametrize("target", ["i", "v"])
def test_binding_uses_current_connected_text(target):
    c = canvas()
    assert resolve_prompt(c, target, "主题：${cover_prompt.text}") == "主题：茶杯桌面"
    c["nodes"][0]["data"]["text"] = "白瓷茶杯，无人物"
    assert resolve_prompt(c, target, "${cover_prompt.text}") == "白瓷茶杯，无人物"


@pytest.mark.parametrize(
    "value", ["${missing.text}", "${cover_prompt.url}", "${cover_prompt.text"]
)
def test_invalid_binding_is_rejected(value):
    with pytest.raises(PromptBindingError):
        resolve_prompt(canvas(), "i", value)


def test_disconnected_empty_and_cycles_are_rejected():
    c = canvas()
    c["edges"] = []
    with pytest.raises(PromptBindingError):
        resolve_prompt(c, "i", "${cover_prompt.text}")
    with pytest.raises(PromptBindingError):
        resolve_prompt(canvas(""), "i", "${cover_prompt.text}")
    c = canvas("${cover_prompt.text}")
    c["edges"].append({"source": "p", "target": "p"})
    with pytest.raises(PromptBindingError):
        resolve_prompt(c, "i", "${cover_prompt.text}")


def test_plain_prompt_unchanged():
    assert resolve_prompt(canvas(), "i", "手写提示词 $20") == "手写提示词 $20"


@pytest.mark.parametrize(
    "target,capability", [("i", "text_to_image"), ("v", "text_to_video")]
)
def test_router_resolves_before_mxapi_body_and_retry_reads_latest(
    monkeypatch, target, capability
):
    from types import SimpleNamespace
    from qwenpaw.app.routers import aigc_studio as api

    c = canvas()
    monkeypatch.setattr(
        api,
        "_load_canvas_for_request",
        lambda *a: SimpleNamespace(model_dump=lambda: c),
    )
    body = api.AigcJobCreate(
        canvas_id="c",
        node_id=target,
        provider_id="mxapi",
        model_id="nano2" if target == "i" else "seedance2",
        capability=capability,
        inputs={"prompt": "${cover_prompt.text}"},
    )
    api._resolve_job_prompt_binding(None, body)
    assert body.inputs["prompt"] == "茶杯桌面"
    assert body.inputs["prompt_template"] == "${cover_prompt.text}"
    if target == "i":
        payload = api._mxapi_submit_body(
            body,
            prompt=api._image_prompt_from_job(body),
            reference_images=[],
            adapter="mxapi_nano2",
        )
        assert payload["prompt"] == "茶杯桌面"
    else:
        payload = api._mxapi_seedance_submit_body(None, body)
        assert payload["content"][0]["text"] == "茶杯桌面"
    c["nodes"][0]["data"]["text"] = "更新后的茶杯文案"
    api._resolve_job_prompt_binding(None, body)
    assert body.inputs["prompt"] == "更新后的茶杯文案"
    assert body.parameters["lastRunPrompt"] == "更新后的茶杯文案"
