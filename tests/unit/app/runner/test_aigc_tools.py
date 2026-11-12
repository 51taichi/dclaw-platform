import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentscope.tool import Toolkit

from qwenpaw.app.workspace.aigc_tools import build_aigc_tools, bind_aigc_tools


CATALOG = 'aigc.workflow.capabilities.list/1'
CREATE = 'aigc.workflow.create/1'
LEGACY_LUYU_1_1_22 = json.loads(
    (
        Path(__file__).parents[3]
        / 'fixtures/super_expert/luyu-aigc-v1/production-1.1.22.json'
    ).read_text(encoding='utf-8'),
)


def harness(grants=None, session='session-a', tasks=None, catalog=None):
    calls = []
    async def call(capability, arguments):
        calls.append((capability, arguments))
        if capability == CATALOG:
            return catalog if catalog is not None else {'nodes': [], 'available_models': []}
        return {'task': arguments}
    tools = build_aigc_tools(
        grants=grants or {}, installation_id='installation-a',
        conversation_id=session, business_call=call,
        read_task=lambda key: (tasks or {}).get(key),
        review_input=None, media_delivery={},
    )
    return tools, calls


def result(response):
    return json.loads(response.content[0]['text'])


def valid_image_workflow():
    return {
        'schema_version': 1,
        'title': 'Image task',
        'execution_preference': 'CUSTOMER_TRIGGERED',
        'nodes': [{
            'node_id': 'image',
            'kind': 'image_generate',
            'title': 'Image',
            'capability': 'text_to_image',
            'provider_id': 'image-provider',
            'model_id': 'image-v1',
            'inputs': {'prompt': 'A classroom'},
            'parameters': {'aspect_ratio': '9:16', 'count': 1},
            'customer_action': 'CLICK_GENERATE',
            'optional': False,
        }],
        'edges': [],
        'output_node_id': 'image',
        'review_node_ids': ['image'],
        'fallback_policy': 'FAIL_CLOSED',
    }


def test_only_granted_supported_capabilities_are_exposed():
    assert harness()[0] == {}
    assert harness({'mcp.execute': '1', CATALOG: '2'})[0] == {}
    assert set(harness({CATALOG: '1'})[0]) == {'aigc_workflow_catalog'}
    assert 'aigc_workflow_create' not in harness({CREATE: '1'})[0]


@pytest.mark.asyncio
async def test_catalog_filters_to_requested_kind_and_returns_live_executable_example():
    catalog = {
        'schema_version': 1,
        'nodes': [
            {
                'kind': 'image_generate', 'title': '图片生成',
                'provisioning': 'AUTO_PROVISIONABLE',
                'capabilities': ['text_to_image', 'reference_image'],
                'input_keys': ['prompt', 'reference_asset_ids'],
                'parameter_keys': ['aspect_ratio', 'count'],
                'input_slots': {'prompt': ['text']}, 'output_type': 'image',
                'control_id': 'aigc.image.generate-submit',
                'customer_actions': ['CLICK_GENERATE'],
                'input_schema': {'type': 'object'},
                'parameter_schema': {
                    'type': 'object',
                    'properties': {
                        'aspect_ratio': {'type': 'string', 'default': '1:1'},
                        'count': {'type': 'integer', 'default': 1},
                    },
                },
            },
            {
                'kind': 'video_generate', 'title': '视频生成',
                'provisioning': 'AUTO_PROVISIONABLE',
                'capabilities': ['text_to_video'],
                'input_keys': ['prompt'], 'parameter_keys': ['duration_seconds'],
                'input_slots': {'prompt': ['text']}, 'output_type': 'video',
                'control_id': 'aigc.video.generate-submit',
                'customer_actions': ['CLICK_GENERATE'],
                'input_schema': {'type': 'object'},
                'parameter_schema': {'type': 'object'},
            },
        ],
        'available_models': [
            {
                'provider_id': 'vision-provider', 'provider_name': 'Vision',
                'model_id': 'vision-v1', 'model_name': 'Vision V1',
                'capability': 'reference_image', 'source': 'model_registry',
                'parameter_schema': {'type': 'object'},
            },
            {
                'provider_id': 'image-provider', 'provider_name': 'Images',
                'model_id': 'image-v1', 'model_name': 'Image V1',
                'capability': 'text_to_image', 'source': 'model_registry',
                'parameter_schema': {'type': 'object'},
            },
            {
                'provider_id': 'video-provider', 'provider_name': 'Videos',
                'model_id': 'video-v1', 'model_name': 'Video V1',
                'capability': 'text_to_video', 'source': 'model_registry',
                'parameter_schema': {'type': 'object'},
            },
        ],
    }
    tools, calls = harness({CATALOG: '1'}, catalog=catalog)

    reply = result(await tools['aigc_workflow_catalog'](['image_generate']))

    assert calls == [(CATALOG, {})]
    assert [node['kind'] for node in reply['catalog']['nodes']] == ['image_generate']
    assert [model['model_id'] for model in reply['catalog']['available_models']] == ['vision-v1', 'image-v1']
    example = reply['workflow_examples'][0]
    assert example['nodes'][0]['provider_id'] == 'image-provider'
    assert example['nodes'][0]['model_id'] == 'image-v1'
    assert example['nodes'][0]['capability'] == 'text_to_image'
    assert example['nodes'][0]['parameters'] == {'aspect_ratio': '1:1', 'count': 1}
    assert example['review_node_ids'] == ['image_generate_1']
    assert isinstance(reply['workflow_schema'], dict)


