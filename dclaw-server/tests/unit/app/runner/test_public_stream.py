import asyncio
import pytest
from agentscope.event import TextBlockDeltaEvent
from qwenpaw.agents.message_compat import Msg
from qwenpaw.app.workspace.public_stream import execute_public_agent, public_snapshot


def test_public_snapshot_excludes_internal_blocks_and_json_envelopes():
    msg = Msg('agent', [{'type':'thinking','thinking':'private'}, {'type':'text','text':'Hello'}], 'assistant')
    snap = public_snapshot(msg)
    assert snap.id == msg.id and snap.get_text_content() == 'Hello'
    assert all(b.type == 'text' for b in snap.content)
    assert public_snapshot(Msg('agent', [{'type':'tool_result','id':'x','name':'skill','output':'private'}], 'assistant')) is None
    assert public_snapshot(Msg('agent', '{"reply":', 'assistant')) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('opt_in', [False, True])
async def test_workspace_progress_is_opt_in_and_final_identity_is_retained(tmp_path, opt_in):
    from types import SimpleNamespace
    from qwenpaw.app.workspace.public_stream import stream_workspace_turn
    from qwenpaw.app.workspace.orchestration import AuthorizedWorkspaceRelease
    from qwenpaw.app.workspace.orchestration_contract import HOST_CAPABILITIES_V1, OrchestrationConfig
    root = tmp_path / 'workspace'; root.mkdir()
    (root / 'runtime.py').write_text('''
class Runtime:
 async def handle(self, request, host):
  value = await host.call('agent.execute', {'messages':request.normalized_input['messages'], 'execution_mode':'agent_loop', 'public_stream': OPT_IN})
  await host.call('runtime.complete', {'invocation_id':request.invocation_id,'message':value['message']})
def create_runtime():return Runtime()
'''.replace('OPT_IN', repr(opt_in)))
    class Agent:
        name = 'agent'
        model = None
        async def __call__(self, messages):
            return Msg('agent', 'Hello', 'assistant')
        async def reply_stream(self, messages, yield_final_msg=True):
            msg = Msg('agent', 'Hello', 'assistant')
            yield TextBlockDeltaEvent(
                reply_id=msg.id,
                block_id=msg.content[0].id,
                delta='Hello',
            )
            if yield_final_msg:
                yield msg
    outputs = []
    async for finished, value in stream_workspace_turn(agent=Agent(), original_messages=[Msg('user','hi','user')],
        request=SimpleNamespace(session_id='s',user_id='u',channel='console',channel_meta={}),
        agent_id='generic',workspace_root=root,state_storage_root=tmp_path/'states',
        config=OrchestrationConfig(enabled=True,entrypoint='runtime.py:create_runtime',required_host_capabilities=HOST_CAPABILITIES_V1),
        authorization=AuthorizedWorkspaceRelease(installation_id='i',release_id='r',release_digest='sha256:'+'a'*64,
          granted_capabilities={key:'1' for key in HOST_CAPABILITIES_V1},signed_workspace_files=frozenset({'runtime.py'}))):
        outputs.append((finished, value))
    assert outputs[-1][0] and outputs[-1][1].error_code is None
    assert len(outputs) == (2 if opt_in else 1)
    if opt_in: assert outputs[0][1].id == outputs[-1][1].message['id']


@pytest.mark.asyncio
async def test_real_agent_streams_text_while_excluding_reasoning():
    from agentscope.agent import Agent
    from agentscope.credential import CredentialBase
    from agentscope.formatter import OpenAIChatFormatter
    from agentscope.message import TextBlock, ThinkingBlock
    from agentscope.model import ChatModelBase, ChatResponse
    from pydantic import BaseModel
    release = asyncio.Event()
    class Model(ChatModelBase):
        class Parameters(BaseModel):
            pass
        def __init__(self):
            super().__init__(
                credential=CredentialBase(),
                model='scripted',
                parameters=self.Parameters(),
                stream=True,
            )
            self.formatter = OpenAIChatFormatter()
        async def __call__(self, *args, **kwargs):
            async def stream():
                yield ChatResponse(
                    content=[
                        ThinkingBlock(thinking='internal'),
                        TextBlock(text='Hello'),
                    ],
                    is_last=False,
                )
                await release.wait()
                yield ChatResponse(
                    content=[
                        ThinkingBlock(thinking='internal'),
                        TextBlock(text='Hello world'),
                    ],
                    is_last=True,
                )
            return stream()
    agent = Agent(name='expert', system_prompt='Respond.', model=Model())
    snapshots = []
    async def receive(message):
        snapshots.append(message)
        release.set()
    final = await asyncio.wait_for(execute_public_agent(agent,[Msg('user','hi','user')],receive), 3)
    assert snapshots[0].get_text_content() == 'Hello'
    assert snapshots[-1].get_text_content() == 'Hello world'
    assert all(snapshot.id == final.id for snapshot in snapshots)
    assert all(b.type == 'text' for snapshot in snapshots for b in snapshot.content)
