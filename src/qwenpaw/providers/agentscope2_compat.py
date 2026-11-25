"""Small compatibility helpers at the DClaw/AgentScope 2 model boundary."""

from __future__ import annotations

from typing import Any

from agentscope.credential import CredentialBase
from agentscope.model import ChatModelBase


def initialize_model_wrapper(
    wrapper: ChatModelBase,
    inner: Any,
    *,
    model: str | None = None,
) -> None:
    """Initialize an AgentScope 2 model wrapper from its inner model."""
    credential = getattr(inner, "credential", None) or CredentialBase()
    parameters = getattr(inner, "parameters", None)
    if parameters is None:
        parameters = ChatModelBase.Parameters()
    current_model = getattr(inner, "model", None)
    legacy_model = getattr(inner, "model_name", None)
    model_id = next(
        (
            candidate
            for candidate in (model, current_model, legacy_model)
            if isinstance(candidate, str) and candidate
        ),
        "unknown",
    )
    ChatModelBase.__init__(
        wrapper,
        credential=credential,
        model=model_id,
        parameters=parameters,
        stream=bool(getattr(inner, "stream", True)),
        context_size=int(getattr(inner, "context_size", 32768)),
    )


class LegacyModelNameMixin:
    """Expose the old identity name without changing AgentScope 2 state."""

    @property
    def model_name(self) -> str:
        return self.model

    @model_name.setter
    def model_name(self, value: str) -> None:
        self.model = value