@pytest.mark.asyncio
async def test_unfiltered_catalog_does_not_expand_output_with_examples():
    catalog = {
        'schema_version': 1,
        'nodes': [{
            'kind': 'image_generate', 'title': '图片生成',
            'provisioning': 'AUTO_PROVISIONABLE',
            'capabilities': ['text_to_image'], 'input_keys': ['prompt'],
            'parameter_schema': {'type': 'object'},
            'customer_actions': ['CLICK_GENERATE'],
        }],
        'available_models': [{
            'provider_id': 'provider', 'model_id': 'model',
            'capability': 'text_to_image',
        }],
    }
    tools, _ = harness({CATALOG: '1'}, catalog=catalog)

    reply = result(await tools['aigc_workflow_catalog']())

    assert reply['workflow_examples'] == []


@pytest.mark.asyncio
async def test_catalog_preserves_deterministic_platform_rejection():
    from qwenpaw.app.super_experts.service import SuperExpertPlatformError

    async def reject(*_args):
        raise SuperExpertPlatformError('capability is not authorized')

    tools = build_aigc_tools(
        grants={CATALOG: '1'}, installation_id='i', conversation_id='s',
        business_call=reject, read_task=None, review_input=None,
        media_delivery={},
    )

    reply = result(await tools['aigc_workflow_catalog']())

    assert reply == {
        'error': 'CAPABILITY_NOT_AUTHORIZED',
        'retryable': True,
        'guidance': (
            'Refresh the expert installation grants before retrying this capability.'
        ),
    }


def test_catalog_tool_schema_exposes_complete_workflow_contract_and_kind_filter():
    tools, _ = harness({CATALOG: '1', CREATE: '1'})
    agent = SimpleNamespace(toolkit=Toolkit())
    with bind_aigc_tools(agent, tools):
        schemas = {item['function']['name']: item['function'] for item in agent.toolkit.get_json_schemas()}
        workflow = schemas['aigc_workflow_create']['parameters']['properties']['workflow']
        assert workflow['type'] == 'object'
        assert set(workflow['required']) == {
            'schema_version', 'title', 'execution_preference', 'nodes',
            'output_node_id', 'fallback_policy',
        }
        node = workflow['properties']['nodes']['items']
        assert set(node['required']) == {
            'node_id', 'kind', 'title', 'customer_action',
        }
        assert set(node['properties']) >= {
            'capability', 'provider_id', 'model_id', 'inputs', 'parameters',
        }
        assert '$ref' not in json.dumps(workflow)
        assert '$defs' not in json.dumps(workflow)
        assert 'const' not in json.dumps(workflow)
        schema_version = workflow['properties']['schema_version']
        assert schema_version['type'] == 'integer'
        assert schema_version['default'] == 1
        assert 'Must equal 1.' in schema_version['description']
        kinds = schemas['aigc_workflow_catalog']['parameters']['properties']['node_kinds']
        assert kinds['type'] == 'array'


def test_create_tool_schema_is_accepted_by_native_gemini_types():
    from google.genai import types

    tools, _ = harness({CATALOG: '1', CREATE: '1'})
    agent = SimpleNamespace(toolkit=Toolkit())
    with bind_aigc_tools(agent, tools):
        create = next(
            item['function'] for item in agent.toolkit.get_json_schemas()
            if item['function']['name'] == 'aigc_workflow_create'
        )

    config = types.GenerateContentConfig(tools=[types.Tool(
        function_declarations=[types.FunctionDeclaration(
            name=create['name'],
            description=create['description'],
            parameters=create['parameters'],
        )],
    )])

    assert config.tools[0].function_declarations[0].name == 'aigc_workflow_create'


async def call_create_through_toolkit(arguments):
    tools, calls = harness({CATALOG: '1', CREATE: '1'})
    agent = SimpleNamespace(toolkit=Toolkit())
    with bind_aigc_tools(agent, tools):
        stream = await agent.toolkit.call_tool_function({
            'type': 'tool_use', 'id': 'create-call',
            'name': 'aigc_workflow_create', 'input': arguments,
        })
        responses = [response async for response in stream]
    return result(responses[-1]), calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('arguments', 'issues'),
    [
        (
            {},
            [
                {'field': 'task_key', 'code': 'FIELD_REQUIRED'},
                {'field': 'content_revision', 'code': 'FIELD_REQUIRED'},
                {'field': 'workflow', 'code': 'FIELD_REQUIRED'},
            ],
        ),
        (
            {
                'task_key': 'campaign', 'content_revision': 1,
                'workflow': valid_image_workflow(), 'unknown': True,
            },
            [{'field': 'unknown', 'code': 'FIELD_NOT_ALLOWED'}],
        ),
        (
            {
                'task_key': '', 'content_revision': 0,
                'workflow': valid_image_workflow(),
            },
            [
                {'field': 'task_key', 'code': 'INVALID_VALUE'},
                {'field': 'content_revision', 'code': 'INVALID_VALUE'},
            ],
        ),
    ],
)
async def test_create_toolkit_boundary_returns_structured_top_level_errors(
    arguments, issues,
):
    reply, calls = await call_create_through_toolkit(arguments)

    assert reply == {
        'error': 'INVALID_WORKFLOW_REQUEST',
        'retryable': True,
        'issues': issues,
        'guidance': (
            'Correct the listed request fields, then retry with the same task '
            'key and content revision.'
        ),
    }
    assert calls == []


