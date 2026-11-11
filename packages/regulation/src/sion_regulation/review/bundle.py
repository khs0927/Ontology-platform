"""Reviewed data bundle: the file a data operator ships to a running workflow.

Holds catalog versions and provisions, designation links, the checklist profile, rules and
conditions as plain JSON. Loading validates everything; a broken bundle fails at start-up rather
than silently narrowing a review. With no bundle the catalog is empty and every checklist row
reports an open gap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sion_regulation.review.applicability import ReviewedRelation
from sion_regulation.review.candidates import ChecklistProfile, DesignationLink
from sion_regulation.review.legal import LegalCatalog
from sion_regulation.review.model import Evidence, LegalVersion, Provision
from sion_regulation.review.rase import RaseRule


class ReviewBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versions: list[LegalVersion] = Field(default_factory=list)
    provisions: list[Provision] = Field(default_factory=list)
    links: list[DesignationLink] = Field(default_factory=list)
    profile: ChecklistProfile | None = None
    rules: list[RaseRule] = Field(default_factory=list)
    conditions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    exception_facts: dict[str, str] = Field(default_factory=dict)
    positions: dict[str, Any] = Field(default_factory=dict)
    reviewed_relations: list[ReviewedRelation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    def catalog(self) -> LegalCatalog:
        catalog = LegalCatalog()
        for version in self.versions:
            catalog.add_version(version)
        for provision in self.provisions:
            catalog.add_provision(provision)
        return catalog


def load_bundle(path: Path) -> ReviewBundle:
    return ReviewBundle.model_validate(json.loads(path.read_text(encoding="utf-8")))
