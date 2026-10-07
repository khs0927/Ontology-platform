"""Layer names are weak evidence, never confirmed building objects."""

from god_cad.models import Drawing, Edge, Evidence, SemanticObject

LAYER_PRIORS = {
    "WAL1": "https://w3id.org/beo#Wall",
    "WAL2": "https://w3id.org/beo#Wall",
    "WAL3": "https://w3id.org/beo#Wall",
    "DOOR": "https://w3id.org/beo#Door",
    "WIN": "https://w3id.org/beo#Window",
    "COL": "https://w3id.org/beo#Column",
}


def candidates(drawing: Drawing) -> tuple[list[SemanticObject], list[Edge]]:
    objects, edges = [], []
    for entity in drawing.entities:
        class_uri = LAYER_PRIORS.get(entity.layer.upper())
        if class_uri is None:
            continue
        obj = SemanticObject(
            id=entity.id.replace("entity:", "candidate:", 1),
            class_uri=class_uri,
            entity_ids=[entity.id],
            evidence=[Evidence(method="layer_prior_v1", value=entity.layer, score=0.5)],
        )
        objects.append(obj)
        edges.append(
            Edge(
                source=obj.id,
                target=entity.id,
                graph="semantic",
                relation="represented_by",
                evidence="Unconfirmed layer prior; primitive grouping is not implemented",
            )
        )
    return objects, edges
