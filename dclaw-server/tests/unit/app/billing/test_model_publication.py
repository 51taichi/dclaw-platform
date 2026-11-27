from datetime import datetime, timezone

from qwenpaw.app.billing.model_publication import ModelPublicationService


class Catalogs:
    def effective_catalog(self, _now):
        return {
            "rules": [
                {"provider_id": "dashscope", "model_key": "qwen-plus"},
                {"provider_id": "volcengine-cn", "model_key": "doubao-pro"},
            ]
        }


def test_published_model_allowlist_is_derived_from_effective_catalog():
    service = ModelPublicationService(
        Catalogs(), clock=lambda: datetime(2026, 8, 30, tzinfo=timezone.utc)
    )

    assert service.is_published("dashscope", "qwen-plus") is True
    assert service.is_published("dashscope", "unpriced") is False
    assert service.published_pairs() == {
        ("dashscope", "qwen-plus"),
        ("volcengine-cn", "doubao-pro"),
    }


def test_missing_catalog_fails_closed():
    class Missing:
        def effective_catalog(self, _now):
            raise LookupError("missing")

    service = ModelPublicationService(Missing())

    assert service.published_pairs() == set()
