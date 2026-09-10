import json
from types import SimpleNamespace

import pytest
from agentscope.tool import Toolkit

from qwenpaw.app.workspace.aigc_tools import build_aigc_tools, bind_aigc_tools


CATALOG = 'aigc.workflow.capabilities.list/1'
CREATE = 'aigc.workflow.create/1'


def harness(grants=None, session='session-a', tasks=None):
    calls = []
    async def call(capability, arguments):
        calls.append((capability, arguments))
        return {'nodes': [], 'available_models': []} if capability == CATALOG else {'task': arguments}
    tools = build_aigc_tools(
        grants=grants or {}, installation_id='installation-a',
        conversation_id=session, business_call=call,
        read_task=lambda key: (tasks or {}).get(key),
        review_input=None, media_delivery={},
    )
    return tools, calls


def result(response):
    return json.loads(response.content[0]['text'])


def test_only_granted_supported_capabilities_are_exposed():
    assert harness()[0] == {}
    assert harness({'mcp.execute': '1', CATALOG: '2'})[0] == {}
    assert set(harness({CATALOG: '1'})[0]) == {'aigc_workflow_catalog'}
    assert 'aigc_workflow_create' not in harness({CREATE: '1'})[0]


@pytest.mark.asyncio
async def test_create_uses_host_scope_and_stable_identity_across_turns():
    grants = {CATALOG: '1', CREATE: '1'}
    tools, calls = harness(grants)
    workflow = {'name': 'test', 'nodes': [], 'edges': []}
    await tools['aigc_workflow_create']('campaign', 1, workflow)
    await tools['aigc_workflow_create']('campaign', 1, workflow)
    first = calls[0][1]
    assert first == calls[1][1]
    assert first['scope']['conversation_id'] == 'session-a'
    assert first['scope']['installation_id'] == 'installation-a'
    other, other_calls = harness(grants, session='session-b')
    await other['aigc_workflow_create']('campaign', 1, workflow)
    assert first['idempotency_key'] != other_calls[0][1]['idempotency_key']
    again, again_calls = harness(grants)
    await again['aigc_workflow_create']('campaign', 1, workflow)
    assert first == again_calls[0][1]


@pytest.mark.asyncio
async def test_status_rejects_cross_session_task_without_disclosing_it():
    foreign = {'binding': {'installation_id': 'installation-a', 'conversation_id': 'other'}, 'secret': 'private'}
    tools, calls = harness({CATALOG: '1', CREATE: '1'}, tasks={'foreign': foreign})
    response = result(await tools['aigc_task_status']('foreign'))
    assert response['error'] == 'TASK_UNAVAILABLE'
    assert 'private' not in str(response)
    assert calls == []


@pytest.mark.asyncio
async def test_review_requires_host_media_context_and_never_accepts_model_identity():
    tools, calls = harness({'aigc.task.create': '1', 'aigc.review.complete': '1'})
    response = result(await tools['aigc_task_review']('fake', 'ACCEPTED', 'looks good'))
    assert 'error' in response
    assert calls == []


def test_registration_is_temporary_even_on_failure():
    agent = SimpleNamespace(toolkit=Toolkit(), model=None)
    original = agent.toolkit
    tools, _ = harness({CATALOG: '1'})
    with pytest.raises(RuntimeError):
        with bind_aigc_tools(agent, tools):
            assert 'aigc_workflow_catalog' in agent.toolkit.tools
            assert 'aigc_workflow_catalog' not in original.tools
            raise RuntimeError('cancelled or failed')
    assert agent.toolkit is original


@pytest.mark.asyncio
async def test_media_tracker_records_native_delivery_and_preserves_stream():
    from agentscope.message import Msg
    from qwenpaw.app.workspace.aigc_tools import track_media_delivery
    media = {'type': 'image', 'source': {'type': 'url', 'url': 'https://example.test/image.png'}}
    messages = [Msg('user', [media], 'user')]
    class Model:
        async def __call__(self, messages):
            async def stream():
                yield SimpleNamespace(id='response-1')
            return stream()
    agent = SimpleNamespace(model=Model())
    original = agent.model
    delivery = {}
    with track_media_delivery(agent, messages, delivery):
        stream = await agent.model(messages=[{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'https://example.test/image.png'}},
        ]}])
        assert len([chunk async for chunk in stream]) == 1
        assert delivery['delivered_modalities'] == ['image']
    assert agent.model is original


