import importlib
import builtins
import unittest

class TestInitImportFallback(unittest.TestCase):
    def test_import_without_redis_falls_back(self):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "redis":
                raise ImportError("simulate missing redis")
            return real_import(name, *args, **kwargs)

        try:
            builtins.__import__ = fake_import
            mod = importlib.import_module("etcher.__init__")
            mod = importlib.reload(mod)
            # Should still expose these symbols
            self.assertTrue(hasattr(mod, "DB"))
            self.assertTrue(hasattr(mod, "RD"))
            self.assertTrue(hasattr(mod, "RL"))
            self.assertTrue(hasattr(mod, "WatchError"))
        finally:
            builtins.__import__ = real_import
            # Reload once more to exercise normal path too
            mod = importlib.import_module("etcher.__init__")
            importlib.reload(mod)
