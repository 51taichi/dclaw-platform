"""Persistence for administrator-managed AIGC model policies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine

from ..schema import aigc_model_policies, aigc_model_policy_items


class AigcModelPolicyVersionConflict(RuntimeError):
    """The policy changed after the caller loaded it."""


def _key(model: Mapping[str, Any]) -> tuple[str, str]:
    return str(model["provider_id"]), str(model["model_id"])


class AigcModelPolicyRepository:
    """Store one ordered, versioned model policy per AIGC category."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(self, category: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            return self._get(connection, category)

    def replace(
        self,
        category: str,
        expected_version: int | None,
        models: Sequence[Mapping[str, Any]],
        default_model: Mapping[str, str],
        updated_by: int | None,
    ) -> dict[str, Any]:
        model_keys = [_key(model) for model in models]
        if len(model_keys) != len(set(model_keys)):
            raise ValueError("selected models must be unique")
        default_key = _key(default_model)
        if default_key not in model_keys:
            raise ValueError("default model must be selected")

        with self.engine.begin() as connection:
            current = self._get(connection, category, for_update=True)
            current_version = current["version"] if current else None
            if current_version != expected_version:
                raise AigcModelPolicyVersionConflict(
                    f"expected version {expected_version}, got {current_version}"
                )

            if current is None:
                result = connection.execute(
                    insert(aigc_model_policies).values(
                        category=category,
                        configured=True,
                        version=1,
                        updated_by=updated_by,
                    )
                )
                policy_id = int(result.inserted_primary_key[0])
            else:
                policy_id = int(current["id"])
                connection.execute(
                    update(aigc_model_policies)
                    .where(aigc_model_policies.c.id == policy_id)
                    .values(
                        configured=True,
                        version=int(current_version) + 1,
                        updated_by=updated_by,
                    )
                )
                connection.execute(
                    delete(aigc_model_policy_items).where(
                        aigc_model_policy_items.c.policy_id == policy_id
                    )
                )

            if model_keys:
                connection.execute(
                    insert(aigc_model_policy_items),
                    [
                        {
                            "policy_id": policy_id,
                            "provider_id": provider_id,
                            "model_id": model_id,
                            "sort_order": index,
                            "is_default": (provider_id, model_id) == default_key,
                        }
                        for index, (provider_id, model_id) in enumerate(model_keys)
                    ],
                )
            saved = self._get(connection, category)
            assert saved is not None
            return saved

    @staticmethod
    def _get(
        connection: Connection,
        category: str,
        *,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        statement = select(aigc_model_policies).where(
            aigc_model_policies.c.category == category
        )
        if for_update:
            statement = statement.with_for_update()
        policy = connection.execute(statement).mappings().one_or_none()
        if policy is None:
            return None
        items = connection.execute(
            select(aigc_model_policy_items)
            .where(aigc_model_policy_items.c.policy_id == policy["id"])
            .order_by(aigc_model_policy_items.c.sort_order.asc())
        ).mappings()
        return {
            **dict(policy),
            "models": [dict(item) for item in items],
        }
