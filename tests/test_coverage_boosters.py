import os
import shutil
import tempfile
import unittest

from etcher.db import DB, RD, RL, decr_ref

class TestCoverageBoosters(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_delete_prefix_batch_count_none_immediate(self):
        db = DB(self.db_path, prefix="pimm")
        db["d"] = {"a": 1}
        db["l"] = [1, 2]
        self.assertTrue(db.prefix_in_use("pimm"))
        # count=None -> immediate path
        self.assertTrue(db.delete_prefix_batch("pimm", count=None))
        self.assertFalse(db.prefix_in_use("pimm"))

    def test_decr_ref_negative_warning_and_already_processed(self):
        db = DB(self.db_path, prefix="neg")
        rl = RL(db)
        child = RD(db); child["x"] = 1
        rl.append(child); rl.append(child)
        # remove both occurrences: GC should delete child
        rl[0] = 0
        rl[1] = 0
        # Force another decref on already-deleted child: triggers new_count < 0 and early return
        decr_ref(db, child.uid, rl.uid)

    def test_redis_delete_no_keys_and_pipeline_rpush_placeholder(self):
        db = DB(self.db_path, prefix="pl")
        r = db.rdb
        self.assertEqual(r.delete(), 0)  # no keys
        p = r.pipeline()
        p.multi()
        # rpush returns placeholder 0 while in MULTI
        self.assertEqual(p.rpush(b"ll", b"x"), 0)
        p.execute()
        self.assertEqual(r.lindex(b"ll", 0), b"x")

    def test_prefix_in_use_anchor_only(self):
        db = DB(self.db_path, prefix="onlyanchor")
        pfx = "onlyanchor"
        root_key = db._root_key(pfx)  # e.g., "onlyanchor:data:"
        # Delete root key only; anchor remains
        db.rdb.delete(root_key)
        self.assertFalse(db.prefix_in_use(pfx))
        self.assertTrue(db.prefix_in_use(pfx, include_anchor=True))

    def test_empty_rd_rl_are_falsy(self):
        db = DB(self.db_path, prefix="bools")
        rd = RD(db)
        rl = RL(db)
        self.assertFalse(bool(rd))
        self.assertFalse(bool(rl))
