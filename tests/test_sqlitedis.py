import os
import tempfile
import shutil
import unittest

try:
    from redislite import Redis as RLRedis
    HAVE_REDISLITE = True
except Exception:
    RLRedis = None
    HAVE_REDISLITE = False

from etcher.sqlitedis import Redis as SQLRedis

from etcher.exceptions import WatchError


def snapshot_state(r):
    """
    Capture current DB state as {key: (type, value)} with all data in bytes.
    - string -> (b'string', b'value')
    - hash   -> (b'hash', {b'field': b'value', ...})
    - list   -> (b'list', [b'v0', b'v1', ...])
    """
    state = {}
    for k in r.keys(b"*"):
        t = r.type(k)
        if t == b"string":
            v = r.get(k)
        elif t == b"hash":
            v = r.hgetall(k)
        elif t == b"list":
            v = r.lrange(k, 0, -1)
        else:
            # ignore unsupported types, should not appear in these tests
            continue
        state[k] = (t, v)
    return state


def clear_db(r):
    """
    Remove all keys in the current DB for the given client.
    Uses KEYS + DEL to avoid requiring flushdb support on the backend.
    """
    ks = list(r.keys(b"*"))
    if ks:
        r.delete(*ks)


@unittest.skipUnless(HAVE_REDISLITE, "redislite not installed")
class TestSqliteDisParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.rl_path = os.path.join(cls.tmpdir, "redislite.rdb")
        cls.sql_path = os.path.join(cls.tmpdir, "sqlite.db")
        cls.rl = RLRedis(cls.rl_path)
        cls.sql = SQLRedis(cls.sql_path)
        # Ensure clean DBs before running tests
        clear_db(cls.rl)
        clear_db(cls.sql)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.rl.shutdown()
        except Exception:
            pass
        try:
            cls.sql.shutdown()
        except Exception:
            pass
        shutil.rmtree(cls.tmpdir)

    def setUp(self):
        # Reuse shared instances and start from a clean state
        self.rl = type(self).rl
        self.sql = type(self).sql
        clear_db(self.rl)
        clear_db(self.sql)

    def tearDown(self):
        # No per-test shutdown; we reuse instances. Ensure clean DBs even if a test failed mid-operation.
        clear_db(self.rl)
        clear_db(self.sql)

    def assertStatesEqual(self):
        self.assertEqual(snapshot_state(self.rl), snapshot_state(self.sql))

    def test_strings(self):
        # initial state
        self.assertStatesEqual()

        # set/get/exists
        self.rl.set(b"k1", b"v1")
        self.sql.set(b"k1", b"v1")
        self.assertEqual(self.rl.get(b"k1"), self.sql.get(b"k1"))
        self.assertEqual(self.rl.exists(b"k1"), self.sql.exists(b"k1"))
        self.assertStatesEqual()

        # overwrite string
        self.rl.set(b"k1", b"v2")
        self.sql.set(b"k1", b"v2")
        self.assertEqual(self.rl.get(b"k1"), self.sql.get(b"k1"))
        self.assertStatesEqual()

        # incr/decr
        self.rl.set(b"cnt", b"10")
        self.sql.set(b"cnt", b"10")
        self.assertEqual(self.rl.incr(b"cnt"), self.sql.incr(b"cnt"))
        self.assertEqual(self.rl.incr(b"cnt", 5), self.sql.incr(b"cnt", 5))
        self.assertEqual(self.rl.decr(b"cnt"), self.sql.decr(b"cnt"))
        self.assertEqual(self.rl.decr(b"cnt", 3), self.sql.decr(b"cnt", 3))
        self.assertStatesEqual()

        # type/get missing
        self.assertEqual(self.rl.type(b"missing"), self.sql.type(b"missing"))
        self.assertEqual(self.rl.get(b"missing"), self.sql.get(b"missing"))

    def test_hashes(self):
        # hset single field (new)
        self.assertEqual(self.rl.hset(b"h1", b"f1", b"v1"), self.sql.hset(b"h1", b"f1", b"v1"))
        # hget/hlen/hexists
        self.assertEqual(self.rl.hget(b"h1", b"f1"), self.sql.hget(b"h1", b"f1"))
        self.assertEqual(self.rl.hlen(b"h1"), self.sql.hlen(b"h1"))
        self.assertEqual(self.rl.hexists(b"h1", b"f1"), self.sql.hexists(b"h1", b"f1"))
        # hkeys/hvals (order-insensitive)
        self.assertEqual(set(self.rl.hkeys(b"h1")), set(self.sql.hkeys(b"h1")))
        self.assertEqual(sorted(self.rl.hvals(b"h1")), sorted(self.sql.hvals(b"h1")))
        # hset mapping for additional new fields (avoid update count ambiguity)
        mapping = {b"f2": b"v2", b"f3": b"v3"}
        self.assertEqual(self.rl.hset(b"h1", mapping=mapping), self.sql.hset(b"h1", mapping=mapping))
        # hgetall
        self.assertEqual(self.rl.hgetall(b"h1"), self.sql.hgetall(b"h1"))
        # update existing field (do not assert return count; assert state)
        self.rl.hset(b"h1", b"f2", b"v2x")
        self.sql.hset(b"h1", b"f2", b"v2x")
        self.assertEqual(self.rl.hgetall(b"h1"), self.sql.hgetall(b"h1"))
        # hdel
        self.assertEqual(self.rl.hdel(b"h1", b"f1"), self.sql.hdel(b"h1", b"f1"))
        self.assertEqual(self.rl.hgetall(b"h1"), self.sql.hgetall(b"h1"))
        self.assertStatesEqual()

    def test_lists(self):
        # rpush/llen/lrange
        for v in [b"a", b"b", b"c"]:
            self.rl.rpush(b"l1", v)
            self.sql.rpush(b"l1", v)
        self.assertEqual(self.rl.llen(b"l1"), self.sql.llen(b"l1"))
        self.assertEqual(self.rl.lrange(b"l1", 0, -1), self.sql.lrange(b"l1", 0, -1))
        # lindex
        self.assertEqual(self.rl.lindex(b"l1", 0), self.sql.lindex(b"l1", 0))
        self.assertEqual(self.rl.lindex(b"l1", -1), self.sql.lindex(b"l1", -1))
        # lset
        self.rl.lset(b"l1", 1, b"bx")
        self.sql.lset(b"l1", 1, b"bx")
        self.assertEqual(self.rl.lrange(b"l1", 0, -1), self.sql.lrange(b"l1", 0, -1))
        self.assertStatesEqual()

    def test_keys_scan_delete_type(self):
        # populate
        self.rl.set(b"s1", b"v")
        self.sql.set(b"s1", b"v")
        self.rl.hset(b"h1", b"f", b"v")
        self.sql.hset(b"h1", b"f", b"v")
        self.rl.rpush(b"l1", b"v")
        self.sql.rpush(b"l1", b"v")

        # keys
        self.assertEqual(set(self.rl.keys(b"*")), set(self.sql.keys(b"*")))
        self.assertEqual(set(self.rl.keys(b"l*")), set(self.sql.keys(b"l*")))
        # type
        for k in [b"s1", b"h1", b"l1", b"zzz"]:
            self.assertEqual(self.rl.type(k), self.sql.type(k))
        # scan_iter (compare sets)
        self.assertEqual(set(self.rl.scan_iter(match=b"*", count=10)), set(self.sql.scan_iter(match=b"*", count=10)))
        self.assertEqual(set(self.rl.scan_iter(match=b"l*", count=1)), set(self.sql.scan_iter(match=b"l*", count=1)))

        # delete single and multiple
        self.assertEqual(self.rl.delete(b"s1"), self.sql.delete(b"s1"))
        self.assertEqual(self.rl.delete(b"h1", b"l1"), self.sql.delete(b"h1", b"l1"))
        self.assertStatesEqual()

    def test_overwrite_types(self):
        # Start with hash, then overwrite with string
        self.rl.hset(b"k", b"f", b"v")
        self.sql.hset(b"k", b"f", b"v")
        self.assertEqual(self.rl.type(b"k"), self.sql.type(b"k"))
        self.rl.set(b"k", b"s")
        self.sql.set(b"k", b"s")
        self.assertEqual(self.rl.type(b"k"), self.sql.type(b"k"))
        self.assertEqual(self.rl.get(b"k"), self.sql.get(b"k"))
        self.assertStatesEqual()

        # Overwrite with list
        self.rl.delete(b"k")
        self.sql.delete(b"k")
        self.rl.set(b"k", b"s2")
        self.sql.set(b"k", b"s2")
        self.rl.delete(b"k")
        self.sql.delete(b"k")
        self.rl.rpush(b"k", b"a")
        self.sql.rpush(b"k", b"a")
        self.assertEqual(self.rl.type(b"k"), self.sql.type(b"k"))
        self.assertStatesEqual()

    def test_pipeline_watch_multi_execute(self):
        # baseline
        self.rl.set(b"pk", b"v")
        self.sql.set(b"pk", b"v")

        # successful transaction
        pr = self.rl.pipeline()
        pr.watch(b"pk")
        pr.multi()
        pr.set(b"pk", b"v1")
        pr.execute()
        ps = self.sql.pipeline()
        ps.watch(b"pk")
        ps.multi()
        ps.set(b"pk", b"v1")
        ps.execute()
        self.assertStatesEqual()

        # conflict causing WatchError
        pr = self.rl.pipeline()
        pr.watch(b"pk")
        # external change before execute
        self.rl.set(b"pk", b"v2")
        pr.multi()
        pr.set(b"pk", b"x")  # will be discarded
        with self.assertRaises(WatchError):
            pr.execute()

        ps = self.sql.pipeline()
        ps.watch(b"pk")
        self.sql.set(b"pk", b"v2")
        ps.multi()
        ps.set(b"pk", b"x")
        with self.assertRaises(WatchError):
            ps.execute()

        # ensure unchanged by failed exec
        self.assertStatesEqual()
