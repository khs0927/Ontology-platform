from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    auto_create_schema: bool
    ontology_path: Path
    map_inventory_path: Path
    cors_origins: tuple[str, ...]


def load_settings() -> Settings:
    database_url = os.getenv(
        "SION_DATABASE_URL",
        f"sqlite:///{PROJECT_ROOT / 'runtime' / 'sion.db'}",
    )
    default_auto_create = database_url.startswith("sqlite")
    origins = tuple(
        item.strip()
        for item in os.getenv(
            "SION_CORS_ORIGINS",
            ",".join(
                [
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                ]
            ),
        ).split(",")
        if item.strip()
    )
    return Settings(
        database_url=database_url,
        auto_create_schema=_bool_env("SION_AUTO_CREATE_SCHEMA", default_auto_create),
        ontology_path=PROJECT_ROOT / "ontology" / "core" / "sion-core.yaml",
        map_inventory_path=PROJECT_ROOT
        / "data"
        / "bootstrap"
        / "current-map-inventory.json",
        cors_origins=origins,
    )
