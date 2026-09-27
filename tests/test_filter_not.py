"""The ``$not`` filter operator: every store excludes what matches the filters under it.

Recall uses it to keep the agents' self-model records out (continuity.hide_self_model).
Stores that build their own query from the filter must not choke on the "$" key: Postgres
turns it into SQL, SQLite and Supabase skip it in the query and let apply_filter apply it.
"""
from urllib.parse import unquote

from logica_mind.continuity.self_model import SELF_MODEL_FILTER, hide_self_model
from logica_mind.embeddings import HashingEmbedder
from logica_mind.stores import InMemoryStore, SQLiteStore
from logica_mind.stores.base import NOT, matches_filter, not_filters
from logica_mind.stores.postgres import PostgresStore
from logica_mind.stores.supabase import SupabaseStore
from logica_mind.types import Memory, MemoryLayer

EMB = HashingEmbedder()


def _mem(id_, content, **metadata):
    return Memory(id=id_, namespace="t", content=content, layer=MemoryLayer.USER,
                  embedding=EMB.embed_one(content), metadata=metadata)


def test_matches_filter_not():
    version = _mem("v", "x", continuity="self-model", kind="version")
    note = _mem("n", "x", session="s1")
    hide = {NOT: SELF_MODEL_FILTER}
    assert not matches_filter(version, hide) and matches_filter(note, hide)
    assert not matches_filter(note, {NOT: [{"session": "s9"}, {"session": "s1"}]})   # any of the list
    assert matches_filter(note, {NOT: {}}) and matches_filter(note, {NOT: None})    # empty excludes nothing
    assert not matches_filter(version, {"kind": "version", NOT: {"continuity": ["self-model", "x"]}})
    assert not_filters([{}, {"a": 1}, None]) == [{"a": 1}]


def test_hide_self_model_keeps_what_the_caller_asked():
    assert hide_self_model(None) == {NOT: [SELF_MODEL_FILTER]}
    assert hide_self_model({"continuity": "self-model"}) == {"continuity": "self-model"}
    both = hide_self_model({"session": "s", NOT: {"kind": "draft"}})
    assert both == {"session": "s", NOT: [{"kind": "draft"}, SELF_MODEL_FILTER]}


def _search_excludes(store):
    store.add([_mem("v1", "copy de alta conversão", continuity="self-model", kind="version"),
               _mem("n1", "copy de alta conversão com prova social", session="s1")])
    q = "copy de alta conversão"
    ids = {r.memory.id for r in store.search("t", EMB.embed_query(q), q, None, 10, hide_self_model())}
    assert ids == {"n1"}
    ids = {r.memory.id for r in store.search("t", EMB.embed_query(q), q, None, 10,
                                             {"session": "s1", NOT: SELF_MODEL_FILTER})}
    assert ids == {"n1"}


def test_in_memory_store():
    _search_excludes(InMemoryStore())


def test_sqlite_store_skips_the_operator_in_sql():
    _search_excludes(SQLiteStore(":memory:"))


def test_postgres_where_meta():
    params = []
    sql = PostgresStore._where_meta({"ownerId": "u1", NOT: [SELF_MODEL_FILTER]}, params)
    assert sql == (" AND metadata @> %s::jsonb"
                   " AND NOT COALESCE((TRUE AND metadata @> %s::jsonb), FALSE)")
    assert params == ['{"ownerId": "u1"}', '{"continuity": "self-model"}']
    params = []   # an empty list under $not excludes nothing
    sql = PostgresStore._where_meta({NOT: {"continuity": []}}, params)
    assert sql == " AND NOT COALESCE((TRUE AND FALSE), FALSE)" and params == []


class _FakeSupabase(SupabaseStore):
    def __init__(self, responder, **kw):
        super().__init__(url="http://fake", key="k", **kw)
        self.calls = []
        self._responder = responder

    def _request(self, method, path, body=None, extra_headers=None):
        self.calls.append((method, path, body))
        return self._responder(method, path, body)


def _row(id_, **metadata):
    return {"id": id_, "namespace": "t", "content": "copy", "layer": "user",
            "metadata": metadata, "similarity": 0.9}


def test_supabase_query_skips_the_operator():
    s = _FakeSupabase(lambda *a: [_row("v1", continuity="self-model"), _row("n1", session="s1")])
    hits = s.search("t", None, "copy", None, 10, {"session": "s1", NOT: SELF_MODEL_FILTER})
    path = unquote(s.calls[-1][1])
    assert "metadata->>session=eq.s1" in path and "$not" not in path
    assert [h.memory.id for h in hits] == ["n1"]


def test_supabase_rpc_gets_scalars_and_the_rows_are_filtered():
    s = _FakeSupabase(lambda *a: [_row("v1", continuity="self-model"), _row("n1")], use_rpc=True)
    hits = s.search("t", [0.1] * 8, "copy", None, 10, hide_self_model({"ownerId": "u1"}))
    body = s.calls[-1][2]
    assert body["p_metadata_filter"] == {"ownerId": "u1"}
    assert [h.memory.id for h in hits] == []   # n1 has no ownerId, v1 is the self-model
    s = _FakeSupabase(lambda *a: [_row("v1", continuity="self-model"), _row("n1")], use_rpc=True)
    assert [h.memory.id for h in s.search("t", [0.1] * 8, "copy", None, 10, hide_self_model())] == ["n1"]
    assert s.calls[-1][2]["p_metadata_filter"] is None
