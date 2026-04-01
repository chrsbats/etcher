import os
import shutil
import tempfile
import unittest
from collections.abc import MutableMapping, MutableSequence

from etcher.db import DB, RD, RL


class TestRDRLEdges(unittest.TestCase):
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

    def test_rd_equality_and_dict_materialization(self):
        rd1 = RD(self.db)
        rd2 = RD(self.db)
        rd1["a"] = 1
        rd2["a"] = 1
        # RD vs dict content equality
        self.assertEqual(rd1, {"a": 1})
        self.assertEqual({"a": 1}, rd1)
        # RD equality is content-based
        self.assertEqual(rd1, rd1)
        self.assertEqual(rd1, rd2)

    def test_rd_satisfies_mutable_mapping(self):
        rd = RD(self.db)
        rd["a"] = 1
        rd["b"] = 2

        self.assertIsInstance(rd, MutableMapping)
        self.assertEqual(dict(rd), {"a": 1, "b": 2})

    def test_rl_slicing_contains_add_iter(self):
        rl1 = RL(self.db)
        rl1.extend([1, 2, 3])
        # full slice and partial slices
        self.assertEqual(rl1[:], [1, 2, 3])
        self.assertEqual(rl1[:2], [1, 2])
        self.assertEqual(rl1[1:], [2, 3])
        # contains via materialization
        self.assertIn(2, rl1)
        # add returns Python list
        self.assertEqual(rl1 + [4], [1, 2, 3, 4])
        # iter path
        self.assertEqual(list(iter(rl1)), [1, 2, 3])

    def test_rl_satisfies_mutable_sequence_and_content_equality(self):
        rl1 = RL(self.db)
        rl2 = RL(self.db)
        rl1.extend([1, 2, 3])
        rl2.extend([1, 2, 3])

        self.assertIsInstance(rl1, MutableSequence)
        self.assertEqual(list(rl1), [1, 2, 3])
        self.assertEqual(rl1, [1, 2, 3])
        self.assertEqual([1, 2, 3], rl1)
        self.assertEqual(rl1, rl2)

    def test_rl_slice_step_and_assignment(self):
        rl = RL(self.db)
        rl.extend([0, 1, 2, 3, 4])

        self.assertEqual(rl[::2], [0, 2, 4])
        self.assertEqual(rl[::-1], [4, 3, 2, 1, 0])

        rl[1:4] = [10, 11]
        self.assertEqual(rl(), [0, 10, 11, 4])

    def test_rd_keys_values_items_and_repr_link_field(self):
        # Prepare child with link field used for repr
        self.db.link_field = "id"
        child = RD(self.db)
        child["id"] = "X"
        rd = RD(self.db)
        rd["x"] = child
        # keys/values/items decode
        self.assertEqual(set(rd.keys()), {"x"})
        vals = rd.values()
        self.assertTrue(vals and isinstance(vals[0], RD))
        items = dict(rd.items())
        self.assertIn("x", items)
        # repr should contain unquoted link X
        rep = repr(rd)
        self.assertIn("X", rep)

    def test_multi_execute_guards(self):
        # Calling multi/execute without transactor should raise
        with self.assertRaises(Exception):
            self.db.multi()
        with self.assertRaises(Exception):
            self.db.execute()
