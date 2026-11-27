from __future__ import annotations

import json

from alibabacloud_dysmsapi20170525 import models as sms_models

from qwenpaw.app.notifications.sms import (
    AliyunSmsSender,
    AliyunSmsSettings,
    DisabledSmsSender,
    SmsAlert,
    get_sms_sender,
)


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.request = None
        self.runtime = None

    def send_sms_with_options(self, request, runtime):
        self.request = request
        self.runtime = runtime
        if self.error is not None:
            raise self.error
        return self.response


def settings():
    return AliyunSmsSettings(
        access_key_id="test-ak",
        access_key_secret="test-secret",
        sign_name="湖南星芒物联科技",
        template_code="SMS_512581202",
    )


def alert(phone_number="+8613800138000"):
    return SmsAlert(
        event_id="event-1",
        phone_number=phone_number,
        display_name="Alice",
        tier="warning",
        available=4800,
        threshold=5000,
    )


def test_aliyun_sender_submits_expected_request():
    response = sms_models.SendSmsResponse(
        body=sms_models.SendSmsResponseBody(
            code="OK", message="OK", biz_id="biz-1", request_id="request-1",
        ),
    )
    client = FakeClient(response=response)

    result = AliyunSmsSender(settings(), client=client).send(alert())

    assert result.status == "submitted"
    assert result.provider_message_id == "biz-1"
    assert result.attempted is True
    assert client.request.phone_numbers == "13800138000"
    assert client.request.sign_name == "湖南星芒物联科技"
    assert client.request.template_code == "SMS_512581202"
    assert client.request.out_id == "event-1"
    assert json.loads(client.request.template_param) == {
        "balance": "4800",
        "threshold": "5000",
    }
    assert client.runtime.autoretry is False
    assert client.runtime.max_attempts == 1


def test_aliyun_sender_records_provider_rejection():
    response = sms_models.SendSmsResponse(
        body=sms_models.SendSmsResponseBody(
            code="isv.SMS_SIGNATURE_ILLEGAL",
            message="signature rejected",
            request_id="request-2",
        ),
    )

    result = AliyunSmsSender(
        settings(), client=FakeClient(response=response),
    ).send(alert())

    assert result.status == "failed"
    assert result.attempted is True
    assert result.provider_message_id is None
    assert result.provider_error == (
        "isv.SMS_SIGNATURE_ILLEGAL: signature rejected "
        "(request_id=request-2)"
    )


def test_aliyun_sender_records_sdk_exception():
    class ProviderError(RuntimeError):
        code = "SDK.Timeout"
        message = "request timed out for test-ak and test-secret"

    result = AliyunSmsSender(
        settings(), client=FakeClient(error=ProviderError()),
    ).send(alert())

    assert result.status == "failed"
    assert result.provider_error == (
        "SDK.Timeout: request timed out for [redacted] and [redacted]"
    )
    assert result.attempted is True


def test_aliyun_sender_rejects_non_mainland_number_without_api_call():
    client = FakeClient()

    result = AliyunSmsSender(settings(), client=client).send(alert("+12025550123"))

    assert result.status == "failed"
    assert result.provider_error == "invalid_mainland_phone_number"
    assert result.attempted is False
    assert client.request is None


def test_sms_sender_factory_is_disabled_by_default():
    assert isinstance(get_sms_sender({}), DisabledSmsSender)


def test_sms_sender_factory_reports_incomplete_aliyun_configuration():
    sender = get_sms_sender({"DCLAW_SMS_PROVIDER": "aliyun"})

    result = sender.send(alert())

    assert result.status == "failed"
    assert result.attempted is False
    assert result.provider_error.startswith(
        "ValueError: missing Aliyun SMS configuration",
    )


def test_settings_accept_standard_alibaba_cloud_credentials():
    resolved = AliyunSmsSettings.from_environment({
        "ALIBABA_CLOUD_ACCESS_KEY_ID": "standard-ak",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "standard-secret",
        "DCLAW_ALIYUN_SMS_SIGN_NAME": "sign",
        "DCLAW_ALIYUN_SMS_TEMPLATE_CODE": "template",
    })

    assert resolved.access_key_id == "standard-ak"
    assert resolved.access_key_secret == "standard-secret"
