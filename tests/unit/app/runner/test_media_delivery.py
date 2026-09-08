"""Transport receipts must reflect the formatted request, not model prose."""
import json
import asyncio
from types import SimpleNamespace

import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg

from qwenpaw.agents import model_factory
from qwenpaw.app.workspace.orchestration import _execute_internal_candidate


@pytest.mark.asyncio
async def test_concurrent_review_contexts_never_share_asset_bindings():
    from qwenpaw.app.workspace.media_review_context import bind_review_input, current_review_input
    from qwenpaw.app.super_experts.models import AigcTaskBinding
    arrived = 0
    ready = asyncio.Event()
    async def task(ordinal):
        nonlocal arrived
        binding = AigcTaskBinding(installation_id='installation', conversation_id=f'conversation-{ordinal}',
            agent_task_id=f'task-{ordinal}', content_revision=1, material_task_id=f'material-{ordinal}',
            canvas_id=f'canvas-{ordinal}', node_id=f'node-{ordinal}')
        with bind_review_input(user_id='user', binding=binding, asset_id=f'asset-{ordinal}',
            media_block={'type':'image','source':{'type':'url','url':f'https://example.test/{ordinal}.png'}}):
            arrived += 1
            if arrived == 2:
                ready.set()
            await ready.wait()
            assert current_review_input(user_id='user', installation_id='installation',
                conversation_id=f'conversation-{ordinal}')['asset_id'] == f'asset-{ordinal}'
            assert current_review_input(user_id='user', installation_id='installation',
                conversation_id=f'conversation-{3-ordinal}') is None
        assert current_review_input(user_id='user', installation_id='installation',
            conversation_id=f'conversation-{ordinal}') is None
    await asyncio.wait_for(asyncio.gather(task(1), task(2)), timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize('supported', [True, False])
async def test_actual_formatter_media_delivery_not_model_claim(monkeypatch, supported):
    monkeypatch.setattr(model_factory, '_supports_multimodal_for_current_model', lambda: supported)
    formatter = model_factory._create_file_block_support_formatter(OpenAIChatFormatter)()
    sent = []
    async def model(prompt, **kwargs):
        sent.extend(prompt)
        return SimpleNamespace(id='model-response-1', content=[{'type': 'text', 'text': '我已经看过图片并审核通过'}])
    messages = [Msg(name='user', role='user', content=[{
        'type': 'image', 'source': {'type': 'url', 'url': 'https://assets.example.test/private-current.png'},
    }])]
    delivery = {'untrusted': 'old result'}
    await _execute_internal_candidate(SimpleNamespace(formatter=formatter, model=model), messages,
                                      media_delivery=delivery)
    assert delivery['schema_version'] == 'dclaw-media-delivery-v1'
    assert delivery['model_response_id'] == 'model-response-1'
    assert delivery['delivered_modalities'] == (['image'] if supported else [])
    assert delivery['unavailable_modalities'] == ([] if supported else ['image'])
    assert 'private-current.png' not in json.dumps(delivery)
    assert 'untrusted' not in delivery
    assert delivery['input_digest'].startswith('sha256:')
    assert messages[0].content[0]['type'] == 'image'


@pytest.mark.asyncio
async def test_failed_model_call_cannot_reuse_previous_media_delivery(monkeypatch):
    monkeypatch.setattr(model_factory, '_supports_multimodal_for_current_model', lambda: True)
    formatter = model_factory._create_file_block_support_formatter(OpenAIChatFormatter)()
    async def model(prompt, **kwargs):
        raise RuntimeError('provider failed')
    delivery = {'delivered_modalities': ['video']}
    with pytest.raises(RuntimeError, match='provider failed'):
        await _execute_internal_candidate(SimpleNamespace(formatter=formatter, model=model),
            [Msg(name='user', role='user', content='https://example.test/video.mp4')], media_delivery=delivery)
    assert delivery == {}


@pytest.mark.asyncio
async def test_text_url_never_becomes_a_media_delivery(monkeypatch):
    monkeypatch.setattr(model_factory, '_supports_multimodal_for_current_model', lambda: True)
    formatter = model_factory._create_file_block_support_formatter(OpenAIChatFormatter)()
    async def model(prompt, **kwargs):
        return SimpleNamespace(id='text-only', content=[{'type': 'text', 'text': '已看完视频'}])
    delivery = {}
    await _execute_internal_candidate(SimpleNamespace(formatter=formatter, model=model),
        [Msg(name='user', role='user', content='https://example.test/video.mp4')], media_delivery=delivery)
    assert delivery == {}


@pytest.mark.asyncio
async def test_old_tool_image_cannot_replace_missing_current_image(monkeypatch, tmp_path):
    monkeypatch.setattr(model_factory, '_supports_multimodal_for_current_model', lambda: True)
    formatter = model_factory._create_file_block_support_formatter(OpenAIChatFormatter)(promote_tool_result_images=True)
    sent = []
    async def model(prompt, **kwargs):
        sent.extend(prompt)
        return SimpleNamespace(id='old-image-only', content=[{'type':'text', 'text':'图片中有白纸'}])
    messages = [
        Msg(name='assistant', role='assistant', content=[{'type':'tool_use', 'id':'t1', 'name':'read', 'input':{}}]),
        Msg(name='tool', role='user', content=[{'type':'tool_result', 'id':'t1', 'name':'read',
            'output':[{'type':'image', 'source':{'type':'url', 'url':'https://example.test/OLD.png'}}]}]),
        Msg(name='user', role='user', content=[{'type':'image', 'source':{'type':'url', 'url':str(tmp_path/'missing.png')}}]),
    ]
    receipt = {}
    await _execute_internal_candidate(SimpleNamespace(formatter=formatter, model=model), messages, media_delivery=receipt)
    assert 'OLD.png' in json.dumps(sent)
    assert receipt['delivered_modalities'] == []
    assert receipt['unavailable_modalities'] == ['image']


@pytest.mark.asyncio
async def test_video_is_native_only_when_the_formatter_preserves_it(monkeypatch):
    monkeypatch.setattr(model_factory, '_supports_multimodal_for_current_model', lambda: True)
    async def model(prompt, **kwargs):
        return SimpleNamespace(id='video-result', content=[{'type': 'text', 'text': '候选结果'}])
    messages = [Msg(name='user', role='user', content=[
        {'type': 'image', 'source': {'type': 'url', 'url': 'https://assets.example.test/frame.png'}},
        {'type': 'video', 'source': {'type': 'url', 'url': 'https://assets.example.test/current.mp4'}},
    ])]
    # Actual upstream OpenAI formatter drops video; DClaw's adapter preserves it.
    for formatter, delivered, missing in (
        (OpenAIChatFormatter(), ['image'], ['video']),
        (model_factory._create_file_block_support_formatter(OpenAIChatFormatter)(), ['image', 'video'], []),
    ):
        receipt = {}
        await _execute_internal_candidate(SimpleNamespace(formatter=formatter, model=model), messages,
                                          media_delivery=receipt)
        assert receipt['delivered_modalities'] == delivered
        assert receipt['unavailable_modalities'] == missing


@pytest.mark.asyncio
async def test_delivery_is_bound_to_this_input_not_a_previous_asset(monkeypatch):
    monkeypatch.setattr(model_factory, '_supports_multimodal_for_current_model', lambda: True)
    formatter = model_factory._create_file_block_support_formatter(OpenAIChatFormatter)()
    async def model(prompt, **kwargs):
        return SimpleNamespace(id='result', content=[{'type': 'text', 'text': '结果'}])
    receipts = []
    for name in ('current', 'other'):
        receipt = {}
        await _execute_internal_candidate(SimpleNamespace(formatter=formatter, model=model),
            [Msg(name='user', role='user', content=[{'type': 'image', 'source': {
                'type': 'url', 'url': f'https://assets.example.test/{name}.png'}}])], media_delivery=receipt)
        receipts.append(receipt)
    assert receipts[0]['input_digest'] != receipts[1]['input_digest']
    assert receipts[0]['media_inputs'][0]['block_digest'] != receipts[1]['media_inputs'][0]['block_digest']


@pytest.mark.asyncio
async def test_empty_model_reply_has_no_delivery_receipt(monkeypatch):
    monkeypatch.setattr(model_factory, '_supports_multimodal_for_current_model', lambda: True)
    formatter = model_factory._create_file_block_support_formatter(OpenAIChatFormatter)()
    async def model(prompt, **kwargs):
        return SimpleNamespace(id='empty', content=[])
    receipt = {}
    await _execute_internal_candidate(SimpleNamespace(formatter=formatter, model=model),
        [Msg(name='user', role='user', content=[{'type': 'image', 'source': {
            'type': 'url', 'url': 'https://assets.example.test/current.png'}}])], media_delivery=receipt)
    assert receipt == {}
