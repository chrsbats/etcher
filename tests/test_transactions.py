import sqlite3

import pytest

from etcher import DB, WatchError, list_db
from etcher.sqlitedis import Redis as SQLite


@pytest.fixture(scope="module", params=["sqlite", "redislite"])
def backend(request, tmp_path_factory):
    if request.param == "sqlite":
        redis = SQLite(":memory:")
    else:
        redislite = pytest.importorskip("redislite")
        path = tmp_path_factory.mktemp("transactions") / "redis.rdb"
        redis = redislite.Redis(str(path))
    yield redis
    redis.shutdown()


@pytest.fixture
def db(backend):
    keys = backend.keys()
    if keys:
        backend.delete(*keys)
    return DB(redis=backend, prefix="tx")


def graph_nodes(db):
    return [db["state"], db["state"]["items"],
            db["state"]["items"][0]]


def test_aborted_callback_preserves_entire_graph(db):
    db["state"] = {"items": [{"value": "old"}]}
    before = list_db(db)
    tx = db.transactor()

    def update():
        tx.multi()
        tx["state"] = {"items": [{"value": "new"}]}
        raise RuntimeError("abort transaction")

    with pytest.raises(RuntimeError, match="abort transaction"):
        tx.transact(update)

    assert db["state"]() == {"items": [{"value": "old"}]}
    assert list_db(db) == before


def test_replacement_is_private_until_commit_and_collects_old_graph(db):
    db["state"] = {"items": [{"value": "old"}]}
    old_nodes = graph_nodes(db)
    before = list_db(db)
    tx = db.transactor()
    tx.watch()
    tx.multi()
    try:
        tx["state"] = {"items": [{"value": "new"}]}
        assert list_db(db) == before
        tx.execute()
    finally:
        tx.pipe.reset()

    assert db["state"]() == {"items": [{"value": "new"}]}
    for node in old_nodes:
        assert not db.rdb.exists(node.uid)
        assert not db.rdb.exists("back:" + node.uid)
    new_nodes = graph_nodes(db)
    for parent, child in zip([db.data] + new_nodes, new_nodes):
        assert db.get_via_uid(child.uid).backrefs == {parent.uid: 1}


@pytest.mark.parametrize("commit", [False, True])
def test_nested_mutations_and_list_rewrites(db, commit):
    db["state"] = {"items": [{"value": "old"}]}
    before = list_db(db)
    tx = db.transactor()
    tx.watch()
    items = tx["state"]["items"]
    item = items[0]
    tx.multi()
    try:
        item["value"] = "new"
        items.append({"value": "extra"})
        items.reverse()
        expected = {"items": [{"value": "extra"}, {"value": "new"}]}
        assert list_db(db) == before
        if commit:
            tx.execute()
    finally:
        tx.pipe.reset()

    if commit:
        assert db["state"]() == expected
    else:
        assert list_db(db) == before


def test_shared_references_survive_replacement_then_are_collected(db):
    db["state"] = {"items": [{"value": "old"}]}
    child = db["state"]["items"][0]
    db["shared"] = child
    old_nodes = graph_nodes(db)
    before = list_db(db)
    tx = db.transactor()

    def replace():
        shared = tx["shared"]
        tx.multi()
        tx["state"] = {"items": [shared, shared]}
        del tx["shared"]
        assert list_db(db) == before

    tx.transact(replace)
    snapshot = db["state"]()
    assert snapshot["items"][0] is snapshot["items"][1]
    assert snapshot["items"][0] == {"value": "old"}
    assert not db.rdb.exists(old_nodes[0].uid)
    assert not db.rdb.exists(old_nodes[1].uid)
    assert child.backrefs == {db["state"]["items"].uid: 2}

    def remove():
        tx.multi()
        del tx["state"]

    tx.transact(remove)
    assert not db.rdb.exists(child.uid)
    assert not db.rdb.exists("back:" + child.uid)


