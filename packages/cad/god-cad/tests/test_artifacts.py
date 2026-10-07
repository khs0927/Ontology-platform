import json
from pathlib import Path

import jsonschema
from rdflib import RDF, Graph, Namespace

from god_cad.models import Drawing, Patch, PlanReport

ROOT = Path(__file__).resolve().parents[1]


def test_schemas_match_code_and_validate_examples(sample, patch_for):
    for name, contract in [("drawing", Drawing), ("patch", Patch), ("report", PlanReport)]:
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        assert schema == contract.model_json_schema()
        jsonschema.Draft202012Validator.check_schema(schema)
    drawing = sample[1]
    jsonschema.validate(drawing.model_dump(mode="json"), Drawing.model_json_schema())
    jsonschema.validate(patch_for(drawing).model_dump(mode="json"), Patch.model_json_schema())


def test_turtle_is_valid_and_candidate_is_not_asserted_as_wall():
    graph = Graph()
    for path in (ROOT / "ontology").glob("*.ttl"):
        graph.parse(path, format="turtle")
    cad = Namespace("https://github.com/khs0927/GOD-CAD/ns#")
    beo = Namespace("https://w3id.org/beo#")
    candidates = list(graph.subjects(RDF.type, cad.SemanticCandidate))
    assert candidates
    assert all((candidate, RDF.type, beo.Wall) not in graph for candidate in candidates)
    assert all((candidate, cad.proposedClass, beo.Wall) in graph for candidate in candidates)
