"""Versioned human/machine-neutral operation contract for AIGC Studio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HumanGuideStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]+$")
    title: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    control_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]+$")
    action: Literal["click", "input", "select", "wait", "verify"]
    success_signal: str = Field(min_length=1)
    recovery: str = Field(min_length=1)


class OperationDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]+$")
    version: Literal["1"] = "1"
    title: str = Field(min_length=1)
    arguments_schema: dict[str, Any]
    preconditions: tuple[str, ...]
    expected_result: dict[str, Any]
    human_guide: tuple[HumanGuideStep, ...] = Field(min_length=1)
    machine_executor: None = None

    @model_validator(mode="after")
    def guide_identifiers_are_unique(self) -> "OperationDefinition":
        step_ids = [step.step_id for step in self.human_guide]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("duplicate guide step id")
        control_ids = [step.control_id for step in self.human_guide]
        if len(control_ids) != len(set(control_ids)):
            raise ValueError("duplicate guide control id")
        return self


class OperationCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    operations: tuple[OperationDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def operation_ids_are_unique(self) -> "OperationCatalog":
        identifiers = [operation.operation_id for operation in self.operations]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate operation id")
        return self

    def operation(self, operation_id: str) -> OperationDefinition:
        for operation in self.operations:
            if operation.operation_id == operation_id:
                return operation
        raise KeyError(operation_id)


def load_operation_catalog(path: Path) -> OperationCatalog:
    return OperationCatalog.model_validate_json(
        Path(path).read_text(encoding="utf-8"),
    )


def build_operation_manual(
    catalog: OperationCatalog,
    manual_path: Path,
    machine_catalog_path: Path,
) -> None:
    lines = [
        "# DClaw AIGC 操作说明书",
        "",
        f"契约版本：{catalog.schema_version}",
        "",
    ]
    for operation in catalog.operations:
        lines.extend([
            f"## {operation.title}",
            "",
            f"操作 ID：`{operation.operation_id}`，版本：`{operation.version}`。",
            "",
            "前置条件：",
            "",
        ])
        lines.extend(f"- {item}" for item in operation.preconditions)
        lines.extend(["", "逐步操作：", ""])
        for index, step in enumerate(operation.human_guide, 1):
            lines.extend([
                f"### {index}. {step.title}",
                "",
                step.instruction,
                "",
                f"- 控件：`{step.control_id}`",
                f"- 完成标志：{step.success_signal}",
                f"- 找不到或操作失败：{step.recovery}",
                "",
            ])
    manual_path = Path(manual_path)
    machine_catalog_path = Path(machine_catalog_path)
    manual_path.parent.mkdir(parents=True, exist_ok=True)
    machine_catalog_path.parent.mkdir(parents=True, exist_ok=True)
    manual_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    machine_catalog_path.write_text(
        json.dumps(
            catalog.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
