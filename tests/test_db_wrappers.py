import os, shutil, tempfile, unittest
from etcher.db import DB, RD, RL, db_key_type

class TestDBWrappers(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.db = DB(self.db_path, prefix="wrap")

    def tearDown(self):
        try: self.db.shutdown()
        except Exception: pass
        shutil.rmtree(self.tmpdir)

    def test_counters_and_wrappers_and_flush(self):
        db = self.db
        # counters
        self.assertEqual(db.count("c"), 0)
        self.assertEqual(db.incr("c"), 1)
        self.assertEqual(db.incr("c", 2), 3)
        self.assertEqual(db.decr("c"), 2)
        self.assertEqual(db.decr("c", 2), 0)
        self.assertEqual(db.count("c"), 0)
        # RD top-level behavior
        db["a"] = 1
        db["b"] = 2
        self.assertIn("a", db)
        self.assertEqual(set(db.keys()), {"a", "b"})
        self.assertEqual(sorted(db.values()), [1, 2])
        self.assertEqual(dict(db.items()), {"a": 1, "b": 2})
        # __iter__
        self.assertEqual(set(iter(db)), {"a", "b"})
        # __call__ materializes top RD
        snap = db()
        self.assertEqual(snap, {"a": 1, "b": 2})
        # flush clears items
        db.flush()
        self.assertEqual(dict(db.items()), {})

    def test_get_via_uid_success_and_error(self):
        db = self.db
        rd = RD(db)
        rl = RL(db)
        # success
        self.assertIsInstance(db.get_via_uid(rd.uid), RD)
        self.assertIsInstance(db.get_via_uid(rl.uid), RL)
        # error
        with self.assertRaisesRegex(KeyError, "not an RD/RL"):
            db.get_via_uid("not-a-uid")
