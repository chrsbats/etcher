import os
import shutil
import tempfile
import unittest

from etcher.db import DB


class TestPrefixDeletionAndDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_delete_prefix_batch_and_immediate(self):
        # Create prefix p1 with both dict and list objects
        db1 = DB(self.db_path, prefix="p1")
        rdb = db1.rdb
        db1["d"] = {"x": 1}
        db1["l"] = [1, 2, 3]
        p1 = db1.get_prefix()
        self.assertEqual(p1, "p1")
        self.assertTrue(db1.prefix_in_use("p1"))

        # Create another prefix p2 to ensure selective deletion works
        db2 = DB(self.db_path, prefix="p2")
        db2["y"] = {"a": 1}
        p2 = db2.get_prefix()
        self.assertEqual(p2, "p2")
        self.assertTrue(db2.prefix_in_use("p2"))

        # Batch delete p1 using scan_iter path
        made_progress = True
        while made_progress:
            made_progress = db2.delete_prefix_batch("p1", count=2)
        self.assertFalse(db2.prefix_in_use("p1"))
        # p2 data still present
        self.assertTrue(db2.prefix_in_use("p2"))

        # Immediate delete p2 with KEYS path
        self.assertTrue(db2.delete_prefix_immediately("p2"))
        self.assertFalse(db2.prefix_in_use("p2"))

        # last_prefix cleanup: after all prefixes removed, :last_prefix: should not point to removed one
        lp = rdb.get(':last_prefix:')
        # If driver had remembered a prefix but it's no longer in use, key may be gone
        if lp is not None:
            self.assertNotEqual(lp.decode("utf-8"), "p2")

    def test_set_prefix_require_empty(self):
        db = DB(self.db_path, prefix="inuse")
        self.assertTrue(db.prefix_in_use("inuse"))
        with self.assertRaises(ValueError):
            db.set_prefix("inuse", require_empty=True)
