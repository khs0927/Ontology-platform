"""BIM (IFC) parsing and ingestion for Sion. ``ifcopenshell`` is optional (extra ``bim``)."""

from .ifc import build_ifc_export, ifcopenshell_available, ingest_ifc, parse_ifc

__all__ = ["build_ifc_export", "ifcopenshell_available", "ingest_ifc", "parse_ifc"]
