from qwenpaw.app.workspace.orchestration import WorkspaceTurnResult, workspace_result_to_message

def test_debug_is_a_separate_content_block_without_changing_reply():
    reply='  模型原文\n第二行  '
    result=WorkspaceTurnResult(message={'reply':reply},diagnostics={'display_text':'[调试\n当前阶段：S2\n]'})
    message=workspace_result_to_message(result,agent_name='陆羽')
    assert message.content[0]=={'type':'text','text':reply}
    assert message.content[1]['text']=='\n\n---\n\n[调试\n当前阶段：S2\n]'
    assert result.message['reply']==reply

def test_internal_diagnostics_are_not_displayed():
    result=WorkspaceTurnResult(message={'reply':'原文'},diagnostics={'current_node':'S2'})
    assert workspace_result_to_message(result,agent_name='陆羽').content=='原文'
