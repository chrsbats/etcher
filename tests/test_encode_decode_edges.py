import os
import shutil
import tempfile
import unittest

from etcher.db import DB, RD, RL, db_key_type
from etcher.db import decr_ref  # direct import for early-return path
from etcher.db import decode, encode  # sanity checks

class TestEncodeDecodeEdges(unittest.TestCase):
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

    def test_encode_decode_scalars_and_sentinels(self):
        d = self.db
        rd = RD(d)
        # Round-trip via encode/decode helpers
        self.assertEqual(decode(d, encode(d, None, rd.uid)), None)
        self.assertEqual(decode(d, encode(d, True, rd.uid)), True)
        self.assertEqual(decode(d, encode(d, False, rd.uid)), False)
        self.assertEqual(decode(d, encode(d, "hello", rd.uid)), "hello")
        self.assertEqual(decode(d, encode(d, 123, rd.uid)), 123)
        self.assertEqual(decode(d, encode(d, 1.25, rd.uid)), 1.25)

    def test_decode_keyerror_message(self):
        rd = RD(self.db)
        with self.assertRaisesRegex(KeyError, 'Key "missing" not found'):
            _ = rd["missing"]

    def test_db_key_type_edges(self):
        self.assertEqual(db_key_type(""), "")
        self.assertEqual(db_key_type(b""), "")
        self.assertEqual(db_key_type("x"), "")
        self.assertEqual(db_key_type("p:Dnotulid"), "")
        self.assertEqual(db_key_type("p:X123"), "")

    def test_get_via_uid_error_and_decr_ref_nonref(self):
        with self.assertRaisesRegex(KeyError, "not found"):
            self.db.get_via_uid("not-a-uid")
        # Early return path (non-ref value)
        decr_ref(self.db, "not-a-ref", "parent")