@pytest.mark.asyncio
async def test_create_uses_host_scope_and_stable_identity_across_turns():
    grants = {CATALOG: '1', CREATE: '1'}
    tools, calls = harness(grants)
    workflow = valid_image_workflow()
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
async def test_create_normalizes_serialized_workflow_object_before_dispatch():
    tools, calls = harness({CATALOG: '1', CREATE: '1'})
    workflow = valid_image_workflow()
    serialized = json.dumps(workflow)

    reply = result(await tools['aigc_workflow_create']('campaign', 1, serialized))

    assert 'error' not in reply
    assert calls[0][0] == CREATE
    assert calls[0][1]['workflow'] == workflow


@pytest.mark.asyncio
async def test_create_rejects_incomplete_workflow_before_platform_dispatch():
    tools, calls = harness({CATALOG: '1', CREATE: '1'})
    workflow = {
        'nodes': [{
            'node_id': 'hook_card', 'kind': 'image_generate',
            'title': 'Hook', 'inputs': {'prompt': 'Create a hook card'},
            'parameters': {'aspect_ratio': '9:16', 'count': 1},
            'customer_action': 'CLICK_GENERATE', 'optional': False,
        }],
        'edges': [], 'output_node_id': 'hook_card',
        'review_node_ids': ['hook_card'],
    }

    reply = result(await tools['aigc_workflow_create']('campaign', 1, workflow))

    assert reply == {
        'error': 'INVALID_WORKFLOW_REQUEST',
        'retryable': True,
        'issues': [
            {'field': 'workflow.schema_version', 'code': 'FIELD_REQUIRED'},
            {'field': 'workflow.title', 'code': 'FIELD_REQUIRED'},
            {'field': 'workflow.execution_preference', 'code': 'FIELD_REQUIRED'},
            {'field': 'workflow.fallback_policy', 'code': 'FIELD_REQUIRED'},
            {'field': 'workflow.nodes.0.capability', 'code': 'FIELD_REQUIRED'},
            {'field': 'workflow.nodes.0.provider_id', 'code': 'FIELD_REQUIRED'},
            {'field': 'workflow.nodes.0.model_id', 'code': 'FIELD_REQUIRED'},
        ],
        'guidance': (
            'Correct the listed fields using the latest catalog example, '
            'then retry with the same task key and content revision.'
        ),
    }
    assert calls == []


@pytest.mark.asyncio
async def test_create_requires_model_binding_for_generated_nodes_before_dispatch():
    tools, calls = harness({CATALOG: '1', CREATE: '1'})
    workflow = valid_image_workflow()
    for field in ('capability', 'provider_id', 'model_id'):
        workflow['nodes'][0].pop(field)

    reply = result(await tools['aigc_workflow_create']('campaign', 1, workflow))

    assert reply['error'] == 'INVALID_WORKFLOW_REQUEST'
    assert reply['issues'] == [
        {'field': 'workflow.nodes.0.capability', 'code': 'FIELD_REQUIRED'},
        {'field': 'workflow.nodes.0.provider_id', 'code': 'FIELD_REQUIRED'},
        {'field': 'workflow.nodes.0.model_id', 'code': 'FIELD_REQUIRED'},
    ]
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('platform_message', 'platform_code', 'guidance'),
    [
        (
            'MODEL_UNAVAILABLE',
            'MODEL_UNAVAILABLE',
            'Refresh the catalog and copy provider_id, model_id and capability '
            'from one compatible available model entry.',
        ),
        (
            'IDEMPOTENCY_CONFLICT',
            'IDEMPOTENCY_CONFLICT',
            'Reuse a content revision only for an identical workflow; increment '
            'content_revision when the production plan changes.',
        ),
        (
            'AIGC service is unavailable',
            'AIGC_SERVICE_UNAVAILABLE',
            'The AIGC service is temporarily unavailable. Retry the same task key '
            'and content revision later.',
        ),
        (
            'capability is not authorized',
            'CAPABILITY_NOT_AUTHORIZED',
            'Refresh the expert installation grants before retrying this capability.',
        ),
        (
            'illegal task transition',
            'TASK_STATE_INVALID',
            'Read the current task status and choose an action allowed from that state.',
        ),
    ],
)
async def test_create_preserves_actionable_platform_rejections(
    platform_message, platform_code, guidance,
):
    from qwenpaw.app.super_experts.service import SuperExpertPlatformError

    async def reject(*_args):
        raise SuperExpertPlatformError(platform_message)

    tools = build_aigc_tools(
        grants={CATALOG: '1', CREATE: '1'},
        installation_id='i', conversation_id='s', business_call=reject,
        read_task=None, review_input=None, media_delivery={},
    )

    reply = result(await tools['aigc_workflow_create'](
        'campaign', 1, valid_image_workflow(),
    ))

    assert reply == {
        'error': platform_code,
        'retryable': True,
        'guidance': guidance,
    }


@pytest.mark.asyncio
async def test_create_treats_unknown_wrapped_platform_error_as_unconfirmed():
    from qwenpaw.app.super_experts.service import SuperExpertPlatformError

    async def reject(*_args):
        raise SuperExpertPlatformError('unexpected validation after persistence')

    tools = build_aigc_tools(
        grants={CATALOG: '1', CREATE: '1'},
        installation_id='i', conversation_id='s', business_call=reject,
        read_task=None, review_input=None, media_delivery={},
    )

    reply = result(await tools['aigc_workflow_create'](
        'campaign', 1, valid_image_workflow(),
    ))

    assert reply['error'] == 'PLATFORM_OPERATION_UNCONFIRMED'
    assert reply['material_task_id'].startswith('material-')
    assert 'unexpected validation' not in str(reply)


