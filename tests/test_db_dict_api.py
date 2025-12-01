import os
import shutil
import tempfile
import unittest

from etcher.db import DB


class TestDBDictAPI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.db = DB(self.db_path)

    def tearDown(self):
        try:
            self.db.shutdown()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_with_default(self):
        db = self.db
        self.assertEqual(db.get("missing", 42), 42)
        db["a"] = 1
        self.assertEqual(db.get("a", 5), 1)

    def test_update_setdefault_pop_popitem_clear_copy(self):
        db = self.db

        # update with mapping, iterable of pairs, and kwargs
        db.update({"a": 1, "b": 2})
        db.update([("c", 3)])
        db.update(d=4)

        # Materialized content check (order not guaranteed)
        self.assertEqual(db(), {"a": 1, "b": 2, "c": 3, "d": 4})

        # setdefault existing and new
        self.assertEqual(db.setdefault("a", 99), 1)
        self.assertEqual(db.setdefault("e", 5), 5)
        self.assertIn("e", db)
        self.assertEqual(db["e"], 5)

        # pop existing
        self.assertEqual(db.pop("b"), 2)
        self.assertNotIn("b", db)

        # pop missing with default
        self.assertEqual(db.pop("zzz", 99), 99)

        # pop missing without default raises
        with self.assertRaises(KeyError):
            db.pop("nope")

        # popitem removes one arbitrary item and returns it
        before = db.copy()
        k, v = db.popitem()
        self.assertIn(k, before)
        self.assertEqual(v, before[k])
        self.assertNotIn(k, db)

        # clear removes all
        db.clear()
        self.assertEqual(len(db), 0)
        self.assertFalse(bool(db))
        self.assertEqual(db.keys(), [])

        # copy returns plain dict
        db["x"] = 10
        db["y"] = 20
        d = db.copy()
        self.assertIsInstance(d, dict)
        self.assertEqual(d, {"x": 10, "y": 20})
