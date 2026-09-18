import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from PIL import Image

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
async def test_image_review_uses_small_cached_proxy_without_changing_original(tmp_path):
    from qwenpaw.app.runtime.aigc_media import review_media_source

    original = tmp_path / 'large.png'
    Image.new('RGB', (1440, 2560), '#f5ead7').save(original, format='PNG')
    original_bytes = original.read_bytes()
    asset = AigcAsset(
        id='large-image', kind='image', name='large.png', path=str(original),
        mime_type='image/png', created_at='2026-01-01',
        meta={'canvas_id': 'canvas', 'node_id': 'image'},
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(aigc_artifact_root=tmp_path)),
    )
    service = AigcAssetService(AigcResourceStore(tmp_path / 'store'))

    first = await review_media_source(
        request, service, asset, canvas_id='canvas', node_ids={'image'},
        asset_kinds={'image'},
    )
    second = await review_media_source(
        request, service, asset, canvas_id='canvas', node_ids={'image'},
        asset_kinds={'image'},
    )

    proxy = Path(first['source']['url'].removeprefix('file://'))
    assert first == second
    assert proxy != original
    assert proxy.suffix == '.jpg'
    assert proxy.is_file()
    assert proxy.stat().st_size < len(original_bytes)
    with Image.open(proxy) as image:
        assert image.size == (1080, 1920)
    assert original.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_cloud_review_proxy_is_bound_as_downloaded_bytes(tmp_path):
    """Cloud review media must retain a byte identity through formatting.

    A signed OSS URL can be downloaded and re-encoded by a provider adapter,
    which makes URL-identity delivery receipts fail even when the model saw
    the image.  Bind the trusted, already-small proxy bytes instead.
    """
    from qwenpaw.app.runtime.aigc_media import review_media_source

    proxy = b"trusted-review-proxy"

    class Storage:
        async def download(self, object_key):
            assert object_key == "review/result.review.jpg"
            return proxy, "image/jpeg"

        def signed_get_url(self, _object_key):
            raise AssertionError("review must not be bound through a signed URL")

    asset = AigcAsset(
        id="cloud-image",
        kind="image",
        name="result.png",
        path="oss://bucket/original/result.png",
        mime_type="image/png",
        created_at="2026-01-01",
        meta={
            "canvas_id": "canvas",
            "node_id": "image",
            "storage": {
                "provider": "aliyun_oss",
                "object_key": "original/result.png",
            },
            "review_proxy": {
                "mime_type": "image/jpeg",
                "storage": {
                    "provider": "aliyun_oss",
                    "object_key": "review/result.review.jpg",
                },
            },
        },
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    result = await review_media_source(
        request,
        AigcAssetService(AigcResourceStore(tmp_path / "store")),
        asset,
        canvas_id="canvas",
        node_ids={"image"},
        asset_kinds={"image"},
        storage_client_factory=Storage,
    )

    assert result == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(proxy).decode("ascii"),
        },
    }


@pytest.mark.asyncio
async def test_generated_image_saves_original_and_review_copy(tmp_path, monkeypatch):
    from qwenpaw.app.aigc.models import AigcJob
    from qwenpaw.app.routers import aigc_studio

    original_buffer = BytesIO()
    Image.new('RGB', (1440, 2560), '#f5ead7').save(
        original_buffer,
        format='PNG',
    )
    original = original_buffer.getvalue()
    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    async def artifact_root(_request):
        return workspace

    monkeypatch.setattr(aigc_studio, 'STUDIO_ROOT', tmp_path / 'studio')
    monkeypatch.setattr(aigc_studio, '_artifact_root_for_request', artifact_root)
    monkeypatch.setattr(
        aigc_studio,
        'get_object_storage_client',
        lambda **_kwargs: None,
    )
    job = AigcJob(
        id='job', canvas_id='canvas', node_id='image',
        capability='text_to_image', provider_id='provider', model_id='model',
        status='running', created_at='2026-01-01',
        updated_at='2026-01-01',
    )

    asset = await aigc_studio._save_generated_asset(
        SimpleNamespace(state=SimpleNamespace(user_id='user')),
        job,
        original,
        kind='image',
        filename='result.png',
        mime_type='image/png',
        adapter='test',
    )

    original_path = workspace / asset.path
    proxy_path = workspace / asset.meta['review_proxy']['path']
    assert original_path.read_bytes() == original
    assert proxy_path.is_file()
    assert proxy_path.suffix == '.jpg'
    assert proxy_path.stat().st_size < original_path.stat().st_size
    assert asset.meta['review_proxy']['source_sha256'].startswith('sha256:')


