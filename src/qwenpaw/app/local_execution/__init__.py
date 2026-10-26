"""Compatibility exports for plugin-owned local execution integration."""

from .session import (
    LOCAL_EXECUTION_SESSION_CAPABILITY,
    LocalExecutionSessionError,
    inject_local_execution_session,
    issue_local_execution_session,
    verify_local_execution_session,
)

__all__ = (
    "LOCAL_EXECUTION_SESSION_CAPABILITY",
    "LocalExecutionSessionError",
    "inject_local_execution_session",
    "issue_local_execution_session",
    "verify_local_execution_session",
)
