import os
import shutil
import tempfile
import unittest

from etcher.sqlitedis import Redis

class TestSqliteDisSmall(unittest.TestCase):
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

    def test_strings_exists_incr_amount(self):
        r = self.r
        self.assertEqual(r.exists(b"k"), 0)
        self.assertEqual(r.incr(b"k", 3), 3)
        self.assertEqual(r.decr(b"k", 2), 1)
        self.assertEqual(r.exists(b"k"), 1)
        self.assertEqual(r.get(b"k"), b"1")

    def test_hashes_mapping_and_meta_cleanup_and_accessors(self):
        r = self.r
        r.hset(b"h", mapping={b"a": b"1", b"b": b"2"})
        self.assertTrue(r.hexists(b"h", b"a"))
        self.assertEqual(set(r.hkeys(b"h")), {b"a", b"b"})
        self.assertEqual(set(r.hvals(b"h")), {b"1", b"2"})
        # hincrby new and existing
        self.assertEqual(r.hincrby(b"h", b"n", 2), 2)
        self.assertEqual(r.hincrby(b"h", b"n", 3), 5)
        # delete all fields removes key from keys()
        r.hdel(b"h", b"a", b"b", b"n")
        self.assertNotIn(b"h", set(r.keys(b"h*")))

    def test_lists_and_type_and_delete_no_keys(self):
        r = self.r
        r.rpush(b"l", b"x")
        r.rpush(b"l", b"y")
        self.assertEqual(r.lindex(b"l", -1), b"y")
        self.assertEqual(r.lrange(b"l", 0, -1), [b"x", b"y"])
        # type lookups
        self.assertEqual(r.type(b"l"), b"list")
        self.assertEqual(r.type(b"missing"), b"none")
        # keys with str and bytes pattern
        self.assertTrue(set(r.keys("*")) >= {b"l"})
        self.assertTrue(set(r.keys(b"*")) >= {b"l"})
        # scan chunking small count
        scanned = set(r.scan_iter(match=b"*", count=1))
        self.assertIn(b"l", scanned)
        # delete() with no args
        self.assertEqual(r.delete(), 0)
