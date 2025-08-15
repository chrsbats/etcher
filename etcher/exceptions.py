try:
    from redis.exceptions import WatchError as WatchError
except Exception:
    class WatchError(RuntimeError):
        pass
