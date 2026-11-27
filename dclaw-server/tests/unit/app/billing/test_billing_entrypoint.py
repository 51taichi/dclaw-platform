# -*- coding: utf-8 -*-
from __future__ import annotations

from unittest.mock import Mock

from qwenpaw.app.billing.entrypoint import PreparedBillingExecution
from qwenpaw.app.storage.repos.billing_execution_repo import (
    BillingExecutionFence,
)


def test_prepared_billing_execution_renews_owned_lease():
    repository = Mock()
    repository.renew.return_value = True
    session = Mock(execution_id="execution-1")
    fence = BillingExecutionFence(owner_token="owner-1", generation=1)
    prepared = PreparedBillingExecution(
        session=session,
        fence=fence,
        execution_repository=repository,
        meter=Mock(),
        usage_service=Mock(),
    )

    assert prepared.renew(lease_seconds=600)
    repository.renew.assert_called_once_with(
        "execution-1",
        fence,
        lease_seconds=600,
    )