@pytest.mark.asyncio
@pytest.mark.parametrize('expert', ['traffic-expert', 'product-expert'])
async def test_authorized_agent_loop_has_tools_without_expert_specific_configuration(tmp_path, expert):
    from agentscope.message import Msg
    from qwenpaw.app.workspace.orchestration import AuthorizedWorkspaceRelease, run_workspace_orchestration_turn
    from qwenpaw.app.workspace.orchestration_contract import HOST_CAPABILITIES_V1, OrchestrationConfig
    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'runtime.py').write_text('''
class Runtime:
    async def handle(self, request, host):
        value = await host.call('agent.execute', {'messages': request.normalized_input['messages'], 'execution_mode': 'agent_loop'})
        await host.call('runtime.complete', {'invocation_id': request.invocation_id, 'message': value['message']})
def create_runtime(): return Runtime()
''')
    class Agent:
        def __init__(self):
            self.toolkit = Toolkit()
        async def __call__(self, messages):
            assert 'aigc_workflow_catalog' in self.toolkit.tools
            assert 'aigc_workflow_create' in self.toolkit.tools
            return Msg('assistant', 'ready', 'assistant')
    agent = Agent()
    authorization = AuthorizedWorkspaceRelease(
        installation_id=expert, release_id='release', release_digest='sha256:'+'a'*64,
        granted_capabilities={key: '1' for key in [*HOST_CAPABILITIES_V1, CATALOG, CREATE]},
        signed_workspace_files=frozenset({'runtime.py'}),
    )
    async def business_call(capability, arguments):
        return {}
    response = await run_workspace_orchestration_turn(
        agent=agent, original_messages=[Msg('user', 'create image', 'user')],
        request=SimpleNamespace(session_id='session', user_id='user', channel='console', channel_meta={}),
        agent_id=expert, workspace_root=root, state_storage_root=tmp_path / 'states',
        config=OrchestrationConfig(enabled=True, entrypoint='runtime.py:create_runtime', required_host_capabilities=HOST_CAPABILITIES_V1),
        authorization=authorization, business_call=business_call,
    )
    assert response.error_code is None
    assert 'aigc_workflow_catalog' not in agent.toolkit.tools


@pytest.mark.asyncio
async def test_uncertain_creation_returns_identity_for_status_recovery():
    async def fail(*args):
        raise RuntimeError('private-provider-details')
    tools = build_aigc_tools(grants={CATALOG: '1', CREATE: '1'},
        installation_id='i', conversation_id='s', business_call=fail,
        read_task=None, review_input=None, media_delivery={})
    reply = result(await tools['aigc_workflow_create']('campaign', 1, {}))
    assert reply['error'] == 'PLATFORM_OPERATION_UNCONFIRMED'
    assert reply['material_task_id'].startswith('material-')
    assert 'private-provider-details' not in str(reply)


@pytest.mark.asyncio
@pytest.mark.parametrize('delivery_kind,expected', [('image', None), ('video', 'MEDIA_NOT_DELIVERED')])
async def test_review_accepts_only_current_native_media(delivery_kind, expected):
    task = {'binding': {'installation_id': 'i', 'conversation_id': 's', 'material_task_id': 't'},
            'asset_id': 'a', 'status': 'SUBMITTED', 'review_assets': [{'asset_id': 'a'}]}
    context = {**task, 'media_kind': 'image', 'block_digest': 'digest'}
    calls = []
    async def call(capability, args):
        calls.append(args)
        return {'ok': True}
    tools = build_aigc_tools(grants={'aigc.task.create': '1', 'aigc.review.complete': '1'},
        installation_id='i', conversation_id='s', business_call=call,
        read_task=lambda key: task, review_input=context,
        media_delivery={'delivered_modalities': [delivery_kind], 'media_inputs': [{'block_digest': 'digest'}]})
    reply = result(await tools['aigc_task_review']('t', 'ACCEPTED', 'clear image'))
    assert reply.get('error') == expected
    assert bool(calls) == (expected is None)
    task['review_assets'] = [{'asset_id': 'new-asset'}]
    stale = result(await tools['aigc_task_review']('t', 'ACCEPTED', 'clear image'))
    assert stale['error'] == 'REVIEW_INPUT_UNAVAILABLE'


