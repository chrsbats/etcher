import os
import tempfile
import shutil
import unittest

from etcher.db import DB


class TestAPIMisc(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.db = DB(self.db_path)
        self._rdb = self.db.rdb

    def tearDown(self):
        try:
            if self._rdb is not None:
                try:
                    self._rdb.shutdown()
                except Exception:
                    pass
        finally:
            shutil.rmtree(self.tmpdir)

    def test_incr_decr_amounts(self):
        # incr without amount -> +1
        self.assertEqual(self.db.incr("cnt"), 1)
        # incr with amount -> +5 (no double-apply)
        self.assertEqual(self.db.incr("cnt", 5), 6)
        # decr without amount -> -1
        self.assertEqual(self.db.decr("cnt"), 5)
        # decr with amount -> -2
        self.assertEqual(self.db.decr("cnt", 2), 3)

    def test_get_via_uid_rd_and_rl(self):
        self.db["x"] = {"a": 1}
        x_uid = self.db["x"].uid
        x_obj = self.db.get_via_uid(x_uid)
        self.assertEqual(x_obj.uid, x_uid)
        self.assertEqual(x_obj["a"], 1)

        self.db["y"] = [1, 2, 3]
        y_uid = self.db["y"].uid
        y_obj = self.db.get_via_uid(y_uid)
        self.assertEqual(y_obj.uid, y_uid)
        self.assertEqual(len(y_obj), 3)
