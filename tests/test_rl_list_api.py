import os
import shutil
import tempfile
import unittest

from etcher.db import DB


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
