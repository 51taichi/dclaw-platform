from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.aigc.model_policy import AigcModelPolicyService
from qwenpaw.app.routers.aigc_model_policy import (
    get_policy_repository,
    get_policy_service,
    router,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.aigc_model_policy_repo import (
    AigcModelPolicyRepository,
)
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


class StubManager:
    async def list_provider_info(self):
        model = SimpleNamespace(
            id="gpt-image-2",
            name="GPT Image 2",
            model_type="image",
            aigc_capabilities=["text_to_image"],
            generate_kwargs={},
            billing_eligible=False,
        )
        return [
            SimpleNamespace(
                id="mxapi",
                name="MXAPI",
                models=[model],
                extra_models=[],
                require_api_key=True,
                api_key="secret",
                disabled=False,
                meta={},
            )
        ]


@pytest.fixture
def client(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "db.sqlite")})
    )
    create_all(engine)
    repository = AigcModelPolicyRepository(engine)
    service = AigcModelPolicyService(
        repository,
        published_pairs={("mxapi", "gpt-image-2")},
        priced_pairs=set(),
    )
    app = FastAPI()

    @app.middleware("http")
    async def authenticated_admin(request, call_next):
        request.state.user_id = 7
        request.state.role = "admin"
        return await call_next(request)

    app.include_router(router, prefix="/api/admin")
    app.dependency_overrides[get_policy_repository] = lambda: repository
    app.dependency_overrides[get_policy_service] = lambda: service
    app.state.provider_manager = StubManager()
    try:
        yield TestClient(app)
    finally:
        engine.dispose()


def test_admin_inventory_keeps_unpriced_model_visible_but_disabled(client):
    response = client.get("/api/admin/aigc-model-policy/inventory")

    assert response.status_code == 200
    item = response.json()["categories"]["image"][0]
    assert item["model_id"] == "gpt-image-2"
    assert item["selectable"] is False
    assert item["reasons"] == ["unpriced"]


def test_save_rejects_default_outside_selected_models(client):
    response = client.put(
        "/api/admin/aigc-model-policy/image",
        json={
            "version": None,
            "models": [{"provider_id": "p", "model_id": "a"}],
            "default_model": {"provider_id": "p", "model_id": "b"},
        },
    )

    assert response.status_code == 422


def test_save_rejects_disabled_new_candidate_with_structured_reason(client):
    response = client.put(
        "/api/admin/aigc-model-policy/image",
        json={
            "version": None,
            "models": [{"provider_id": "mxapi", "model_id": "gpt-image-2"}],
            "default_model": {
                "provider_id": "mxapi",
                "model_id": "gpt-image-2",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reasons"] == ["unpriced"]
