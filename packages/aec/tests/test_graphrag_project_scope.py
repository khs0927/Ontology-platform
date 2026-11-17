"""Project search filters fail closed; they are not an authorization boundary."""

from contextlib import contextmanager
from types import SimpleNamespace

from aec_intelligence.operational.graphrag.ask import GraphRAG


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, *, project_alias=None, semantic_aliases=()):
        self.project_alias = project_alias
        self.semantic_aliases = semantic_aliases
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if "SELECT n.id, n.project_key AS key" in query:
            return Rows([{"id": "kg:p:a", "key": "a", "name": "Alpha"}])
        if "project_name" in query:
            return Rows([{"project_key": self.project_alias}] if self.project_alias else [])
        if "a.alias_type='project_id'" in query:
            return Rows([{"alias": value} for value in self.semantic_aliases])
        if "room_name" in query:
            return Rows([])
        raise AssertionError(f"unexpected query: {query}")


class Database:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def connect(self):
        yield self.conn


class Search:
    def __init__(self):
        self.calls = []

    def search(self, question, **kwargs):
        self.calls.append(kwargs["project_id"])
        return SimpleNamespace(warnings=[], hits=[])


def test_unknown_or_empty_explicit_project_refuses_before_global_retrieval():
    for project in ("missing", "", "   "):
        conn = Connection()
        search = Search()
        result = GraphRAG(Database(conn), search_router=search).retrieve("도면을 찾아줘", project=project)
        assert result["route"] == "refuse" and result["items"] == []
        assert not search.calls
        assert not any("room_name" in sql for sql, _ in conn.queries)


def test_project_key_and_alias_resolve_without_global_room_lookup():
    for project, alias in (("a", None), ("P-A", "a")):
        conn = Connection(project_alias=alias)
        linked = GraphRAG(Database(conn)).link(conn, "회의실", project)
        assert [p["key"] for p in linked.projects] == ["a"]
        assert any("room_name" in sql and "project_key = ANY" in sql for sql, _ in conn.queries)


def test_semantic_missing_or_empty_alias_never_falls_back_to_global():
    for keys, aliases in ((["a"], ()), (["a"], ("", None, "   ")), ([], ())):
        search = Search()
        rag = GraphRAG(None, search_router=search)
        assert rag._semantic(Connection(semantic_aliases=aliases), "도면", keys) == []
        assert search.calls == []


def test_semantic_known_alias_is_scoped_and_no_project_remains_global():
    search = Search()
    rag = GraphRAG(None, search_router=search)
    rag._semantic(Connection(semantic_aliases=("P-A",)), "도면", ["a"])
    rag._semantic(Connection(), "도면", None)
    assert search.calls == ["P-A", None]


def test_partial_multi_project_aliases_do_not_widen():
    search = Search()
    rag = GraphRAG(None, search_router=search)
    rag._semantic(Connection(semantic_aliases=("P-A",)), "도면", ["a", "b"])
    assert search.calls == ["P-A"]  # Missing aliases reduce recall, not the scope.