@pytest.mark.asyncio
async def test_create_rejects_registered_node_schema_errors_before_dispatch():
    tools, calls = harness({CATALOG: '1', CREATE: '1'})
    workflow = {
        'schema_version': 1,
        'title': 'Long image task',
        'execution_preference': 'CUSTOMER_TRIGGERED',
        'nodes': [{
            'node_id': 'long_image',
            'kind': 'long_image_export',
            'title': 'Long image',
            'inputs': {'title': 'Course introduction'},
            'parameters': {'width': 'wide', 'slice_height': False},
            'customer_action': 'CLICK_GENERATE',
            'optional': False,
        }],
        'edges': [],
        'output_node_id': 'long_image',
        'review_node_ids': ['long_image'],
        'fallback_policy': 'FAIL_CLOSED',
    }

    reply = result(await tools['aigc_workflow_create']('campaign', 1, workflow))

    assert reply['error'] == 'INVALID_WORKFLOW_REQUEST'
    assert reply['issues'] == [
        {'field': 'workflow.nodes.0.parameters.slice_height', 'code': 'INVALID_VALUE'},
        {'field': 'workflow.nodes.0.parameters.width', 'code': 'INVALID_VALUE'},
    ]
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('workflow', 'received'),
    [('not-json', 'string'), ('[]', 'array'), ([], 'array')],
)
async def test_create_rejects_unusable_workflow_with_actionable_field_error(workflow, received):
    tools, calls = harness({CATALOG: '1', CREATE: '1'})

    reply = result(await tools['aigc_workflow_create']('campaign', 1, workflow))

    assert reply == {
        'error': 'INVALID_WORKFLOW_REQUEST',
        'field': 'workflow',
        'expected': 'object',
        'received': received,
        'retryable': True,
        'guidance': 'Pass workflow as a nested JSON object, not a serialized JSON string.',
    }
    assert calls == []


@pytest.mark.asyncio
async def test_status_rejects_cross_session_task_without_disclosing_it():
    foreign = {'binding': {'installation_id': 'installation-a', 'conversation_id': 'other'}, 'secret': 'private'}
    tools, calls = harness({CATALOG: '1', CREATE: '1'}, tasks={'foreign': foreign})
    response = result(await tools['aigc_task_status']('foreign'))
    assert response['error'] == 'TASK_UNAVAILABLE'
    assert 'private' not in str(response)
    assert calls == []


@pytest.mark.asyncio
async def test_retired_review_grant_registers_read_only_compatibility_tool():
    tools, calls = harness({'aigc.task.create': '1', 'aigc.review.complete': '1'})
    assert 'aigc_task_review' in tools
    assert 'aigc_task_status' in tools
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('task_status', 'customer_action_required'),
    [('ACCEPTED', False), ('IN_PROGRESS', True)],
)
async def test_legacy_review_tool_reads_customer_completion_without_writing(
    task_status,
    customer_action_required,
):
    task = {
        'binding': {
            'installation_id': 'installation-a',
            'conversation_id': 'session-a',
            'agent_task_id': 'content-a',
            'content_revision': 1,
            'material_task_id': 'material-a',
            'canvas_id': 'canvas-a',
            'node_id': 'output-a',
        },
        'status': task_status,
        'asset_id': 'asset-a',
    }
    tools, calls = harness(
        {'aigc.review.complete': '1'},
        tasks={'material-a': task},
    )

    receipt = result(
        await tools['aigc_task_review'](
            'material-a',
            'ACCEPTED',
            'legacy signed instruction',
        ),
    )

    assert receipt['status'] == task_status
    assert receipt['compatibility_mode'] == 'legacy_read_only'
    assert receipt['completion_source'] == (
        'customer' if task_status == 'ACCEPTED' else None
    )
    assert receipt['review_performed'] is False
    assert receipt['write_applied'] is False
    assert receipt['customer_action_required'] is customer_action_required
    assert receipt['task']['status'] == task_status
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'binding_change',
    [
        {'installation_id': 'installation-b'},
        {'conversation_id': 'session-b'},
        {'material_task_id': 'material-b'},
    ],
)
async def test_legacy_review_tool_cannot_read_foreign_task(binding_change):
    binding = {
        'installation_id': 'installation-a',
        'conversation_id': 'session-a',
        'agent_task_id': 'content-a',
        'content_revision': 1,
        'material_task_id': 'material-a',
        'canvas_id': 'canvas-a',
        'node_id': 'output-a',
    }
    binding.update(binding_change)
    task = {'binding': binding, 'status': 'ACCEPTED', 'asset_id': 'asset-a'}
    tools = build_aigc_tools(
        grants={'aigc.review.complete': '1'},
        installation_id='installation-a',
        conversation_id='session-a',
        business_call=lambda *_args: pytest.fail('must stay read-only'),
        read_task=lambda _key: task,
        review_input={'binding': binding},
        media_delivery={},
    )

    receipt = result(
        await tools['aigc_task_review'](
            'material-a',
            'ACCEPTED',
            'legacy signed instruction',
        ),
    )

    assert receipt == {'error': 'TASK_UNAVAILABLE'}


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
async def test_media_tracker_records_agentscope_local_image_delivery(tmp_path):
    from agentscope.message import Msg
    from qwenpaw.app.workspace.aigc_tools import track_media_delivery

    image = tmp_path / "review.jpg"
    image.write_bytes(b"review-image")
    media = {
        "type": "image",
        "source": {"type": "url", "url": str(image)},
    }
    messages = [Msg("user", [media], "user")]

    class Model:
        async def __call__(self, messages):
            return SimpleNamespace(id="response-local")

    agent = SimpleNamespace(model=Model())
    delivery = {}
    with track_media_delivery(agent, messages, delivery):
        await agent.model(messages=messages)

    assert delivery["delivered_modalities"] == ["image"]
    assert delivery["media_inputs"][0]["block_digest"].startswith("sha256:")