@pytest.mark.asyncio
async def test_generated_cloud_image_uploads_original_and_review_copy(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.aigc.models import AigcJob
    from qwenpaw.app.routers import aigc_studio

    original_buffer = BytesIO()
    Image.new('RGB', (1440, 2560), '#f5ead7').save(
        original_buffer,
        format='PNG',
    )
    uploads = []

    async def upload(_client, *, relative_path, content, mime_type):
        uploads.append((relative_path, content, mime_type))
        return {
            'provider': 'aliyun_oss',
            'bucket': 'bucket',
            'endpoint': 'endpoint',
            'object_key': 'objects/' + relative_path,
            'size': len(content),
        }

    monkeypatch.setattr(aigc_studio, 'STUDIO_ROOT', tmp_path / 'studio')
    monkeypatch.setattr(
        aigc_studio,
        'get_object_storage_client',
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(aigc_studio, '_upload_generated_asset', upload)
    job = AigcJob(
        id='job', canvas_id='canvas', node_id='image',
        capability='text_to_image', provider_id='provider', model_id='model',
        status='running', created_at='2026-01-01',
        updated_at='2026-01-01',
    )

    asset = await aigc_studio._save_generated_asset(
        SimpleNamespace(state=SimpleNamespace(user_id='user')),
        job,
        original_buffer.getvalue(),
        kind='image',
        filename='result.png',
        mime_type='image/png',
        adapter='test',
    )

    assert [item[2] for item in uploads] == ['image/png', 'image/jpeg']
    assert uploads[1][0].endswith('result.review.jpg')
    assert len(uploads[1][1]) < len(uploads[0][1])
    assert asset.meta['storage']['object_key'] == 'objects/' + uploads[0][0]
    assert asset.meta['review_proxy']['storage']['object_key'].endswith(
        'result.review.jpg',
    )


@pytest.mark.asyncio
async def test_bundle_resolves_every_declared_node_in_order(monkeypatch):
    data = blueprint().model_dump(mode='json')
    data['nodes'][1]['inputs'] = {'prompt': '画面必须突出第一项内容'}
    plan = WorkflowBlueprint.model_validate(data)
    task = SimpleNamespace(workflow=SimpleNamespace(blueprint=plan),
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
    assert any('制作要求：画面必须突出第一项内容' in block.get('text', '') for block in blocks)


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
    task = SimpleNamespace(
        binding=binding,
        workflow=SimpleNamespace(blueprint=plan),
        review_assets=entries,
        status=router.AigcTaskStatus.ACCEPTED,
    )
    captured = {}
    class Runner:
        async def query_handler(self, messages, request):
            captured['content'] = messages[0].content
            captured['message_metadata'] = messages[0].metadata
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
    assert captured['message_metadata']['dclaw_aigc_review_bundle'] == {
        'material_task_id': 'material',
        'assets': [
            {'asset_id': 'a-first'},
            {'asset_id': 'a-second'},
        ],
    }


@pytest.mark.asyncio
async def test_review_bundle_archive_contains_only_bound_images(tmp_path, monkeypatch):
    from qwenpaw.app.super_experts.models import AigcTaskBinding, AigcReviewAsset

    binding = AigcTaskBinding(
        installation_id='install', conversation_id='chat', agent_task_id='content',
        content_revision=1, material_task_id='material', canvas_id='canvas',
        node_id='p-second',
    )
    store = AigcResourceStore(tmp_path / 'store')
    entries = []
    for index, name in enumerate(('first.png', 'second.png'), start=1):
        path = tmp_path / name
        path.write_bytes(f'image-{index}'.encode())
        asset = AigcAsset(
            id=f'asset-{index}', kind='image', name=name, path=str(path),
            mime_type='image/png', created_at='2026-01-01',
            meta={
                'canvas_id': 'canvas', 'node_id': f'image-{index}',
                'owner_user_id': 'user',
            },
        )
        store.write('assets', asset.id, asset.model_dump())
        entries.append(AigcReviewAsset(node_id=f'image-{index}', asset_id=asset.id))
    task = SimpleNamespace(binding=binding, review_assets=entries)
    service = SimpleNamespace(
        aigc=SimpleNamespace(assets=AigcAssetService(store)),
        get_task=lambda _: task,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user_id='user'),
        app=SimpleNamespace(state=SimpleNamespace(aigc_artifact_root=tmp_path)),
    )
    monkeypatch.setattr(router, 'get_super_expert_platform_service', lambda: service)
    monkeypatch.setattr(router, 'ensure_chat_access', lambda *_args, **_kwargs: {})

    response = await router.download_review_assets_archive('material', request)
    body = b''.join([chunk async for chunk in response.body_iterator])
    with zipfile.ZipFile(BytesIO(body)) as archive:
        assert archive.namelist() == ['first.png', 'second.png']
        assert archive.read('first.png') == b'image-1'
        assert archive.read('second.png') == b'image-2'


@pytest.mark.asyncio
async def test_bundle_rejects_incomplete_declared_submission():
    from fastapi import HTTPException
    task = SimpleNamespace(workflow=SimpleNamespace(blueprint=blueprint()),
        binding=SimpleNamespace(node_bindings={key: 'p-' + key for key in ['copy', 'first', 'second']}))
    with pytest.raises(HTTPException) as error:
        await router._resolve_review_bundle(None, task, [{'node_id': 'p-copy', 'asset_id': 'copy'}], service=None)
    assert error.value.status_code == 400
