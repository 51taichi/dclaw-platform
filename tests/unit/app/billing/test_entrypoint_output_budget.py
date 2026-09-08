from types import SimpleNamespace
import pytest
from qwenpaw.app.billing import entrypoint
from qwenpaw.app.billing.context import BillingSource
from qwenpaw.app.sealed_agents import registry

@pytest.mark.parametrize('package_type, expected', [(None, 2048), ('agent', 2048), ('super_expert', 4096)])
def test_console_and_resumed_calls_use_expert_budget(monkeypatch, package_type, expected):
    record = None if package_type is None else SimpleNamespace(enabled=True, active_release=SimpleNamespace(package_type=package_type))
    monkeypatch.setattr(registry, 'get_sealed_agent_registry', lambda: SimpleNamespace(get_agent=lambda _: record))
    meter = entrypoint._meter_for_source(None, BillingSource(type='client', id='chat', expert_id='expert'))
    assert meter.default_max_output_tokens == expected
    assert meter.platform_max_output_tokens == expected
