import os
import shutil
import tempfile
import unittest
import asyncio

from etcher.db import DB

class TestDBPrefixExtra(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_delete_prefix_batch_none_and_include_anchor(self):
        db = DB(self.db_path, prefix="p1")
        # Put some data
        db["a"] = 1
        # count=None should route to immediate delete
        self.assertTrue(db.delete_prefix_batch("p1", count=None))
        self.assertFalse(db.prefix_in_use("p1"))
        # Create anchor-only prefix manually
        r = db.rdb
        p = "anchoronly"
        # Create only the backref anchor without data
        r.hset(f"back:{p}:", ":root:", 1)
        self.assertFalse(db.prefix_in_use(p, include_anchor=False))
        self.assertTrue(db.prefix_in_use(p, include_anchor=True))
        # Clean up that anchor via immediate delete
        db.delete_prefix_immediately(p)
        self.assertFalse(db.prefix_in_use(p, include_anchor=True))

    def test_set_prefix_require_empty_raises_and_maintenance_wrappers(self):
        db = DB(self.db_path, prefix="useme")
        db["k"] = 1
        with self.assertRaises(ValueError):
            db.set_prefix("useme", require_empty=True)
        # Maintenance wrappers are safe no-ops
        db.maintenance()
        asyncio.run(db.maintenance_async())