@pytest.mark.asyncio
async def test_failed_media_request_clears_previous_delivery():
    from agentscope.message import Msg
    from qwenpaw.app.workspace.aigc_tools import track_media_delivery
    media = {'type': 'image', 'source': {'type': 'url', 'url': 'https://example.test/a.png'}}
    class Model:
        async def __call__(self, **kwargs):
            raise RuntimeError('model unavailable')
    agent = SimpleNamespace(model=Model())
    delivery = {'delivered_modalities': ['image']}
    with track_media_delivery(agent, [Msg('user', [media], 'user')], delivery):
        with pytest.raises(RuntimeError):
            await agent.model(messages=[])
        assert delivery == {}


@pytest.mark.asyncio
async def test_current_review_task_is_discoverable_without_model_guessing_id():
    task = {'binding': {'installation_id': 'i', 'conversation_id': 's', 'material_task_id': 't'}}
    tools = build_aigc_tools(grants={'aigc.review.complete': '1', 'aigc.task.create': '1'},
        installation_id='i', conversation_id='s', business_call=lambda *args: None,
        read_task=lambda key: task if key == 't' else None,
        review_input=task, media_delivery={})
    assert result(await tools['aigc_task_status']())['task'] == task


@pytest.mark.asyncio
async def test_bridge_creates_real_owned_canvas_idempotently_without_generation(tmp_path):
    from qwenpaw.app.aigc.asset_service import AigcAssetService
    from qwenpaw.app.aigc.canvas_service import AigcCanvasService
    from qwenpaw.app.aigc.resource_store import AigcResourceStore, AigcResourceError
    from qwenpaw.app.aigc.capability_service import project_workflow_capability_catalog
    from qwenpaw.app.aigc.models import CapabilityList, AigcCapabilityInfo
    from qwenpaw.app.super_experts.aigc_adapter import AigcServiceAdapter
    from qwenpaw.app.super_experts.aigc_tasks import AigcTaskRepository
    from qwenpaw.app.super_experts.events import SuperExpertEventRepository
    from qwenpaw.app.super_experts.grants import SuperExpertGrantRepository
    from qwenpaw.app.super_experts.service import SuperExpertPlatformService
    from qwenpaw.app.sealed_agents.models import SealedReleaseRecord
    grants = SuperExpertGrantRepository(tmp_path / 'grants')
    release = SealedReleaseRecord(release_id='release', version='1.0.0',
        content_digest='sha256:'+'a'*64, signer_id='test', package_type='super_expert',
        capability_digest='sha256:'+'b'*64,
        declared_capabilities=((CATALOG, '1'), (CREATE, '1')))
    grant = grants.grant_installation(grants.preview('generic-expert', release, tenant_id='tenant'), administrator_id='admin')
    store = AigcResourceStore(tmp_path / 'studio')
    canvases = AigcCanvasService(store)
    async def catalog():
        return project_workflow_capability_catalog(CapabilityList(capabilities=[AigcCapabilityInfo(
            provider_id='provider', provider_name='Provider', model_id='image', model_name='Image',
            capability='text_to_image', source='model_registry')]))
    async def publish(event):
        return event
    service = SuperExpertPlatformService(grant_repository=grants,
        task_repository=AigcTaskRepository(tmp_path / 'tasks'),
        event_repository=SuperExpertEventRepository(tmp_path / 'events'),
        event_bus=SimpleNamespace(publish=publish),
        aigc_adapter=AigcServiceAdapter(canvases, AigcAssetService(store), catalog_loader=catalog))
    async def call(capability, arguments):
        arguments = dict(arguments)
        key = arguments.pop('idempotency_key')
        return await service.execute(tenant_id='tenant', user_id='owner',
            installation_id=grant.installation_id, capability=capability,
            contract_version='1', arguments=arguments, idempotency_key=key)
    tools = build_aigc_tools(grants=dict(grant.capabilities), installation_id=grant.installation_id,
        conversation_id='conversation', business_call=call, read_task=None, review_input=None, media_delivery={})
    workflow = {'schema_version': 1, 'title': 'Image', 'execution_preference': 'CUSTOMER_TRIGGERED',
        'nodes': [{'node_id': 'image', 'kind': 'image_generate', 'title': 'Image',
            'capability': 'text_to_image', 'provider_id': 'provider', 'model_id': 'image',
            'inputs': {'prompt': 'A classroom'}, 'parameters': {}, 'customer_action': 'CLICK_GENERATE'}],
        'edges': [], 'output_node_id': 'image', 'review_node_ids': ['image'], 'fallback_policy': 'FAIL_CLOSED'}
    first = result(await tools['aigc_workflow_create']('lesson', 1, workflow))
    assert 'error' not in first, first
    second = result(await tools['aigc_workflow_create']('lesson', 1, workflow))
    assert first == second
    binding = first['task']['binding']
    assert canvases.get('owner', binding['canvas_id']).nodes
    with pytest.raises(AigcResourceError):
        canvases.get('other-user', binding['canvas_id'])
    assert not list(store.directory('jobs').glob('*.json'))
    changed = {**workflow, 'title': 'Changed plan'}
    rejected = result(await tools['aigc_workflow_create']('lesson', 1, changed))
    assert rejected['error'] == 'PLATFORM_OPERATION_UNCONFIRMED'
    assert len(list(store.directory('canvases').glob('*.json'))) == 1


