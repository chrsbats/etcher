import os
import tempfile
import shutil
import unittest

from etcher.db import DB


class TestLastPrefix(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self._rdb = None  # tracked so we can shutdown in tearDown

    def tearDown(self):
        try:
            if self._rdb is not None:
                try:
                    self._rdb.shutdown()
                except Exception:
                    pass
        finally:
            shutil.rmtree(self.tmpdir)

    def test_reuse_last_prefix_numeric_default(self):
        # First open with no prefix/new_prefix -> should create a new numeric prefix and persist :last_prefix:
        db1 = DB(self.db_path)
        self._rdb = db1.rdb  # keep handle for cleanup
        p1 = db1.get_prefix()
        last = db1.rdb.get(':last_prefix:')
        self.assertIsNotNone(last)
        self.assertEqual(last.decode('utf-8'), p1)
        dbs_before = db1.rdb.get(':dbs:')

        # Second open with no prefix -> should reuse last prefix and NOT bump :dbs:
        db2 = DB(self.db_path)
        self.assertIs(db2.rdb, db1.rdb)  # same underlying connection in-process
        p2 = db2.get_prefix()
        self.assertEqual(p2, p1)
        dbs_after = db2.rdb.get(':dbs:')
        self.assertEqual(dbs_before, dbs_after)

    def test_remember_explicit_prefix(self):
        # Explicit prefix should be remembered in :last_prefix:
        db1 = DB(self.db_path, prefix="custom")
        self._rdb = db1.rdb  # keep handle for cleanup
        self.assertEqual(db1.get_prefix(), "custom")
        self.assertEqual(db1.rdb.get(':last_prefix:').decode('utf-8'), "custom")

        # Next open without prefix should reuse "custom"
        db2 = DB(self.db_path)
        self.assertIs(db2.rdb, db1.rdb)  # same underlying connection in-process
        self.assertEqual(db2.get_prefix(), "custom")
