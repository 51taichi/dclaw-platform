from types import SimpleNamespace

import pytest

from qwenpaw.aigc.workflow_contract import WorkflowBlueprint, validate_workflow_blueprint
from qwenpaw.app.aigc.asset_service import AigcAssetService
from qwenpaw.app.aigc.models import AigcAsset
from qwenpaw.app.aigc.resource_store import AigcResourceStore
from qwenpaw.app.routers import super_expert_platform as router


def blueprint():
    return WorkflowBlueprint.model_validate({
        'schema_version': 1, 'title': '通用图文作品',
        'execution_preference': 'CUSTOMER_TRIGGERED',
        'nodes': [{'node_id': key, 'kind': 'prompt', 'title': key,
                   'customer_action': 'NONE'} for key in ['copy', 'first', 'second']],
        'output_node_id': 'second', 'review_node_ids': ['copy', 'first', 'second'],
        'fallback_policy': 'FAIL_CLOSED',
    })


def test_workflow_preserves_explicit_review_order():
    result = validate_workflow_blueprint(blueprint())
    assert result.review_node_ids == ('copy', 'first', 'second')


@pytest.mark.asyncio
async def test_plain_text_asset_is_read_as_text(tmp_path):
    from qwenpaw.app.runtime.aigc_media import review_media_source
    path = tmp_path / 'copy.txt'
    path.write_text('通用作品的完整文案', encoding='utf-8')
    asset = AigcAsset(id='copy', kind='file', name='copy.txt', path=str(path),
        mime_type='text/plain', created_at='2026-01-01',
        meta={'canvas_id': 'canvas', 'node_id': 'copy'})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(aigc_artifact_root=tmp_path)))
    result = await review_media_source(request, AigcAssetService(AigcResourceStore(tmp_path / 'store')),
        asset, canvas_id='canvas', node_ids={'copy'}, asset_kinds={'text'})
    assert result == {'type': 'text', 'text': '通用作品的完整文案'}


@pytest.mark.asyncio
async def test_bundle_resolves_every_declared_node_in_order(monkeypatch):
    task = SimpleNamespace(workflow=SimpleNamespace(blueprint=blueprint()),
        binding=SimpleNamespace(canvas_id='canvas', node_bindings={'copy': 'p-copy', 'first': 'p-first', 'second': 'p-second'}))
    seen = []
    async def resolve(request, asset_id, **kwargs):
        seen.append((asset_id, kwargs['node_ids']))
        return {'type': 'text', 'text': asset_id}
    monkeypatch.setattr(router, 'resolve_owned_asset_for_agent_review', resolve)
    entries = [{'node_id': 'p-' + key, 'asset_id': 'a-' + key} for key in ['copy', 'first', 'second']]
    blocks = await router._resolve_review_bundle(None, task, entries, service=object())
    assert [item[0] for item in seen] == ['a-copy', 'a-first', 'a-second']
    assert all(item[1] == {'p-' + key} for item, key in zip(seen, ['copy', 'first', 'second']))
    assert [block['text'] for block in blocks if block['text'].startswith('a-')] == ['a-copy', 'a-first', 'a-second']


def test_bundle_submission_is_persisted_and_replayed(tmp_path):
    from qwenpaw.app.super_experts.aigc_tasks import AigcTaskCommand, AigcTaskRepository
    from qwenpaw.app.super_experts.models import AigcTaskBinding
    repository = AigcTaskRepository(tmp_path)
    binding = AigcTaskBinding(installation_id='install', conversation_id='chat',
        agent_task_id='content', content_revision=1, material_task_id='material',
        canvas_id='canvas', node_id='output')
    for action in ['create', 'start']:
        repository.apply(AigcTaskCommand(action=action, event_id=action, binding=binding), action)
    entries = [{'node_id': 'copy', 'asset_id': 'a-copy'}, {'node_id': 'image', 'asset_id': 'a-image'}]
    command = AigcTaskCommand(action='submit', event_id='submit', binding=binding,
        asset_id='a-copy', review_assets=entries)
    saved = repository.apply(command, 'submit')
    assert [item.model_dump() for item in saved.review_assets] == entries
    assert repository.apply(command, 'submit') == saved
    assert AigcTaskRepository(tmp_path).get('material').review_assets == saved.review_assets


