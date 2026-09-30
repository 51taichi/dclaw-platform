"""Environment-backed settings for the independent config patch process."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConfigPatchSettings:
    data_dir: Path
    token_pepper: str = field(repr=False)
    admin_secret: str = field(repr=False)
    dclaw_service_secret: str = field(repr=False)
    dclaw_allowed_origins: tuple[str, ...]
    omnichannel_service_secret: str = field(repr=False)
    omnichannel_base_url: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().resolve())

    @property
    def database_path(self) -> Path:
        return self.data_dir / "config-patch.sqlite3"

    @classmethod
    def from_env(cls) -> "ConfigPatchSettings":
        names = {
            "data_dir": "CONFIG_PATCH_DATA_DIR",
            "token_pepper": "CONFIG_PATCH_TOKEN_PEPPER",
            "admin_secret": "CONFIG_PATCH_ADMIN_SECRET",
            "dclaw_service_secret": "DCLAW_CONFIG_PATCH_INTERNAL_SECRET",
            "dclaw_allowed_origins": "DCLAW_CONFIG_PATCH_ALLOWED_ORIGINS",
            "omnichannel_service_secret": "OMNICHANNEL_CONFIG_PATCH_INTERNAL_SECRET",
            "omnichannel_base_url": "OMNICHANNEL_CONFIG_PATCH_BASE_URL",
        }
        values = {
            field_name: os.environ.get(env_name, "")
            for field_name, env_name in names.items()
        }
        missing = [
            names[field_name]
            for field_name, value in values.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "missing required config patch settings: " + ", ".join(sorted(missing))
            )
        values["dclaw_allowed_origins"] = tuple(
            item.strip()
            for item in values["dclaw_allowed_origins"].split(",")
            if item.strip()
        )
        return cls(**values)
