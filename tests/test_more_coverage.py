import os
import shutil
import tempfile
import unittest

from etcher.db import DB, RD, RL, list_db

class TestMoreCoverage(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.db = DB(self.db_path, prefix="cov")

    def tearDown(self):
        try:
            self.db.shutdown()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir)

    def test_db_and_rd_iter_items_values_flush_and_eq(self):
        d = self.db
        rd = RD(d)
        rd["a"] = 1
        rd["b"] = {"x": 2}   # creates nested RD, backrefs
        rd["c"] = [3, 4]     # creates RL, backrefs
        # DB dict-like proxies
        d["root_key"] = 123
        self.assertIn("root_key", d)
        self.assertTrue(list(d.keys()))
        self.assertTrue(list(d.values()))
        self.assertTrue(list(d.items()))
        # RD proxies/eq branches
        mat = rd()
        self.assertIsInstance(mat, dict)
        self.assertTrue(rd == mat)
        self.assertTrue(rd == RD(d, uid=rd.uid))
        self.assertFalse(rd == RD(d))  # different identity
        # list_db to touch string/hash/list branches
        snap = list_db(d)
        self.assertIsInstance(snap, dict)
        # Flush (iterates and deletes each key in root RD)
        d.flush()
        self.assertEqual(len(d.data), 0)

    def test_rl_slice_empty_and_contains_and_eq(self):
        d = self.db
        rl = RL(d)
        a = RD(d); a["x"] = 1
        rl.append(a)
        rl.append(2)
        rl.append(3)
        # empty slice path (stop < start after normalization)
        self.assertEqual(rl[5:3], [])
        # contains True and False paths (uses materialization)
        self.assertIn(2, rl)
        self.assertNotIn(42, rl)
        # eq to list and to another RL instance
        self.assertTrue(rl == [a, 2, 3])
        self.assertTrue(rl == RL(d, uid=rl.uid))
        self.assertFalse(rl == RL(d))  # different identity

    def test_decr_ref_partial_no_gc(self):
        d = self.db
        rl = RL(d)
        a = RD(d); a["x"] = 1
        rl.append(a); rl.append(a)
        # remove one occurrence -> backref counter > 0, no GC
        rl[0] = 0
        self.assertEqual(a.refcount, 1)
        self.assertEqual(a.backrefs[rl.uid], 1)
        # still resolvable
        self.assertIsInstance(d.get_via_uid(a.uid), RD)

    def test_sqlitedis_broad_paths(self):
        r = self.db.rdb
        # _b unknown type fallback via set: object() coerced with str()
        class X:
            def __repr__(self): return "<X>"
        self.assertTrue(r.set("weird", X()))
        self.assertIsNotNone(r.get("weird"))
        # _s handles non-bytes keys implicitly through str()
        self.assertTrue(r.set(123, "n"))
        self.assertEqual(r.get("123"), b"n")
        # keys with no pattern argument, ensure returns bytes[] (already returns)
        self.assertIsInstance(r.keys(), list)
        # lrange normalization (stop beyond range; negative start)
        r.rpush(b"LL", b"a")
        r.rpush(b"LL", b"b")
        r.rpush(b"LL", b"c")
        self.assertEqual(r.lrange(b"LL", -10, 99), [b"a", b"b", b"c"])
        # lindex negative beyond range returns None path
        self.assertIsNone(r.lindex(b"LL", -99))
        # scan_iter chunking with small count
        self.assertTrue(set(r.scan_iter(match=b"*", count=1)))

    def test_pipeline_watch_tuple_and_execute_again(self):
        r = self.db.rdb
        p = r.pipeline()
        # tuple-form watch
        p.watch((b"k1", b"k2"))
        p.multi()
        p.set(b"k1", b"v1")
        p.hset(b"h", mapping={b"a": b"1"})
        p.execute()
        # Reuse pipeline after reset to ensure it still works
        p.reset()
        p.watch((b"k3",))
        p.multi()
        p.rpush(b"llx", b"x")
        p.lset(b"llx", 0, b"y")
        p.execute()
        self.assertEqual(r.lindex(b"llx", 0), b"y")
