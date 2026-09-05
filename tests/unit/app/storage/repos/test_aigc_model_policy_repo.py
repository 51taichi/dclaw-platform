import pytest

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.aigc_model_policy_repo import (
    AigcModelPolicyRepository,
    AigcModelPolicyVersionConflict,
)
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def repo(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "db.sqlite")}),
    )
    create_all(engine)
    try:
        yield AigcModelPolicyRepository(engine)
    finally:
        engine.dispose()


def test_replace_creates_ordered_policy(repo):
    saved = repo.replace(
        "image",
        expected_version=None,
        models=[
            {"provider_id": "mxapi", "model_id": "gpt-image-2"},
            {"provider_id": "volcengine", "model_id": "seedream-5"},
        ],
        default_model={
            "provider_id": "mxapi",
            "model_id": "gpt-image-2",
        },
        updated_by=7,
    )

    assert saved["configured"] is True
    assert saved["version"] == 1
    assert saved["models"][0]["is_default"] is True
    assert repo.get("image")["models"][1]["sort_order"] == 1


def test_replace_rejects_stale_version(repo):
    model = {"provider_id": "p", "model_id": "m"}
    repo.replace("image", None, [model], model, 1)

    with pytest.raises(AigcModelPolicyVersionConflict):
        repo.replace("image", 0, [model], model, 2)


def test_get_returns_none_before_first_save(repo):
    assert repo.get("audio") is None


def test_replace_requires_default_to_be_selected(repo):
    with pytest.raises(ValueError, match="default model must be selected"):
        repo.replace(
            "video",
            None,
            [{"provider_id": "p", "model_id": "selected"}],
            {"provider_id": "p", "model_id": "other"},
            1,
        )
