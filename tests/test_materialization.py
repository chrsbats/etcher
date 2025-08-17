import os
import tempfile
import shutil
import unittest

from etcher.db import DB


class TestMaterializationIdentity(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.db = DB(self.db_path)
        self._rdb = self.db.rdb  # keep handle for cleanup

    def tearDown(self):
        try:
            if self._rdb is not None:
                try:
                    self._rdb.shutdown()
                except Exception:
                    pass
        finally:
            shutil.rmtree(self.tmpdir)

    def test_shared_substructure_identity(self):
        self.db["x"] = {"child": {"n": 1}}
        child = self.db["x"]["child"]
        self.db["y"] = {"a": child, "b": child}

        y = self.db["y"]()  # materialize to plain Python
        self.assertIs(y["a"], y["b"])  # same Python object

    def test_cycles_preserved(self):
        self.db["a"] = {"name": "A"}
        self.db["b"] = {"name": "B", "friend": self.db["a"]}
        self.db["a"]["friend"] = self.db["b"]

        a = self.db["a"]()  # materialize to plain Python
        self.assertIs(a["friend"]["friend"], a)  # cycle maintained
