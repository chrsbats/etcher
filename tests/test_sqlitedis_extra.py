import os
import shutil
import tempfile
import unittest
import asyncio

from etcher.sqlitedis import Redis


class TestSqliteDisExtra(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "sqlite.db")
        self.r = Redis(self.db_path)

    def tearDown(self):
        try:
            self.r.shutdown()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir)

    def test_keys_scan_types_and_delete(self):
        r = self.r
        # Populate string, hash, list
        r.set(b"s1", b"v")
        r.hset(b"h1", b"f1", b"v1")
        r.rpush(b"l1", b"a")

        # keys with bytes and str patterns
        self.assertTrue(set(r.keys(b"*")))
        self.assertEqual(set(r.keys(b"l*")), {b"l1"})
        self.assertEqual(set(r.keys("*")), set(k for k in r.keys(b"*")))
        # scan chunking
        self.assertEqual(set(r.scan_iter(match=b"*", count=1)), set(r.keys(b"*")))

        # type none on missing
        self.assertEqual(r.type(b"missing"), b"none")

        # hdel multiple and meta cleanup
        r.hset(b"h2", mapping={b"a": b"1", b"b": b"2"})
        self.assertEqual(r.hlen(b"h2"), 2)
        r.hdel(b"h2", b"a", b"b")
        self.assertEqual(r.hlen(b"h2"), 0)
        # After empty, key should be gone from meta, so not in keys()
        self.assertNotIn(b"h2", set(r.keys(b"h*")))

        # lindex negative; lset missing index raises
        self.assertEqual(r.lindex(b"l1", -1), b"a")
        with self.assertRaises(IndexError):
            r.lset(b"l1", 5, b"x")

    def test_pipeline_variations_and_accum(self):
        r = self.r
        p = r.pipeline()
        # list-form watch
        p.watch([b"pk1", b"pk2"])
        p.multi()
        # hset mapping and hincrby twice to exercise accumulation return
        self.assertEqual(p.hincrby(b"hh", b"n", 2), 2)
        self.assertEqual(p.hincrby(b"hh", b"n", 3), 5)
        p.hset(b"hh2", mapping={b"a": b"1", b"b": b"2"})
        p.hdel(b"hh2", b"a", b"b")
        # list ops queued
        p.rpush(b"ll", b"x")
        p.lset(b"ll", 0, b"y")  # will work after rpush
        p.execute()

        self.assertEqual(r.hget(b"hh", b"n"), b"5")
        self.assertEqual(r.lindex(b"ll", 0), b"y")
        self.assertEqual(r.hlen(b"hh2"), 0)
        self.assertNotIn(b"hh2", set(r.keys(b"hh*")))

        # explicit reset covers clearing of queue/watch state
        p.reset()
        # subsequent operations still work after reset
        p.watch([b"another"])
        p.multi()
        p.set(b"another", b"v")
        p.execute()
        self.assertEqual(r.get(b"another"), b"v")

    def test_maintenance_and_shutdown(self):
        # Should be safe no-ops that still execute code paths
        self.r.maintenance()
        asyncio.run(self.r.maintenance_async())
        # shutdown is covered in tearDown; call again to ensure idempotence handling
        self.r.shutdown()
