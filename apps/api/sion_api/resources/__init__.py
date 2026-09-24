"""Packaged SION ontology, validation, and map bootstrap resources."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

_RESOURCE_PACKAGE = __package__ or "sion_api.resources"


def resource_path(name: str) -> Path:
    """Return a filesystem path for a packaged resource."""
    return Path(str(resources.files(_RESOURCE_PACKAGE).joinpath(name)))


def ontology_path() -> Path:
    return resource_path("sion-core.yaml")


def shacl_path() -> Path:
    return resource_path("sion-core.shacl.ttl")


def map_inventory_path() -> Path:
    return resource_path("current-map-inventory.json")


def map_export_example_path() -> Path:
    return resource_path("map-export.example.json")
