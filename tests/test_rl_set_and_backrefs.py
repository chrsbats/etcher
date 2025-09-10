import os, shutil, tempfile, unittest
from etcher.db import DB, RD, RL

class TestRLSetAndBackrefs(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.db")
        self.db = DB(self.db_path, prefix="rls")

    def tearDown(self):
        try: self.db.shutdown()
        except Exception: pass
        shutil.rmtree(self.tmpdir)

    def test_setitem_decrements_old_and_increments_new(self):
        db = self.db
        rl = RL(db)
        a = RD(db); a["x"] = 1
        b = RD(db); b["y"] = 2
        # append two entries
        rl.append(a); rl.append(a)
        self.assertEqual(a.refcount, 1)
        self.assertEqual(a.backrefs[rl.uid], 2)
        # replace index 0 with b -> a decref once, b increments
        rl[0] = b
        self.assertEqual(a.backrefs[rl.uid], 1)
        self.assertEqual(b.backrefs[rl.uid], 1)
        self.assertEqual(a.refcount, 1)
        self.assertEqual(b.refcount, 1)
        # replace index 1 with a simple scalar should decref 'a' again
        rl[1] = 42
        self.assertEqual(a.refcount, 0)
        # sanity: values decode
        self.assertEqual(list(rl), [b, 42])

    def test_encode_list_and_dict_refs(self):
        db = self.db
        parent = RD(db)
        # list value creates RL and backref from new RL to parent
        parent["L"] = [1, 2, 3]
        rl = parent["L"]
        self.assertIsInstance(rl, RL)
        self.assertGreaterEqual(rl.refcount, 1)
        # dict value creates RD and backref
        parent["D"] = {"a": 1}
        rd = parent["D"]
        self.assertIsInstance(rd, RD)
        self.assertGreaterEqual(rd.refcount, 1)
