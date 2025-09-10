import os, shutil, tempfile, unittest
from etcher.db import DB, RD, RL, find_refs

class TestFindRefsAndHousekeeping(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_find_refs_non_rdrl_returns_empty(self):
        db = DB(self.db_path, prefix="pX")
        self.assertEqual(find_refs(db, "not-a-uid"), [])
        self.assertEqual(find_refs(db, b"not-a-uid"), [])

    def test_batch_limit_and_anchor_recreate_and_last_prefix_cleanup(self):
        db = DB(self.db_path, prefix="pL")
        # add some keys under pL
        db["d"] = {"a": 1, "b": 2}
        db["l"] = [1, 2, 3]
        # delete current prefix in small batches to hit limit path
        iterations = 0
        while True:
            progressed = db.delete_prefix_batch("pL", count=1)
            iterations += 1
            if not progressed:
                break
        self.assertGreater(iterations, 1)  # needed multiple passes due to limit=1
        # data gone, but anchor recreated for current prefix
        self.assertFalse(db.prefix_in_use("pL", include_anchor=False))
        self.assertTrue(db.prefix_in_use("pL", include_anchor=True))
        # :last_prefix: cleared when current prefix deleted
        self.assertIsNone(db.rdb.get(":last_prefix:"))