@pytest.mark.asyncio
async def test_media_tracker_keeps_delivery_across_later_agent_model_calls():
    from agentscope.message import Msg
    from qwenpaw.app.workspace.aigc_tools import track_media_delivery

    url = "https://example.test/review.jpg"
    media = {"type": "image", "source": {"type": "url", "url": url}}
    messages = [Msg("user", [media], "user")]

    class Model:
        async def __call__(self, messages):
            return SimpleNamespace(id="response")

    agent = SimpleNamespace(model=Model())
    delivery = {}
    with track_media_delivery(agent, messages, delivery):
        await agent.model(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                },
            ],
        )
        await agent.model(messages=[{"role": "user", "content": "continue"}])

    assert delivery["delivered_modalities"] == ["image"]


@pytest.mark.asyncio
async def test_media_tracker_records_dashscope_image_delivery(tmp_path):
    import base64

    from agentscope.message import Msg
    from qwenpaw.app.workspace.aigc_tools import track_media_delivery

    content = b"dashscope-review-image"
    image = tmp_path / "review.jpg"
    image.write_bytes(content)
    media = {
        "type": "image",
        "source": {"type": "url", "url": str(image)},
    }
    messages = [Msg("user", [media], "user")]
    encoded = base64.b64encode(content).decode()

    class Model:
        async def __call__(self, messages):
            return SimpleNamespace(id="response-dashscope")

    agent = SimpleNamespace(model=Model())
    delivery = {}
    with track_media_delivery(agent, messages, delivery):
        await agent.model(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": f"data:image/jpeg;base64,{encoded}"},
                    ],
                },
            ],
        )

    assert delivery["delivered_modalities"] == ["image"]


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
@pytest.mark.parametrize('review_granted', [True, False])
async def test_review_metadata_does_not_create_a_review_only_agent_loop(
    tmp_path,
    review_granted,
):
    from agentscope.message import Msg
    from qwenpaw.app.workspace.orchestration import (
        AuthorizedWorkspaceRelease,
        run_workspace_orchestration_turn,
    )
    from qwenpaw.app.workspace.orchestration_contract import (
        HOST_CAPABILITIES_V1,
        OrchestrationConfig,
    )

    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'runtime.py').write_text('''
class Runtime:
    async def handle(self, request, host):
        value = await host.call('agent.execute', {'messages': request.normalized_input['messages'], 'execution_mode': 'agent_loop'})
        await host.call('runtime.complete', {'invocation_id': request.invocation_id, 'message': value['message']})
def create_runtime(): return Runtime()
''')

    async def read_agent_skill(skill_name: str):
        return skill_name

    async def execute_shell_command(command: str):
        return command

    class Agent:
        def __init__(self):
            self.toolkit = Toolkit()
            self.toolkit.register_tool_function(read_agent_skill)
            self.toolkit.register_tool_function(execute_shell_command)

        async def __call__(self, _messages):
            assert ('aigc_task_review' in self.toolkit.tools) is review_granted
            assert 'read_agent_skill' in self.toolkit.tools
            return Msg('assistant', 'reviewed', 'assistant')

    binding = {
        'installation_id': 'expert',
        'conversation_id': 'session',
        'agent_task_id': 'content',
        'content_revision': 1,
        'material_task_id': 'material',
        'canvas_id': 'canvas',
        'node_id': 'image',
    }
    task = {
        'binding': binding,
        'asset_id': 'asset',
        'status': 'SUBMITTED',
        'review_assets': [{'node_id': 'image', 'asset_id': 'asset'}],
    }
    authorization = AuthorizedWorkspaceRelease(
        installation_id='expert', release_id='release',
        release_digest='sha256:' + 'a' * 64,
        granted_capabilities={
            **{key: '1' for key in HOST_CAPABILITIES_V1},
            'aigc.task.create': '1',
            **({'aigc.review.complete': '1'} if review_granted else {}),
        },
        signed_workspace_files=frozenset({'runtime.py'}),
    )
    response = await run_workspace_orchestration_turn(
        agent=Agent(),
        original_messages=[Msg('user', 'review image', 'user')],
        request=SimpleNamespace(
            session_id='session', user_id='user', channel='console',
            channel_meta={},
        ),
        agent_id='expert', workspace_root=root,
        state_storage_root=tmp_path / 'states',
        config=OrchestrationConfig(
            enabled=True,
            entrypoint='runtime.py:create_runtime',
            required_host_capabilities=HOST_CAPABILITIES_V1,
        ),
        authorization=authorization,
        business_call=lambda *_args: {},
        read_aigc_task=lambda key: task if key == 'material' else None,
        safe_metadata={
            'aigcReviewInput': {
                'binding': binding,
                'asset_id': 'asset',
                'review_assets': task['review_assets'],
                'media_kind': 'image',
                'block_digest': 'sha256:block',
            },
        },
    )

    assert response.error_code is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('task_status', 'expected_reply', 'customer_action_required'),
    [
        ('ACCEPTED', '客户已完成素材任务，继续后续会话。', False),
        ('IN_PROGRESS', '请先进入任务页完成素材任务。', True),
    ],
)
async def test_production_1_1_22_luyu_path_adapts_review_tool_read_only(
    tmp_path,
    task_status,
    expected_reply,
    customer_action_required,
):
    """Exercise the signed 1.1.22 runtime's agent.execute compatibility path."""
    from agentscope.message import Msg
    from qwenpaw.app.workspace.orchestration import (
        AuthorizedWorkspaceRelease,
        run_workspace_orchestration_turn,
    )
    from qwenpaw.app.workspace.orchestration_contract import (
        HOST_CAPABILITIES_V1,
        OrchestrationConfig,
    )

    assert LEGACY_LUYU_1_1_22['version'] == '1.1.22'
    assert LEGACY_LUYU_1_1_22['runtime']['calls_agent_execute'] is True
    assert LEGACY_LUYU_1_1_22['runtime']['calls_runtime_complete'] is True
    assert 'aigc.review.complete' in LEGACY_LUYU_1_1_22['capabilities']
    assert 'aigc_task_review' in LEGACY_LUYU_1_1_22['workflow_rule']
    assert 'ACCEPTED' in LEGACY_LUYU_1_1_22['workflow_rule']

    root = tmp_path / 'legacy-luyu-workspace'
    root.mkdir()
    (root / 'runtime.py').write_text('''
class TransparentRuntime:
    async def handle(self, request, host):
        await host.call('session.context', {})
        candidate = await host.call('agent.execute', {
            'messages': request.normalized_input['messages'],
            'execution_mode': 'agent_loop',
            'public_stream': True,
        })
        await host.call('runtime.complete', {
            'invocation_id': request.invocation_id,
            'message': candidate['message'],
        })
def create_runtime(): return TransparentRuntime()
''')
    binding = {
        'installation_id': 'legacy-luyu-installation',
        'conversation_id': 'session',
        'agent_task_id': 'content',
        'content_revision': 1,
        'material_task_id': 'material',
        'canvas_id': 'canvas',
        'node_id': 'output',
    }
    task = {
        'binding': binding,
        'asset_id': 'asset',
        'status': task_status,
        'review_assets': [],
    }
    business_calls = []

    async def business_call(capability, arguments):
        business_calls.append((capability, arguments))
        raise AssertionError('legacy review compatibility must not write')

    class Agent:
        def __init__(self):
            self.toolkit = Toolkit()

        async def __call__(self, _messages):
            assert 'aigc_task_status' in self.toolkit.tools
            assert 'aigc_task_review' in self.toolkit.tools
            status_tool = self.toolkit.tools['aigc_task_status'].original_func
            review_tool = self.toolkit.tools['aigc_task_review'].original_func
            status = result(await status_tool('material'))
            assert status['task']['status'] == task_status
            receipt = result(
                await review_tool(
                    'material',
                    'ACCEPTED',
                    'legacy signed instruction requires this call',
                ),
            )
            assert receipt['status'] == task_status
            assert receipt['compatibility_mode'] == 'legacy_read_only'
            assert receipt['completion_source'] == (
                'customer' if task_status == 'ACCEPTED' else None
            )
            assert receipt['review_performed'] is False
            assert receipt['write_applied'] is False
            assert (
                receipt['customer_action_required']
                is customer_action_required
            )
            return Msg('assistant', expected_reply, 'assistant')

    authorization = AuthorizedWorkspaceRelease(
        installation_id='legacy-luyu-installation',
        release_id='luyu-dclaw-agent-1.1.22',
        release_digest=LEGACY_LUYU_1_1_22['content_digest'],
        granted_capabilities={
            **{key: '1' for key in HOST_CAPABILITIES_V1},
            'aigc.task.create': '1',
            'aigc.asset.submit': '1',
            'aigc.review.complete': '1',
        },
        signed_workspace_files=frozenset({'runtime.py'}),
    )
    response = await run_workspace_orchestration_turn(
        agent=Agent(),
        original_messages=[Msg('user', '继续刚才的素材任务', 'user')],
        request=SimpleNamespace(
            session_id='session',
            user_id='user',
            channel='console',
            channel_meta={},
        ),
        agent_id='luyu_dclaw_agent',
        workspace_root=root,
        state_storage_root=tmp_path / 'states',
        config=OrchestrationConfig(
            enabled=True,
            entrypoint='runtime.py:create_runtime',
            required_host_capabilities=HOST_CAPABILITIES_V1,
        ),
        authorization=authorization,
        business_call=business_call,
        read_aigc_task=lambda key: task if key == 'material' else None,
    )

    assert response.error_code is None
    assert response.message['content'] == [
        {'type': 'text', 'text': expected_reply},
    ]
    assert business_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        'continuation_fails',
        'budget_exhausted',
        'setup_fails',
        'initial_review_fails',
        'expected_reply',
        'expected_calls',
    ),
    [
        (False, False, False, True, 'production continued', 2),
        (False, False, False, False, 'production continued', 2),
        (False, True, False, True, 'production continued', 3),
        (
            True,
            False,
            False,
            True,
            '素材审核已完成，但后续制作未能完整结束，请查看当前任务状态后再重试。',
            2,
        ),
        (
            False,
            False,
            True,
            True,
            '素材审核已完成，但后续制作未能完整结束，请查看当前任务状态后再重试。',
            1,
        ),
    ],
)
@pytest.mark.skip(reason="Agent review continuation was retired in platform 2.47")
async def test_accepted_review_failure_continues_with_full_aigc_tools(
    tmp_path,
    monkeypatch,
    continuation_fails,
    budget_exhausted,
    setup_fails,
    initial_review_fails,
    expected_reply,
    expected_calls,
):
    """Catch accepted reviews getting stranded in the review-only tool scope."""
    from agentscope.message import Msg
    from qwenpaw.app.workspace.orchestration import (
        AuthorizedWorkspaceRelease,
        run_workspace_orchestration_turn,
        WorkspaceStateTransaction,
    )
    from qwenpaw.app.workspace.orchestration_contract import (
        HOST_CAPABILITIES_V1,
        OrchestrationConfig,
    )

    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'runtime.py').write_text('''
from pathlib import Path
class Runtime:
    async def handle(self, request, host):
        if getattr(request, '_runtime_continuation', False):
            assert 'aigcReviewInput' not in request.safe_metadata
        try:
            value = await host.call('agent.execute', {
                'messages': request.normalized_input['messages'],
                'execution_mode': 'agent_loop',
            })
        except Exception:
            await host.call('runtime.fail', {
                'invocation_id': request.invocation_id,
                'error_code': 'runtime_failed',
            })
            return
        diagnostics = {}
        marker = Path(request.transaction_root) / 'review-budget-used'
        if (request.safe_metadata.get('forceBudgetOnce') is True
                and request.safe_metadata.get('aigcReviewContinuation') is True
                and not marker.exists()):
            marker.write_text('used')
            diagnostics = {'continuation_reason': 'turn_budget_exhausted'}
        await host.call('runtime.complete', {
            'invocation_id': request.invocation_id,
            'message': value['message'],
            'diagnostics': diagnostics,
        })
def create_runtime(): return Runtime()
''')

    async def read_agent_skill(skill_name: str):
        return skill_name

    async def imagegen(prompt: str):
        return prompt

    binding = {
        'installation_id': 'expert',
        'conversation_id': 'session',
        'agent_task_id': 'content',
        'content_revision': 1,
        'material_task_id': 'material',
        'canvas_id': 'canvas',
        'node_id': 'script',
    }
    task = {
        'binding': binding,
        'asset_id': 'asset',
        'status': 'SUBMITTED',
        'review_assets': [{'node_id': 'script', 'asset_id': 'asset'}],
    }

    class Agent:
        def __init__(self):
            self.calls = 0
            self._sys_prompt = 'base prompt'
            self.toolkit = Toolkit()
            self.toolkit.register_tool_function(read_agent_skill)
            self.toolkit.register_tool_function(imagegen)

        async def __call__(self, _messages):
            self.calls += 1
            if self.calls == 1:
                assert set(self.toolkit.tools) == {
                    'read_agent_skill',
                    'aigc_task_review',
                }
                review = self.toolkit.tools['aigc_task_review'].original_func
                await review('material', 'ACCEPTED', '脚本内容可用')
                if initial_review_fails:
                    raise RuntimeError('attempted follow-up work in review-only scope')
                return Msg('assistant', 'reviewed', 'assistant')
            assert 'aigc_workflow_catalog' in self.toolkit.tools
            assert 'aigc_workflow_create' in self.toolkit.tools
            assert 'AIGC review has been accepted' in self._sys_prompt
            if continuation_fails and self.calls == 2:
                raise RuntimeError('follow-up provider unavailable')
            if budget_exhausted and self.calls == 2:
                return Msg('assistant', 'checkpoint', 'assistant')
            return Msg('assistant', 'production continued', 'assistant')

    agent = Agent()
    authorization = AuthorizedWorkspaceRelease(
        installation_id='expert', release_id='release',
        release_digest='sha256:' + 'a' * 64,
        granted_capabilities={
            **{key: '1' for key in HOST_CAPABILITIES_V1},
            CATALOG: '1',
            CREATE: '1',
            'aigc.task.create': '1',
            'aigc.review.complete': '1',
        },
        signed_workspace_files=frozenset({'runtime.py'}),
    )

    business_calls = []

    async def business_call(capability, _arguments):
        business_calls.append(capability)
        if capability == CATALOG:
            return {'nodes': [], 'available_models': []}
        return {'status': 'ACCEPTED'}

    if setup_fails:
        original_begin = WorkspaceStateTransaction.begin
        begin_calls = 0

        def fail_second_begin(cls, storage_root, **kwargs):
            nonlocal begin_calls
            begin_calls += 1
            if begin_calls == 2:
                raise OSError('continuation state unavailable')
            return original_begin(storage_root, **kwargs)

        monkeypatch.setattr(
            WorkspaceStateTransaction,
            'begin',
            classmethod(fail_second_begin),
        )

    response = await run_workspace_orchestration_turn(
        agent=agent,
        original_messages=[Msg('user', 'review script and continue', 'user')],
        conversation_history=[Msg('assistant', 'existing work', 'assistant')],
        request=SimpleNamespace(
            session_id='session', user_id='user', channel='console',
            channel_meta={},
        ),
        agent_id='expert', workspace_root=root,
        state_storage_root=tmp_path / 'states',
        config=OrchestrationConfig(
            enabled=True,
            entrypoint='runtime.py:create_runtime',
            required_host_capabilities=HOST_CAPABILITIES_V1,
        ),
        authorization=authorization,
        business_call=business_call,
        read_aigc_task=lambda key: task if key == 'material' else None,
        safe_metadata={
            'forceBudgetOnce': budget_exhausted,
            'aigcReviewInput': {
                'binding': binding,
                'asset_id': 'asset',
                'review_assets': task['review_assets'],
                'media_kind': 'text',
                'block_digest': 'sha256:block',
            },
        },
    )

    assert response.error_code is None
    reply = response.message.get('reply') or response.message.get('content')
    assert reply == expected_reply
    assert agent.calls == expected_calls
    assert business_calls.count('aigc.review.complete') == 1