@pytest.mark.parametrize("commit", [False, True])
def test_cyclic_graph_cleanup_is_transactional(db, commit):
    db["a"] = {"name": "a"}
    db["b"] = {"a": db["a"]}
    db["a"]["b"] = db["b"]
    nodes = [db["a"], db["b"]]
    before = list_db(db)
    tx = db.transactor()
    tx.watch()
    tx.multi()
    try:
        del tx["a"]
        del tx["b"]
        assert list_db(db) == before
        if commit:
            tx.execute()
    finally:
        tx.pipe.reset()

    if commit:
        assert db() == {}
        for node in nodes:
            assert not db.rdb.exists(node.uid)
            assert not db.rdb.exists("back:" + node.uid)
    else:
        assert list_db(db) == before


def test_failed_final_root_write_preserves_previous_snapshot(db):
    class FailingPipeline:
        def __init__(self, pipeline):
            self.pipeline = pipeline

        def __getattr__(self, name):
            return getattr(self.pipeline, name)

        def hset(self, key, *args, **kwargs):
            if key in ("tx:data:", b"tx:data:"):
                raise RuntimeError("injected final root write failure")
            return self.pipeline.hset(key, *args, **kwargs)

    class FailingBackend:
        def __getattr__(self, name):
            return getattr(db.rdb, name)

        def pipeline(self):
            return FailingPipeline(db.rdb.pipeline())

    db["state"] = {"items": [{"value": "old"}]}
    before = list_db(db)
    tx = DB(redis=FailingBackend(), prefix="tx").transactor()

    def replace():
        tx.multi()
        tx["state"] = {"items": [{"value": "new"}]}

    with pytest.raises(RuntimeError, match="final root write failure"):
        tx.transact(replace)
    assert db["state"]() == {"items": [{"value": "old"}]}
    assert list_db(db) == before


@pytest.mark.parametrize("execute_first", [False, True],
                         ids=["before-exec", "lost-acknowledgement"])
def test_execute_failure_preserves_only_an_unexecuted_batch(
        db, monkeypatch, execute_first):
    db["state"] = {"items": [{"value": "old"}]}
    before = list_db(db)
    pipeline = db.rdb.pipeline()
    real_execute = pipeline.execute
    calls = []

    def fail_execute():
        calls.append("execute")
        if execute_first:
            real_execute()
        raise TimeoutError("injected execute failure")

    monkeypatch.setattr(pipeline, "execute", fail_execute)
    monkeypatch.setattr(db.rdb, "pipeline", lambda: pipeline)
    tx = db.transactor()

    def replace():
        tx.multi()
        tx["state"] = {"items": [{"value": "new"}]}
        assert list_db(db) == before

    with pytest.raises(TimeoutError, match="execute failure"):
        tx.transact(replace)
    assert calls == ["execute"]
    if execute_first:
        assert db["state"]() == {"items": [{"value": "new"}]}
    else:
        assert list_db(db) == before


def test_redis_execution_error_does_not_roll_back_other_commands(db):
    if isinstance(db.rdb, SQLite):
        pytest.skip("Redis-specific execution-time error semantics")
    from redis.exceptions import ResponseError

    tx = db.transactor()

    def update():
        tx.multi()
        tx["before"] = 1
        tx.pipe.execute_command("LSET", "tx:missing-list", 0, "fail")
        tx["after"] = 2
        tx.incr("counter")

    with pytest.raises(ResponseError):
        tx.transact(update)
    assert db["before"] == 1
    assert db["after"] == 2
    assert db.count("counter") == 1


def test_conflicting_commit_does_not_publish_or_collect(db):
    db["state"] = {"items": [{"value": "old"}]}
    tx = db.transactor()
    tx.watch()
    tx.multi()
    try:
        tx["state"] = {"items": [{"value": "loser"}]}
        winner = db.transactor()

        def replace():
            winner.multi()
            winner["state"] = {"items": [{"value": "winner"}]}

        winner.transact(replace)
        committed = list_db(db)
        with pytest.raises(WatchError):
            tx.execute()
        assert list_db(db) == committed
    finally:
        tx.pipe.reset()


