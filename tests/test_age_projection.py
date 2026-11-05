"""Apache AGE projection: Cypher text must not be injectable from canonical data."""

from __future__ import annotations

from sion_graphrag.age import GRAPH_NAME, _label, _literal, ensure_graph, projection_cypher
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_label_is_reduced_to_a_plain_identifier():
    assert _label("HAS_PART") == "HAS_PART"
    assert _label("Has-Part`) DETACH") == "Has_Part___DETACH"
    assert _label("sion:Building") == "sion_Building"
    assert _label("1x") == "L_1x"
    assert _label("") == "Unlabeled"


def test_literal_escapes_quotes_backslashes_and_dollar_quotes():
    assert _literal("a'b") == "a\\'b"
    assert _literal("a\\b") == "a\\\\b"
    assert _literal("a$$c") == "a$ $c"
    assert "$$" not in _literal("$$$$")


def _seeded_session() -> Session:
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE entities (id INTEGER PRIMARY KEY, stable_key TEXT, entity_type_id TEXT, name TEXT)"))
        conn.execute(
            text(
                "CREATE TABLE relations (id INTEGER PRIMARY KEY, stable_key TEXT, relation_type_id TEXT, "
                "source_entity_id INTEGER, target_entity_id INTEGER, valid_to TEXT)"
            )
        )
        conn.execute(
            text("INSERT INTO entities VALUES (1, 'e:a', 'Project', :name), (2, 'e:b''x', 'Bad) DETACH', 'b')"),
            {"name": "evil $$) AS (v agtype); DROP TABLE entities; --"},
        )
        conn.execute(
            text(
                "INSERT INTO relations VALUES (1, 'r:1', 'HAS-PART', 1, 2, NULL), "
                "(2, 'r:old', 'HAS_PART', 1, 2, '2026-01-01')"
            )
        )
    return Session(engine)


def _dollar_body(statement: str) -> str:
    # Exactly one $$...$$ block per statement: the generated text cannot close it early.
    assert statement.count("$$") == 2, statement
    return statement.split("$$")[1]


def test_projection_statements_keep_data_inside_the_cypher_block():
    with _seeded_session() as session:
        statements = projection_cypher(session)

    assert len(statements) == 4  # reset + 2 vertices + 1 current edge (invalidated edge skipped)
    bodies = [_dollar_body(s) for s in statements]
    assert "CREATE (:Project {stable_key: 'e:a', name: 'evil $ $) AS (v agtype); DROP TABLE entities; --'})" in bodies[1]
    assert "CREATE (:Bad__DETACH {stable_key: 'e:b\\'x', name: 'b'})" in bodies[2]
    assert "-[:HAS_PART {stable_key: 'r:1'}]->" in bodies[3]
    assert "r:old" not in "".join(statements)


class _RecordingSession:
    def __init__(self, graph_exists: bool):
        self.graph_exists = graph_exists
        self.statements: list[tuple[str, dict | None]] = []

    def execute(self, clause, params=None):
        self.statements.append((str(clause), params))
        exists = self.graph_exists

        class _Result:
            def first(self):
                return (1,) if exists else None

        return _Result()


def test_ensure_graph_creates_the_graph_only_when_missing():
    missing = _RecordingSession(graph_exists=False)
    ensure_graph(missing)
    assert missing.statements[-1] == ("SELECT ag_catalog.create_graph(:name)", {"name": GRAPH_NAME})

    present = _RecordingSession(graph_exists=True)
    ensure_graph(present)
    assert not any("create_graph" in sql for sql, _ in present.statements)
    assert present.statements[0][0] == "CREATE EXTENSION IF NOT EXISTS age"