def test_prior_platform_review_attempts_are_removed_from_agent_memory():
    from agentscope.message import Msg
    from qwenpaw.app.workspace.orchestration import (
        _drop_prior_platform_review_attempts,
    )

    marker = '当前绑定的 DClaw AIGC 素材已由客户明确提交。任务ID：material-1。'
    memory = SimpleNamespace(content=[
        (Msg('user', 'ordinary context', 'user'), []),
        (Msg('user', marker, 'user'), []),
        (Msg('assistant', 'stale refusal', 'assistant'), []),
        (Msg('system', 'TASK_UNAVAILABLE', 'system'), []),
        (Msg('user', 'customer correction', 'user'), []),
        (Msg('assistant', 'normal answer', 'assistant'), []),
        (Msg('user', marker, 'user'), []),
        (Msg('assistant', 'another stale refusal', 'assistant'), []),
    ])

    assert _drop_prior_platform_review_attempts(memory) == 5
    assert [item[0].get_text_content() for item in memory.content] == [
        'ordinary context',
        'customer correction',
        'normal answer',
    ]


@pytest.mark.asyncio
async def test_uncertain_creation_returns_identity_for_status_recovery():
    async def fail(*args):
        raise RuntimeError('private-provider-details')
    tools = build_aigc_tools(grants={CATALOG: '1', CREATE: '1'},
        installation_id='i', conversation_id='s', business_call=fail,
        read_task=None, review_input=None, media_delivery={})
    reply = result(await tools['aigc_workflow_create'](
        'campaign', 1, valid_image_workflow(),
    ))
    assert reply['error'] == 'PLATFORM_OPERATION_UNCONFIRMED'
    assert reply['material_task_id'].startswith('material-')
    assert 'private-provider-details' not in str(reply)


