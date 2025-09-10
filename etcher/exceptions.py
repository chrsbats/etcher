import sys

if "redis" not in sys.modules:
    class WatchError(RuntimeError):
        pass
else:
    from redis.exceptions import WatchError as WatchError