@pytest.mark.asyncio
async def test_real_agent_loop_can_call_scoped_tool_then_answer():
    from agentscope.agent import ReActAgent
    from agentscope.formatter import OpenAIChatFormatter
    from agentscope.message import Msg
    from agentscope.model import ChatModelBase, ChatResponse
    class Model(ChatModelBase):
        def __init__(self):
            super().__init__(model_name='scripted', stream=False)
            self.calls = 0
        async def __call__(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                assert any(tool['function']['name'] == 'aigc_workflow_catalog' for tool in kwargs['tools'])
                return ChatResponse(content=[{'type': 'tool_use', 'id': 'call-1',
                    'name': 'aigc_workflow_catalog', 'input': {}}])
            assert any('workflow_schema' in str(message) for message in messages)
            return ChatResponse(content=[{'type': 'text', 'text': 'Catalog checked.'}])
    model = Model()
    agent = ReActAgent(name='expert', sys_prompt='Use tools.', model=model,
        formatter=OpenAIChatFormatter(), toolkit=Toolkit(), max_iters=3)
    agent.set_console_output_enabled(False)
    original = agent.toolkit
    tools, calls = harness({CATALOG: '1'})
    with bind_aigc_tools(agent, tools):
        reply = await agent(Msg('user', 'Check capabilities', 'user'))
    assert reply.get_text_content() == 'Catalog checked.'
    assert model.calls == 2 and len(calls) == 1
    assert agent.toolkit is original


def test_all_granted_aigc_tools_register_with_valid_review_schema():
    tools, _ = harness({CATALOG: '1', CREATE: '1', 'aigc.task.create': '1',
                        'aigc.task.resume': '1', 'aigc.review.complete': '1'})
    agent = SimpleNamespace(toolkit=Toolkit())
    with bind_aigc_tools(agent, tools):
        schemas = agent.toolkit.get_json_schemas()
        review = next(item['function'] for item in schemas if item['function']['name'] == 'aigc_task_review')
        assert review['parameters']['properties']['decision']['enum'] == ['ACCEPTED', 'REVISION_REQUIRED']
        assert len(schemas) == 5