def test_transact_retries_with_fresh_graph_and_reuses_after_abort(db):
    db["state"] = {"items": []}
    tx = db.transactor()
    attempts = []

    def append():
        items = tx["state"]["items"]
        attempts.append(items())
        tx.multi()
        items.append("ours")
        if len(attempts) == 1:
            winner = db.transactor()

            def competing_append():
                other_items = winner["state"]["items"]
                winner.multi()
                other_items.append("theirs")

            winner.transact(competing_append)

    tx.transact(append)
    assert attempts == [[], ["theirs"]]
    assert db["state"]() == {"items": ["theirs", "ours"]}

    def abort():
        tx.multi()
        tx["state"] = {"items": []}
        raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        tx.transact(abort)
    tx.transact(append)
    assert db["state"]() == {"items": ["theirs", "ours", "ours"]}


def test_transaction_mapping_and_list_mutations(db):
    db["state"] = {"items": [1, 2, 3], "discard": {"nested": []}}
    before = list_db(db)
    tx = db.transactor()

    def update():
        state = tx["state"]
        items = state["items"]
        discard = state["discard"]
        assert items() == [1, 2, 3]
        assert tx.get_via_uid(state.uid).db is tx
        tx.multi()
        tx.update(flag=True, optional=None)
        assert tx.setdefault("flag", False) is True
        assert tx.pop("optional") is None
        items[-1] = 4
        items[1:2] = [5, 6]
        discard.clear()
        assert list_db(db) == before

    tx.transact(update)
    assert db() == {
        "state": {"items": [1, 5, 6, 4], "discard": {}}, "flag": True,
    }


def test_replacing_staged_graph_does_not_leak_intermediate_nodes(db):
    tx = db.transactor()

    def replace_twice():
        tx.multi()
        tx["state"] = {"items": [{"value": "intermediate"}]}
        tx["state"] = {"items": [{"value": "final"}]}

    tx.transact(replace_twice)
    assert db["state"]() == {"items": [{"value": "final"}]}
    final_uids = {node.uid.encode() for node in graph_nodes(db)}
    assert set(db.rdb.keys("tx:[DL]*")) == final_uids
    assert set(db.rdb.keys("back:tx:[DL]*")) == {
        b"back:" + uid for uid in final_uids
    }


def test_sqlite_commit_error_rolls_back_root_children_and_backrefs():
    backend = SQLite(":memory:")
    try:
        db = DB(redis=backend, prefix="tx")
        db["state"] = {"items": [{"value": "old"}]}
        before = list_db(db)
        backend._conn.execute("""
            CREATE TRIGGER fail_root BEFORE INSERT ON hkv
            WHEN NEW.hk = 'tx:data:' AND NEW.f = X'7374617465'
            BEGIN SELECT RAISE(ABORT, 'injected root failure'); END
        """)
        tx = db.transactor()

        def replace():
            tx.multi()
            tx["state"] = {"items": [{"value": "new"}]}

        with pytest.raises(sqlite3.IntegrityError, match="root failure"):
            tx.transact(replace)
        assert list_db(db) == before
        backend._conn.execute("DROP TRIGGER fail_root")
        tx.transact(replace)
        assert db["state"]() == {"items": [{"value": "new"}]}
    finally:
        backend.shutdown()


def test_sqlite_pipeline_delete_is_queued_and_rolled_back_on_failure():
    backend = SQLite(":memory:")
    try:
        backend.set("victim", "old")
        pipeline = backend.pipeline()
        pipeline.multi()
        pipeline.delete("victim")
        assert backend.get("victim") == b"old"
        pipeline.reset()
        assert backend.get("victim") == b"old"

        pipeline.multi()
        pipeline.delete("victim")
        pipeline.lset("missing", 0, "fail")
        with pytest.raises(IndexError):
            pipeline.execute()
        assert backend.get("victim") == b"old"
        pipeline.multi()
        pipeline.delete("victim")
        pipeline.execute()
        assert backend.get("victim") is None
    finally:
        backend.shutdown()
