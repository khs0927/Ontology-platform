"""Read-only AEC/CAIR federation with khs0927/Ontology (``aec_intelligence``) over MCP stdio."""

from .adapter import AecCairAdapter, AecCairConfig, AecCairError

__all__ = ["AecCairAdapter", "AecCairConfig", "AecCairError"]