@pytest.mark.asyncio
@pytest.mark.skip(reason="legacy Agent review write behavior is retired")
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
@pytest.mark.skip(reason="legacy Agent review write behavior is retired")
async def test_review_tool_accepts_a_trusted_task_from_the_previous_installation():
    binding = {
        'installation_id': 'historical-installation',
        'conversation_id': 'conversation',
        'material_task_id': 'material',
    }
    task = {
        'binding': binding,
        'asset_id': 'asset',
        'status': 'SUBMITTED',
        'review_assets': [],
    }
    review_input = {
        'binding': binding,
        'asset_id': 'asset',
        'review_assets': [],
        'media_kind': 'image',
        'block_digest': 'sha256:block',
    }
    calls = []

    async def call(capability, arguments):
        calls.append((capability, arguments))
        return {'task': {'status': 'REVISION_REQUIRED'}}

    tools = build_aigc_tools(
        grants={
            'aigc.task.create': '1',
            'aigc.review.complete': '1',
        },
        installation_id='active-installation',
        conversation_id='conversation',
        business_call=call,
        read_task=lambda key: task if key == 'material' else None,
        review_input=review_input,
        media_delivery={},
    )

    reply = result(await tools['aigc_task_review'](
        'material',
        'REVISION_REQUIRED',
        '第一张图的手部结构需要修正。',
    ))

    assert 'error' not in reply
    assert calls[0][0] == 'aigc.review.complete'
    assert calls[0][1]['binding']['installation_id'] == 'historical-installation'


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
    assert rejected['error'] == 'IDEMPOTENCY_CONFLICT'
    assert rejected['retryable'] is True
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


