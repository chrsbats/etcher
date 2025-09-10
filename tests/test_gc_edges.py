import os, shutil, tempfile, unittest, io
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

    def test_negative_count_warning_and_recursive_gc(self):
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
        # Extra decref to drive negative count warning path
        buf = io.StringIO()
        with redirect_stdout(buf):
            decr_ref(db, child.uid, parent.uid)
        out = buf.getvalue()
        self.assertIn("WARNING: A reference count is less than zero", out)
