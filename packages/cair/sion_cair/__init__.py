"""AEC/CAIR bridge with khs0927/Ontology (``aec_intelligence``).

* :mod:`sion_cair.adapter` - read-only federation over MCP stdio.
* :mod:`sion_cair.ingest` - DXF/IFC ingestion through Ontology's CLI, mapped into the Sion graph as
  unverified claims with evidence (contract ``aec-cair-snapshot/1``).
"""

from .adapter import AecCairAdapter, AecCairConfig, AecCairError

__all__ = ["AecCairAdapter", "AecCairConfig", "AecCairError"]
