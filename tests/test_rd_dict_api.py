import os
import shutil
import tempfile
import unittest

from etcher.db import DB


class TestRDDictAPI(unittest.TestCase):
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
        rd = self.db.data
        self.assertEqual(rd.get("missing", 42), 42)
        rd["a"] = 1
        self.assertEqual(rd.get("a", 5), 1)

    def test_update_setdefault_pop_popitem_clear_copy(self):
        rd = self.db.data

        # update with mapping, iterable of pairs, and kwargs
        rd.update({"a": 1, "b": 2})
        rd.update([("c", 3)])
        rd.update(d=4)

        # Materialized content check (order not guaranteed)
        self.assertEqual(rd(), {"a": 1, "b": 2, "c": 3, "d": 4})

        # setdefault existing and new
        self.assertEqual(rd.setdefault("a", 99), 1)
        self.assertEqual(rd.setdefault("e", 5), 5)
        self.assertIn("e", rd)
        self.assertEqual(rd["e"], 5)

        # pop existing
        self.assertEqual(rd.pop("b"), 2)
        self.assertNotIn("b", rd)

        # pop missing with default
        self.assertEqual(rd.pop("zzz", 99), 99)

        # pop missing without default raises
        with self.assertRaises(KeyError):
            rd.pop("nope")

        # popitem removes one arbitrary item and returns it
        before = rd.copy()
        k, v = rd.popitem()
        self.assertIn(k, before)
        self.assertEqual(v, before[k])
        self.assertNotIn(k, rd)

        # clear removes all
        rd.clear()
        self.assertEqual(len(rd), 0)
        self.assertFalse(bool(rd))
        self.assertEqual(rd.keys(), [])

        # copy returns plain dict
        rd["x"] = 10
        rd["y"] = 20
        d = rd.copy()
        self.assertIsInstance(d, dict)
        self.assertEqual(d, {"x": 10, "y": 20})
