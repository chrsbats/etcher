import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from etcher.db import DB, RD, decr_ref


class TestGCEdges(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.db = DB(self.db_path, prefix="gc")

    def tearDown(self):
        try:
            self.db.shutdown()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir)

    def test_recursive_gc_and_deleted_object_decrement_is_noop(self):
        db = self.db
        parent = RD(db)
        child = RD(db)
        parent["a"] = child
        parent["b"] = child  # two references from same parent
        # Deleting both should decref to zero and GC child
        del parent["a"]
        del parent["b"]
        # child data and its backref hash should be gone
        self.assertEqual(db.rdb.exists(child.uid), 0)
        self.assertEqual(db.rdb.exists("back:" + child.uid), 0)

        buf = io.StringIO()
        with redirect_stdout(buf):
            decr_ref(db, child.uid, parent.uid)
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(db.rdb.exists("back:" + child.uid), 0)

    def test_missing_backref_is_noop(self):
        db = self.db
        parent = RD(db)
        child = RD(db)
        child["value"] = 1

        buf = io.StringIO()
        with redirect_stdout(buf):
            decr_ref(db, child.uid, parent.uid)

        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(child["value"], 1)

    def test_top_level_cycle_gc_does_not_warn(self):
        db = self.db
        db["a"] = {}
        db["b"] = {"a": db["a"]}
        db["a"]["b"] = db["b"]
        a_uid = db["a"].uid
        b_uid = db["b"].uid

        buf = io.StringIO()
        with redirect_stdout(buf):
            del db["a"]
            del db["b"]

        self.assertNotIn(
            "WARNING: A reference count is less than zero", buf.getvalue()
        )
        self.assertEqual(db(), {})
        for uid in (a_uid, b_uid):
            self.assertEqual(db.rdb.exists(uid), 0)
            self.assertEqual(db.rdb.exists("back:" + uid), 0)
