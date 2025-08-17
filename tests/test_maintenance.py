import os
import tempfile
import shutil
import unittest
import asyncio

from etcher.db import DB


class TestMaintenance(unittest.TestCase):
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

    def test_maintenance_sync_noop_state(self):
        # Create some churn
        self.db["x"] = {"a": 1, "b": [1, 2, 3]}
        self.db["y"] = [self.db["x"], 5]
        del self.db["y"]

        before = self.db()  # logical snapshot (pure Python)

        # Should not raise and should not change logical state
        self.db.maintenance()
        after = self.db()

        self.assertEqual(before, after)

    def test_maintenance_async_noop_state(self):
        # Create some churn
        self.db["x"] = {"a": 1, "b": [1, 2, 3]}
        self.db["y"] = [self.db["x"], 5]
        del self.db["y"]

        before = self.db()  # logical snapshot (pure Python)

        async def run_async():
            await self.db.maintenance_async()

        # Should not raise and should not change logical state
        asyncio.run(run_async())
        after = self.db()

        self.assertEqual(before, after)
