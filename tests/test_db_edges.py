import os
import shutil
import tempfile
import unittest

from etcher.db import DB, RD, RL, WatchError


class TestDBEdges(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.db = DB(self.db_path)

    def tearDown(self):
        try:
            self.db.shutdown()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir)

    def test_get_via_uid_errors_and_success(self):
        # Non-UID
        with self.assertRaises(KeyError):
            self.db.get_via_uid("not-a-uid")
        # Not D/L (root data is not a D/L uid)
        with self.assertRaises(KeyError):
            self.db.get_via_uid(self.db.pfx + "data:")
        # Success paths
        self.db["x"] = {"a": 1}
        self.db["y"] = [1, 2]
        x_uid = self.db["x"].uid
        y_uid = self.db["y"].uid
        self.assertIsInstance(self.db.get_via_uid(x_uid), RD)
        self.assertIsInstance(self.db.get_via_uid(y_uid), RL)

    def test_rd_rl_bool_len_contains_slice_eq(self):
        self.db["d"] = {}
        self.db["l"] = []

        d = self.db["d"]
        l = self.db["l"]
        self.assertFalse(bool(d))
        self.assertEqual(len(d), 0)
        self.assertFalse(bool(l))
        self.assertEqual(len(l), 0)

        d["a"] = 1
        l.append(1)
        self.assertTrue(bool(d))
        self.assertTrue(bool(l))
        self.assertIn(1, l)
        self.assertNotIn(2, l)

        # Slicing variants
        l_full = l[:]
        self.assertEqual(l_full, [1])
        self.assertEqual(l[0:], [1])
        self.assertEqual(l[-2:], [1])
        self.assertEqual(l[1:3], [])

        # RD equality by content and identity
        d2 = self.db["d"]
        self.assertTrue(d == d2)  # same uid
        self.assertTrue(d == {"a": 1})  # by materialized content
        self.db["d2"] = {"a": 1}
        self.assertTrue(self.db["d2"] == {"a": 1})
        self.assertFalse(self.db["d2"] == d)  # different uid

        # RL equality by content and identity
        l2 = self.db["l"]
        self.assertTrue(l == l2)  # same uid
        self.assertTrue(l == [1])  # by materialized content
        self.db["l2"] = [1]
        self.assertTrue(self.db["l2"] == [1])
        self.assertFalse(self.db["l2"] == l)  # different uid

    def test_transact_guards_and_flow(self):
        # Guard rails: calling multi/execute without transactor
        with self.assertRaises(Exception):
            self.db.multi()
        with self.assertRaises(Exception):
            self.db.execute()

        # Proper transact usage auto-retries and resets pipeline
        self.db["nums"] = [1, 2, 3]
        t = self.db.transactor()

        def txn():
            xs = t["nums"]()
            t.multi()
            t["nums"] = xs + [4]

        t.transact(txn)
        self.assertEqual(self.db["nums"](), [1, 2, 3, 4])

        # After transact, normal operations still work (pipe.reset() covered)
        self.db["nums"] = [10]
        self.assertEqual(self.db["nums"](), [10])
