import os
import tempfile
import shutil
import unittest

from etcher.db import DB


class TestLinkField(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._rdb = None

    def tearDown(self):
        try:
            if self._rdb is not None:
                try:
                    self._rdb.shutdown()
                except Exception:
                    pass
        finally:
            shutil.rmtree(self.tmpdir)

    def test_repr_without_link_field_shows_uid(self):
        # Without link_field, nested RD prints an internal UID (not the 'id' value)
        db_path = os.path.join(self.tmpdir, "nolink.db")
        db = DB(db_path)
        self._rdb = db.rdb

        db["person"] = {"id": "123", "name": "Alice"}
        db["task"] = {"owner": db["person"], "status": "waiting"}

        s = str(db["task"])
        self.assertIn("@{", s)
        self.assertIn("'status': 'waiting'", s)
        # Docs: without link_field, summary shows an internal UID for nested RD
        self.assertIn("'owner':", s)
        self.assertNotIn("'owner': 123", s)

    def test_repr_with_link_field_uses_id_value(self):
        # With link_field='id', nested RD prints that field's value (unquoted) instead of UID
        db_path = os.path.join(self.tmpdir, "withlink.db")
        db = DB(db_path, link_field="id")
        self._rdb = db.rdb

        db["person"] = {"id": "123", "name": "Alice"}
        db["task"] = {"owner": db["person"], "status": "waiting"}

        s = str(db["task"])
        self.assertIn("@{", s)
        self.assertIn("'status': 'waiting'", s)
        # Docs example: -> @{'owner': 123, 'status': 'waiting'}
        self.assertIn("'owner': 123", s)

    def test_repr_with_link_field_string_id_unquoted(self):
        db_path = os.path.join(self.tmpdir, "withlink2.db")
        db = DB(db_path, link_field="id")
        self._rdb = db.rdb

        db["person"] = {"id": "alice-42", "name": "Alice"}
        db["task"] = {"owner": db["person"], "status": "waiting"}

        s = str(db["task"])
        self.assertIn("@{", s)
        self.assertIn("'status': 'waiting'", s)
        # String ID should be rendered without quotes in the summary
        self.assertIn("'owner': alice-42", s)
        self.assertNotIn("'owner': 'alice-42'", s)

    def test_star_shorthand_when_key_equals_id(self):
        # With link_field='id', when a child RD's link equals the dict key, summary shows *
        db_path = os.path.join(self.tmpdir, "star.db")
        db = DB(db_path, link_field="id")
        self._rdb = db.rdb

        db["people"] = {
            "alice": {"id": "alice", "name": "Alice"},
            "bob": {"id": "BOB", "name": "Bob"},
        }

        s = str(db["people"])
        self.assertIn("'alice': *", s)
        self.assertIn("'bob': BOB", s)
