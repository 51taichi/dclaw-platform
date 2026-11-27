from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.app.integration_delivery.signer_provisioning import (
    IntegrationDeliverySignerError,
    integration_delivery_signer_status,
    main,
    provision_integration_delivery_signer,
)


def test_provision_signer_is_secure_idempotent_and_official(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = tmp_path / "secret"
    sealed = tmp_path / "sealed"

    first = provision_integration_delivery_signer(
        secret_dir=secret,
        sealed_root=sealed,
    )
    private_before = (secret / "integration_delivery_signer.json").read_bytes()
    second = provision_integration_delivery_signer(
        secret_dir=secret,
        sealed_root=sealed,
    )

    assert first.ready and second.ready
    assert first == integration_delivery_signer_status(
        secret_dir=secret,
        sealed_root=sealed,
    )
    assert (secret / "integration_delivery_signer.json").read_bytes() == private_before
    assert (secret / "integration_delivery_signer.json").stat().st_mode & 0o777 == 0o600
    trusted = json.loads((sealed / "trusted_signers.json").read_text())
    official = json.loads(
        (sealed / "official_super_expert_signers.json").read_text(),
    )
    assert trusted["signers"]["integration-delivery"] == official["signers"][
        "integration-delivery"
    ]

    assert main(
        [
            "--check",
            "--secret-dir",
            str(secret),
            "--sealed-root",
            str(sealed),
        ],
    ) == 0
    output = capsys.readouterr().out
    assert '"ready": true' in output
    assert "privateKey" not in output


def test_provision_signer_refuses_conflicting_registry_entry(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "secret"
    sealed = tmp_path / "sealed"
    provision_integration_delivery_signer(
        secret_dir=secret,
        sealed_root=sealed,
    )
    registry = sealed / "official_super_expert_signers.json"
    payload = json.loads(registry.read_text())
    payload["signers"]["integration-delivery"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IntegrationDeliverySignerError, match="conflicts"):
        provision_integration_delivery_signer(
            secret_dir=secret,
            sealed_root=sealed,
        )
