"""Validated capability and responsibility catalog for caller AIs."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from pydantic import Field, ValidationError, model_validator

from .models import ApiModel


EXPECTED_PROFILES = {"standard-2026.09", "super-expert-2026.09"}
EXPECTED_SEMANTICS = {"stateMachine", "tags", "knowledge"}


class CapabilityCatalogError(RuntimeError):
    pass


class ModuleResponsibility(ApiModel):
    module_id: str
    owner: str
    purpose: str
    use_when: list[str]


class CapabilityProfile(ApiModel):
    profile_id: str
    name: str
    capabilities: list[str]


class ComponentSemantics(ApiModel):
    owner: str
    purpose: str
    change_when: list[str]
    coordinate_with: list[str] = Field(default_factory=list)


class CapabilityRequestContract(ApiModel):
    required_fields: list[str]
    destination: str
    outcome: str


class CapabilityCatalog(ApiModel):
    schema_version: str
    version: str
    modules: list[ModuleResponsibility]
    profiles: dict[str, CapabilityProfile]
    semantics: dict[str, ComponentSemantics]
    capability_request: CapabilityRequestContract

    @model_validator(mode="after")
    def validate_catalog_contract(self) -> "CapabilityCatalog":
        if self.schema_version != "capability-catalog.v1":
            raise ValueError("unsupported capability catalog schema")
        if set(self.profiles) != EXPECTED_PROFILES:
            raise ValueError("capability profile set is invalid")
        if any(key != profile.profile_id for key, profile in self.profiles.items()):
            raise ValueError("capability profile identity mismatch")
        if set(self.semantics) != EXPECTED_SEMANTICS:
            raise ValueError("component semantics set is invalid")
        return self


class CapabilityCatalogService:
    def __init__(self, *, path: Path | None = None) -> None:
        self._path = path
        self._catalog: CapabilityCatalog | None = None

    def load(self) -> CapabilityCatalog:
        try:
            text = (
                self._path.read_text(encoding="utf-8")
                if self._path is not None
                else files("config_patch_service.resources")
                .joinpath("capability-catalog.v1.json")
                .read_text(encoding="utf-8")
            )
            self._catalog = CapabilityCatalog.model_validate_json(text)
        except (OSError, ValidationError, ValueError) as exc:
            raise CapabilityCatalogError("capability catalog is invalid") from exc
        return self._catalog

    def get_profile(self, profile_id: str) -> CapabilityProfile:
        catalog = self._catalog or self.load()
        try:
            return catalog.profiles[profile_id]
        except KeyError as exc:
            raise CapabilityCatalogError(
                f"unknown capability profile: {profile_id}"
            ) from exc
