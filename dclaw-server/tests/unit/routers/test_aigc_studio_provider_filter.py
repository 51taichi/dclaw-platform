# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app.routers.aigc_studio import _provider_configured_for_aigc


def test_disabled_provider_is_not_configured_for_aigc() -> None:
    provider = SimpleNamespace(
        disabled=True,
        require_api_key=False,
        api_key="",
    )

    assert _provider_configured_for_aigc(provider) is False