@pytest.mark.asyncio
async def test_bundle_dispatch_delivers_real_text_and_both_images(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from qwenpaw.app.super_experts.models import AigcTaskBinding, AigcReviewAsset
    from qwenpaw.app.workspace.media_review_context import current_review_input
    data = blueprint().model_dump(mode='json')
    for node in data['nodes'][1:]:
        node.update(kind='image_generate', customer_action='CLICK_GENERATE', capability='text_to_image',
                    model_id='image-model', provider_id='provider')
    plan = WorkflowBlueprint.model_validate(data)
    binding = AigcTaskBinding(installation_id='install', conversation_id='chat', agent_task_id='content',
        content_revision=1, material_task_id='material', canvas_id='canvas', node_id='p-second',
        node_bindings={key: 'p-' + key for key in ['copy', 'first', 'second']})
    store = AigcResourceStore(tmp_path / 'store')
    entries = []
    for key in ['copy', 'first', 'second']:
        path = tmp_path / (key + ('.txt' if key == 'copy' else '.png'))
        path.write_bytes('完整作品正文'.encode() if key == 'copy' else b'fixture')
        asset = AigcAsset(id='a-' + key, kind='file' if key == 'copy' else 'image',
            name=path.name, path=str(path), mime_type='text/plain' if key == 'copy' else 'image/png',
            created_at='2026-01-01', meta={'canvas_id': 'canvas', 'node_id': 'p-' + key, 'owner_user_id': 'user'})
        store.write('assets', asset.id, asset.model_dump())
        entries.append(AigcReviewAsset(node_id='p-' + key, asset_id=asset.id))
    task = SimpleNamespace(binding=binding, workflow=SimpleNamespace(blueprint=plan), review_assets=entries)
    captured = {}
    class Runner:
        async def query_handler(self, messages, request):
            captured['content'] = messages[0].content
            captured['metadata'] = current_review_input(user_id='user', installation_id='install', conversation_id='chat')
            yield SimpleNamespace(get_text_content=lambda: '模型给出的整组审核结果'), True
    class Chats:
        async def get_chat(self, chat_id):
            return SimpleNamespace(id=chat_id, user_id='user', channel='console', meta={})
    class Manager:
        async def get_agent(self, agent_id):
            return SimpleNamespace(runner=Runner(), chat_manager=Chats())
    request = SimpleNamespace(state=SimpleNamespace(user_id='user'), app=SimpleNamespace(state=SimpleNamespace(
        aigc_artifact_root=tmp_path, multi_agent_manager=Manager())))
    service = SimpleNamespace(aigc=SimpleNamespace(assets=AigcAssetService(store)),
        get_task=lambda _: task,
        grant_repository=SimpleNamespace(get=lambda _: SimpleNamespace(agent_id='agent', tenant_id='tenant')))
    monkeypatch.setattr(router, 'prepare_user_billing_execution', lambda *a, **k: SimpleNamespace(
        activate=nullcontext, finalize_completed=lambda: None, finalize=lambda *a, **k: None))
    result = await router._dispatch_agent_asset_review(request, service=service, installation_id='install',
        binding=binding, asset_id='a-copy', request_key='review')
    assert result['reply'] == '模型给出的整组审核结果'
    assert [block['source']['url'] for block in captured['content'] if block['type'] == 'image'] == [
        (tmp_path / 'first.png').as_uri(), (tmp_path / 'second.png').as_uri()]
    assert any(block.get('text') == '完整作品正文' for block in captured['content'])
    assert [entry['asset_id'] for entry in captured['metadata']['review_assets']] == ['a-copy', 'a-first', 'a-second']
    assert len(captured['metadata']['review_blocks']) == 6


@pytest.mark.asyncio
async def test_bundle_rejects_incomplete_declared_submission():
    from fastapi import HTTPException
    task = SimpleNamespace(workflow=SimpleNamespace(blueprint=blueprint()),
        binding=SimpleNamespace(node_bindings={key: 'p-' + key for key in ['copy', 'first', 'second']}))
    with pytest.raises(HTTPException) as error:
        await router._resolve_review_bundle(None, task, [{'node_id': 'p-copy', 'asset_id': 'copy'}], service=None)
    assert error.value.status_code == 400
