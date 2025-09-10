import os, shutil, tempfile, unittest
from unittest.mock import patch
from etcher.sqlitedis import Redis

class TestSqliteDisMore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "sqlite.db")
        self.r = Redis(self.db_path)

    def tearDown(self):
        try: self.r.shutdown()
        except Exception: pass
        shutil.rmtree(self.tmpdir)

    def test_strings_hashes_lists_extras(self):
        r = self.r
        # incr/decr with amount and exists
        self.assertEqual(r.exists(b"si"), 0)
        self.assertEqual(r.incr("si", 3), 3)
        self.assertEqual(r.decr("si", 2), 1)
        self.assertEqual(r.exists("si"), 1)
        # hset single-field and accessors
        self.assertEqual(r.hset("h", "f1", "v1"), 1)
        self.assertTrue(r.hexists("h", "f1"))
        self.assertEqual(set(r.hkeys("h")), {b"f1"})
        self.assertEqual(set(r.hvals("h")), {b"v1"})
        # llen empty and non-empty
        self.assertEqual(r.llen("lx"), 0)
        r.rpush("lx", "a")
        r.rpush("lx", "b")
        self.assertEqual(r.llen("lx"), 2)
        # delete returns count for multiple keys
        self.assertGreaterEqual(r.delete("si", "h", "lx"), 1)

    def test_pipeline_watch_tuple_and_set(self):
        r = self.r
        p = r.pipeline()
        p.watch((b"k1", b"k2"))
        p.watch({b"k3"})
        p.multi()
        p.set(b"k1", b"v1")
        p.hset(b"h2", b"f", b"v")
        p.execute()
        self.assertEqual(r.get(b"k1"), b"v1")
        self.assertEqual(r.hget(b"h2", b"f"), b"v")

    def test_maintenance_exception_branches(self):
        r = self.r
        # Patch execute to raise for specific PRAGMA/SQL to hit excepts
        orig_execute = r._conn.execute

        def flaky_execute(sql, *args, **kwargs):
            s = str(sql).upper()
            if "PRAGMA WAL_CHECKPOINT" in s:
                raise RuntimeError("fail wal")
            if "VACUUM" in s:
                raise RuntimeError("fail vacuum")
            if "PRAGMA OPTIMIZE" in s:
                raise RuntimeError("fail optimize")
            return orig_execute(sql, *args, **kwargs)

        with patch.object(r, "_conn") as mock_conn:
            mock_conn.execute.side_effect = flaky_execute
            # freelist/page_count queries also go through execute; fallback values handled
            r.maintenance()
