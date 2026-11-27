# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import pytest

from qwenpaw.app import _app
from qwenpaw.app.billing import recovery as general_recovery
from qwenpaw.app.open_api import runtime


def test_enforced_startup_recovery_failure_is_fail_closed(monkeypatch):
    monkeypatch.setenv("DCLAW_BILLING_MODE", "enforced")
    monkeypatch.setattr(
        runtime,
        "recover_open_api_billing",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    with pytest.raises(RuntimeError, match="billing recovery failed"):
        _app._recover_open_api_billing_at_startup()


@pytest.mark.parametrize("mode", ["shadow", "observe", "off"])
def test_non_enforced_startup_recovery_failure_is_explicitly_degraded(
    monkeypatch,
    mode,
):
    monkeypatch.setenv("DCLAW_BILLING_MODE", mode)
    monkeypatch.setattr(
        runtime,
        "recover_open_api_billing",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    assert _app._recover_open_api_billing_at_startup() == 0


def test_general_billing_recovery_failure_always_blocks_readiness(monkeypatch):
    monkeypatch.setattr(
        general_recovery,
        "recover_general_billing",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    with pytest.raises(RuntimeError, match="General billing recovery failed"):
        _app._recover_general_billing_at_startup()
