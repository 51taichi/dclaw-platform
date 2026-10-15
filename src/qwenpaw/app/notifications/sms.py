from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from alibabacloud_dysmsapi20170525 import models as sms_models
from alibabacloud_dysmsapi20170525.client import Client as AliyunSmsClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as tea_util_models

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "dysmsapi.aliyuncs.com"
_DEFAULT_CONNECT_TIMEOUT_MS = 3000
_DEFAULT_READ_TIMEOUT_MS = 5000
_MAX_PROVIDER_ERROR_LENGTH = 2000


@dataclass(frozen=True)
class SmsAlert:
    event_id: str
    phone_number: str
    display_name: str | None
    tier: str
    available: int
    threshold: int


@dataclass(frozen=True)
class SmsSubmissionResult:
    status: str
    provider_message_id: str | None = None
    provider_error: str | None = None
    attempted: bool = False


class SmsSender(Protocol):
    def send(self, alert: SmsAlert) -> SmsSubmissionResult:
        ...


class DisabledSmsSender:
    def send(self, alert: SmsAlert) -> SmsSubmissionResult:
        del alert
        return SmsSubmissionResult(status="skipped_unconfigured")


@dataclass(frozen=True)
class AliyunSmsSettings:
    access_key_id: str
    access_key_secret: str
    sign_name: str
    template_code: str
    endpoint: str = _DEFAULT_ENDPOINT
    connect_timeout_ms: int = _DEFAULT_CONNECT_TIMEOUT_MS
    read_timeout_ms: int = _DEFAULT_READ_TIMEOUT_MS

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None,
    ) -> AliyunSmsSettings:
        env = os.environ if environ is None else environ
        values = {
            "access_key_id": _first_nonempty(
                env,
                "DCLAW_ALIYUN_SMS_ACCESS_KEY_ID",
                "ALIBABA_CLOUD_ACCESS_KEY_ID",
            ),
            "access_key_secret": _first_nonempty(
                env,
                "DCLAW_ALIYUN_SMS_ACCESS_KEY_SECRET",
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
            ),
            "sign_name": _clean(env.get("DCLAW_ALIYUN_SMS_SIGN_NAME")),
            "template_code": _clean(env.get("DCLAW_ALIYUN_SMS_TEMPLATE_CODE")),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(
                "missing Aliyun SMS configuration: " + ", ".join(missing),
            )
        return cls(
            **values,
            endpoint=_clean(env.get("DCLAW_ALIYUN_SMS_ENDPOINT"))
            or _DEFAULT_ENDPOINT,
            connect_timeout_ms=_positive_int(
                env.get("DCLAW_ALIYUN_SMS_CONNECT_TIMEOUT_MS"),
                _DEFAULT_CONNECT_TIMEOUT_MS,
                "DCLAW_ALIYUN_SMS_CONNECT_TIMEOUT_MS",
            ),
            read_timeout_ms=_positive_int(
                env.get("DCLAW_ALIYUN_SMS_READ_TIMEOUT_MS"),
                _DEFAULT_READ_TIMEOUT_MS,
                "DCLAW_ALIYUN_SMS_READ_TIMEOUT_MS",
            ),
        )


class AliyunSmsSender:
    def __init__(
        self,
        settings: AliyunSmsSettings,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or AliyunSmsClient(open_api_models.Config(
            access_key_id=settings.access_key_id,
            access_key_secret=settings.access_key_secret,
            endpoint=settings.endpoint,
            connect_timeout=settings.connect_timeout_ms,
            read_timeout=settings.read_timeout_ms,
        ))

    def send(self, alert: SmsAlert) -> SmsSubmissionResult:
        phone_number = _mainland_phone_number(alert.phone_number)
        if phone_number is None:
            return SmsSubmissionResult(
                status="failed",
                provider_error="invalid_mainland_phone_number",
            )
        request = sms_models.SendSmsRequest(
            out_id=alert.event_id,
            phone_numbers=phone_number,
            sign_name=self.settings.sign_name,
            template_code=self.settings.template_code,
            template_param=json.dumps(
                {
                    "balance": str(alert.available),
                    "threshold": str(alert.threshold),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        runtime = tea_util_models.RuntimeOptions(
            autoretry=False,
            max_attempts=1,
            connect_timeout=self.settings.connect_timeout_ms,
            read_timeout=self.settings.read_timeout_ms,
        )
        try:
            response = self.client.send_sms_with_options(request, runtime)
            body = response.body
        except Exception as exc:  # noqa: BLE001 - provider failures are data
            return SmsSubmissionResult(
                status="failed",
                provider_error=_exception_detail(
                    exc,
                    secrets=(
                        self.settings.access_key_id,
                        self.settings.access_key_secret,
                    ),
                ),
                attempted=True,
            )
        if body is not None and body.code == "OK" and body.biz_id:
            return SmsSubmissionResult(
                status="submitted",
                provider_message_id=str(body.biz_id),
                attempted=True,
            )
        return SmsSubmissionResult(
            status="failed",
            provider_error=_response_error(body),
            attempted=True,
        )


class _ConfigurationErrorSmsSender:
    def __init__(self, error: str) -> None:
        self.error = error

    def send(self, alert: SmsAlert) -> SmsSubmissionResult:
        del alert
        return SmsSubmissionResult(status="failed", provider_error=self.error)


def get_sms_sender(
    environ: Mapping[str, str] | None = None,
) -> SmsSender:
    env = os.environ if environ is None else environ
    provider = _clean(env.get("DCLAW_SMS_PROVIDER")).lower()
    if provider in ("", "disabled", "none", "off"):
        return DisabledSmsSender()
    if provider != "aliyun":
        return _ConfigurationErrorSmsSender(
            f"unsupported_sms_provider:{provider}"[:_MAX_PROVIDER_ERROR_LENGTH],
        )
    try:
        return AliyunSmsSender(AliyunSmsSettings.from_environment(env))
    except Exception as exc:  # noqa: BLE001 - configuration cannot abort billing
        detail = _exception_detail(exc)
        logger.error(
            "Aliyun SMS sender configuration failed (error_type=%s)",
            type(exc).__name__,
        )
        return _ConfigurationErrorSmsSender(detail)


def _first_nonempty(environ: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = _clean(environ.get(name))
        if value:
            return value
    return ""


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _positive_int(raw: str | None, default: int, name: str) -> int:
    if not _clean(raw):
        return default
    value = int(str(raw))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _mainland_phone_number(phone_number: str) -> str | None:
    compact = "".join(
        character for character in phone_number
        if character not in " -()"
    )
    if compact.startswith("+86"):
        compact = compact[3:]
    elif compact.startswith("86") and len(compact) == 13:
        compact = compact[2:]
    if len(compact) != 11 or not compact.isdigit() or not compact.startswith("1"):
        return None
    return compact


def _exception_detail(
    exc: Exception, *, secrets: tuple[str, ...] = (),
) -> str:
    code = _clean(getattr(exc, "code", None))
    message = _clean(getattr(exc, "message", None)) or _clean(str(exc))
    if code:
        detail = f"{code}: {message}" if message else code
    else:
        detail = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, "[redacted]")
    return detail[:_MAX_PROVIDER_ERROR_LENGTH]


def _response_error(body: Any | None) -> str:
    if body is None:
        return "empty_response_body"
    code = _clean(getattr(body, "code", None)) or "unknown_code"
    message = _clean(getattr(body, "message", None)) or "no_message"
    request_id = _clean(getattr(body, "request_id", None))
    detail = f"{code}: {message}"
    if request_id:
        detail += f" (request_id={request_id})"
    return detail[:_MAX_PROVIDER_ERROR_LENGTH]
