"""Queue graph mutations through a native Redis-compatible pipeline."""


def _bytes(value):
    return value if isinstance(value, bytes) else str(value).encode("utf-8")


class Transaction:
    """Keep pending graph data only to plan reference counting and cleanup.

    Redis cannot return command results during MULTI. Etcher's mutation code
    needs old values and reference counts to decide which commands to queue.
    The pipeline owns the commands and their execution; this cache is discarded
    with the batch and does not provide SQL-style transactional reads.
    """

    def __init__(self, redis):
        self._redis = redis
        self._pipe = redis.pipeline()
        self._values = {}
        self._in_multi = False

    def __getattr__(self, name):
        return getattr(self._pipe, name)

    def multi(self):
        if self._in_multi:
            raise RuntimeError("MULTI calls cannot be nested")
        self._pipe.multi()
        self._in_multi = True

    def _read(self, key, container):
        key = _bytes(key)
        if self._in_multi and key in self._values:
            data = self._values[key]
            if data is not None:
                return data
            data = container()
        elif container is dict:
            data = self._redis.hgetall(key)
        else:
            data = self._redis.lrange(key, 0, -1)
        if self._in_multi:
            self._values[key] = data
        return data

    def execute(self):
        try:
            return self._pipe.execute()
        finally:
            self.reset()

    def reset(self):
        self._pipe.reset()
        self._values.clear()
        self._in_multi = False

    def exists(self, key):
        key = _bytes(key)
        if self._in_multi and key in self._values:
            return int(bool(self._values[key]))
        return self._redis.exists(key)

    def hgetall(self, key):
        return self._read(key, dict).copy()

    def hget(self, key, field):
        if not self._in_multi:
            return self._redis.hget(key, field)
        return self._read(key, dict).get(_bytes(field))

    def hkeys(self, key):
        return list(self._read(key, dict))

    def hvals(self, key):
        return list(self._read(key, dict).values())

    def hlen(self, key):
        return len(self._read(key, dict))

    def hexists(self, key, field):
        return _bytes(field) in self._read(key, dict)

    def hset(self, key, field=None, value=None, mapping=None):
        if not self._in_multi:
            return self._redis.hset(key, field, value, mapping=mapping)
        items = mapping if mapping is not None else {field: value}
        items = {_bytes(k): _bytes(v) for k, v in items.items()}
        data = self._read(key, dict)
        added = len(items.keys() - data.keys())
        if items:
            self._pipe.hset(key, mapping=items)
            data.update(items)
        return added

    def hdel(self, key, *fields):
        if not self._in_multi:
            return self._redis.hdel(key, *fields)
        data = self._read(key, dict)
        self._pipe.hdel(key, *fields)
        deleted = 0
        for field in fields:
            if _bytes(field) in data:
                del data[_bytes(field)]
                deleted += 1
        return deleted

    def hincrby(self, key, field, amount):
        if not self._in_multi:
            return self._redis.hincrby(key, field, amount)
        data = self._read(key, dict)
        value = int(data.get(_bytes(field), 0)) + int(amount)
        self._pipe.hincrby(key, field, amount)
        data[_bytes(field)] = _bytes(value)
        return value

    def lrange(self, key, start, stop):
        data = self._read(key, list)
        if start < 0:
            start += len(data)
        if stop < 0:
            stop += len(data)
        if stop < 0:
            return []
        return data[max(0, start):stop + 1]

    def lindex(self, key, index):
        try:
            return self._read(key, list)[index]
        except IndexError:
            return None

    def llen(self, key):
        return len(self._read(key, list))

    def rpush(self, key, value):
        if not self._in_multi:
            return self._redis.rpush(key, value)
        data = self._read(key, list)
        self._pipe.rpush(key, value)
        data.append(_bytes(value))
        return len(data)

    def lset(self, key, index, value):
        if not self._in_multi:
            return self._redis.lset(key, index, value)
        data = self._read(key, list)
        # Resolve negative indices against the pending list for both backends.
        if index < 0:
            index += len(data)
        if index < 0 or index >= len(data):
            raise IndexError("index out of range")
        self._pipe.lset(key, index, value)
        data[index] = _bytes(value)
        return True

    def delete(self, *keys):
        if not self._in_multi:
            return self._redis.delete(*keys)
        deleted = sum(self.exists(key) for key in set(keys))
        self._pipe.delete(*keys)
        for key in keys:
            self._values[_bytes(key)] = None
        return deleted
