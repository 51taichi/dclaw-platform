"""DClaw runtime error taxonomy with stable HTTP and business codes."""

from __future__ import annotations

from typing import Any


class AppBaseException(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        return f"[{self.status}] {self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class BusinessLogicException(AppBaseException):
    def __init__(self, code: str, message: str, details=None):
        super().__init__(422, code, message, details)


class InternalServerErrorException(AppBaseException):
    def __init__(self, code: str, message: str, details=None):
        super().__init__(500, code, message, details)


class TooManyRequestsException(AppBaseException):
    def __init__(self, code: str, message: str, details=None):
        super().__init__(429, code, message, details)


class AgentException(BusinessLogicException):
    def __init__(self, message: str, details=None):
        super().__init__("AGENT_ERROR", message, details)


class AgentRuntimeErrorException(BusinessLogicException):
    pass


class ExternalServiceException(InternalServerErrorException):
    def __init__(self, service_name: str, message: str, details=None):
        super().__init__(
            "EXTERNAL_SERVICE_ERROR",
            f"External service {service_name} error: {message}",
            details,
        )


class ConfigurationException(InternalServerErrorException):
    def __init__(self, config_key: str, message: str | None = None, details=None):
        super().__init__(
            "CONFIGURATION_ERROR",
            message or f"Configuration error: {config_key}",
            details,
        )


class RateLimitExceededException(TooManyRequestsException):
    def __init__(self, operation: str, retry_after: int = 60, details=None):
        super().__init__(
            "RATE_LIMIT_EXCEEDED",
            f"Operation {operation} is too frequent, please retry after {retry_after} seconds",
            details,
        )


class ModelExecutionException(AgentRuntimeErrorException):
    def __init__(self, model_name: str, details=None):
        super().__init__(
            "MODEL_EXECUTION_FAILED",
            f"Error occurred during execution of model: {model_name}",
            details,
        )


class ModelTimeoutException(AgentRuntimeErrorException):
    def __init__(self, model_name: str, timeout: int, details=None):
        super().__init__(
            "MODEL_TIMEOUT",
            f"Model inference timed out: {model_name}, timeout limit: {timeout} seconds",
            details,
        )


class ModelNotFoundException(AgentRuntimeErrorException):
    def __init__(self, model_name: str, details=None):
        super().__init__("MODEL_NOT_FOUND", f"Model not found: {model_name}", details)


class UnauthorizedModelAccessException(AgentRuntimeErrorException):
    def __init__(self, model_name: str, details=None):
        super().__init__(
            "MODEL_UNAUTHORIZED_ACCESS",
            f"Unauthorized access to model: {model_name}",
            details,
        )


class UnknownAgentException(AgentRuntimeErrorException):
    def __init__(self, original_exception: Exception | None = None, details=None):
        suffix = (
            f": {type(original_exception).__name__}: {original_exception}"
            if original_exception is not None
            else ""
        )
        super().__init__("AGENT_UNKNOWN_ERROR", "Unknown agent error" + suffix, details)


class ModelQuotaExceededException(AgentRuntimeErrorException):
    def __init__(self, model_name: str, details=None):
        super().__init__(
            "MODEL_QUOTA_EXCEEDED", f"Model quota exceeded: {model_name}", details
        )


class ModelContextLengthExceededException(AgentRuntimeErrorException):
    def __init__(self, model_name: str, details=None):
        super().__init__(
            "MODEL_CONTEXT_LENGTH_EXCEEDED",
            f"Model context length exceeded: {model_name}",
            details,
        )
