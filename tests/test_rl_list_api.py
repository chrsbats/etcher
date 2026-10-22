import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from etcher.db import DB, RD, RL


class TestRLListAPI(unittest.TestCase):
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

    def test_remove_and_pop(self):
        rd = self.db.data
        rd["lst"] = [1, 2, 2, 3]
        lst = rd["lst"]

        # remove first occurrence
        lst.remove(2)
        self.assertEqual(lst(), [1, 2, 3])

        # removing missing raises
        with self.assertRaises(ValueError):
            lst.remove(999)

        # pop default (last)
        self.assertEqual(lst.pop(), 3)
        self.assertEqual(lst(), [1, 2])

        # pop by index
        self.assertEqual(lst.pop(0), 1)
        self.assertEqual(lst(), [2])

        # pop from empty raises
        lst.clear()
        with self.assertRaises(IndexError):
            lst.pop()

    def test_insert_index_count_clear_copy(self):
        rd = self.db.data
        rd["lst"] = [1, 3]
        lst = rd["lst"]

        lst.insert(1, 2)
        self.assertEqual(lst(), [1, 2, 3])

        # index and count
        self.assertEqual(lst.index(2), 1)
        self.assertEqual(lst.count(2), 1)
        with self.assertRaises(ValueError):
            lst.index(999)

        # copy returns plain list snapshot
        cp = lst.copy()
        self.assertIsInstance(cp, list)
        self.assertEqual(cp, [1, 2, 3])

        # clear empties
        lst.clear()
        self.assertEqual(len(lst), 0)
        self.assertEqual(lst(), [])

    def test_reverse_sort_and_iadd_and_delitem(self):
        rd = self.db.data
        rd["lst"] = [3, 1, 2]
        lst = rd["lst"]

        lst.reverse()
        self.assertEqual(lst(), [2, 1, 3])

        lst.sort()
        self.assertEqual(lst(), [1, 2, 3])

        lst.sort(reverse=True)
        self.assertEqual(lst(), [3, 2, 1])

        # sort with key
        rd["s"] = ["b", "aa", "c"]
        s = rd["s"]
        s.sort(key=len)
        self.assertEqual(s(), ["b", "c", "aa"])

        # __iadd__
        lst += [4, 5]
        self.assertEqual(lst(), [3, 2, 1, 4, 5])

        # __delitem__ by index
        del lst[1]
        self.assertEqual(lst(), [3, 1, 4, 5])

        # __delitem__ by slice
        del lst[1:3]
        self.assertEqual(lst(), [3, 5])

    def test_contains_nested_and_wrapper_values(self):
        shared = RD(self.db)
        shared["x"] = 1
        lst = RL(self.db)
        lst.extend([{"a": 1}, [1, 2], shared, 3])

        self.assertIn({"a": 1}, lst)
        self.assertIn([1, 2], lst)
        self.assertIn(shared, lst)
        self.assertIn(3, lst)
        self.assertNotIn({"a": 2}, lst)
        self.assertNotIn([2, 1], lst)
        self.assertNotIn(4, lst)
        self.assertNotIn((1, 2), lst)

    def test_contains_empty_list(self):
        self.assertNotIn(1, RL(self.db))

    def test_contains_scalar_list_uses_one_read_call(self):
        lst = RL(self.db)
        lst.extend([1, 2, 3])

        with patch.object(
            self.db.pipe, "lrange", wraps=self.db.pipe.lrange
        ) as lrange, patch.object(
            self.db.pipe, "hgetall", wraps=self.db.pipe.hgetall
        ) as hgetall:
            self.assertIn(2, lst)

        self.assertEqual(lrange.call_count, 1)
        self.assertEqual(hgetall.call_count, 0)

    def test_contains_stops_before_loading_later_nested_values(self):
        lst = RL(self.db)
        lst.extend([1, {"a": {"b": 1}}, 3])

        with patch.object(
            self.db.pipe, "hgetall", wraps=self.db.pipe.hgetall
        ) as hgetall:
            self.assertIn(1, lst)

        self.assertEqual(hgetall.call_count, 0)

    def test_contains_fetches_shared_nested_value_once(self):
        shared = RD(self.db)
        shared["x"] = 1
        lst = RL(self.db)
        lst.extend([shared, shared, 3])

        with patch.object(
            self.db.pipe, "hgetall", wraps=self.db.pipe.hgetall
        ) as hgetall:
            self.assertIn(3, lst)

        self.assertEqual(hgetall.call_count, 1)
