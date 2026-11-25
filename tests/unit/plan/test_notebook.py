import pytest

from qwenpaw.plan import InMemoryPlanStorage, PlanNotebook, SubTask


@pytest.mark.asyncio
async def test_plan_notebook_round_trip_and_tool_registration():
    notebook = PlanNotebook(storage=InMemoryPlanStorage())
    tool_names = {tool.__name__ for tool in notebook.list_tools()}
    assert "create_plan" in tool_names
    assert "finish_plan" in tool_names

    await notebook.create_plan(
        name="Upgrade",
        description="Upgrade the runtime",
        expected_outcome="All tests pass",
        subtasks=[
            SubTask(
                name="Migrate",
                description="Migrate APIs",
                expected_outcome="No legacy imports",
            ),
        ],
    )
    state = notebook.state_dict()

    restored = PlanNotebook(storage=InMemoryPlanStorage())
    restored.load_state_dict(state)

    assert restored.current_plan is not None
    assert restored.current_plan.name == "Upgrade"
    assert (await restored.get_current_hint()).get_text_content().startswith(
        "<system-hint>",
    )


@pytest.mark.asyncio
async def test_finished_plan_moves_to_history_and_restores():
    notebook = PlanNotebook()
    await notebook.create_plan(
        name="Upgrade",
        description="Upgrade",
        expected_outcome="Done",
        subtasks=[
            SubTask(name="Test", description="Run", expected_outcome="Pass"),
        ],
    )
    plan_id = notebook.current_plan.id
    await notebook.finish_plan("done", "Passed")
    assert notebook.current_plan is None

    await notebook.recover_historical_plan(plan_id)
    assert notebook.current_plan is not None
    assert notebook.current_plan.outcome == "Passed"
