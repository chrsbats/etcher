import sys
from importlib import reload
import unittest


class TestExceptionsFallback(unittest.TestCase):
    def test_watcherror_fallback(self):
        # Ensure we execute the fallback definition path in etcher.exceptions
        saved_redis = sys.modules.pop("redis", None)
        try:
            import etcher.exceptions as exc
            # Force a reload with no 'redis' in sys.modules so import fails
            reload(exc)
            self.assertTrue(issubclass(exc.WatchError, RuntimeError))
        finally:
            # Restore and reload module to its normal state for other tests
            if saved_redis is not None:
                sys.modules["redis"] = saved_redis
            import etcher.exceptions as exc2
            reload(exc2)