def test_all_granted_aigc_tools_include_read_only_legacy_review_schema():
    tools, _ = harness({CATALOG: '1', CREATE: '1', 'aigc.task.create': '1',
                        'aigc.task.resume': '1', 'aigc.review.complete': '1'})
    agent = SimpleNamespace(toolkit=Toolkit())
    with bind_aigc_tools(agent, tools):
        schemas = agent.toolkit.get_json_schemas()
        names = {item['function']['name'] for item in schemas}
        assert 'aigc_task_review' in names
        assert 'aigc_task_status' in names
        assert len(schemas) == 5


def test_review_binding_can_hide_unrelated_base_and_aigc_tools():
    async def read_agent_skill(skill_name: str):
        return skill_name

    async def execute_shell_command(command: str):
        return command

    async def aigc_task_review(
        material_task_id: str,
        decision: str,
        assessment: str,
    ):
        return material_task_id, decision, assessment

    async def aigc_workflow_create(task_key: str):
        return task_key

    toolkit = Toolkit()
    toolkit.register_tool_function(read_agent_skill)
    toolkit.register_tool_function(execute_shell_command)
    agent = SimpleNamespace(toolkit=toolkit)
    original = agent.toolkit

    with bind_aigc_tools(
        agent,
        {
            'aigc_task_review': aigc_task_review,
            'aigc_workflow_create': aigc_workflow_create,
        },
        base_tool_names={'read_agent_skill'},
        added_tool_names={'aigc_task_review'},
    ):
        assert set(agent.toolkit.tools) == {
            'read_agent_skill',
            'aigc_task_review',
        }

    assert agent.toolkit is original
