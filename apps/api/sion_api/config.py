from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .resources import map_inventory_path, ontology_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_resource(env_name: str, packaged_path: Path, checkout_path: Path) -> Path:
    override = os.getenv(env_name)
    if override:
        return Path(override).expanduser()
    if packaged_path.is_file():
        return packaged_path
    return checkout_path


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
    api_host: str = "127.0.0.1"
    local_api_token: str | None = None
    environment: str = "development"


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
                    "https://sion-ontology-map.changebytwoman.chatgpt.site",
                ]
            ),
        ).split(",")
        if item.strip()
    )
    return Settings(
        database_url=database_url,
        auto_create_schema=_bool_env("SION_AUTO_CREATE_SCHEMA", default_auto_create),
        ontology_path=_resolve_resource(
            "SION_ONTOLOGY_PATH",
            ontology_path(),
            PROJECT_ROOT / "ontology" / "core" / "sion-core.yaml",
        ),
        map_inventory_path=_resolve_resource(
            "SION_MAP_INVENTORY_PATH",
            map_inventory_path(),
            PROJECT_ROOT / "data" / "bootstrap" / "current-map-inventory.json",
        ),
        cors_origins=origins,
        api_host=os.getenv("SION_API_HOST", os.getenv("SION_BIND_HOST", "127.0.0.1")),
        local_api_token=os.getenv("SION_LOCAL_API_TOKEN") or None,
        environment=os.getenv("SION_ENV", "development").strip().lower(),
    )
