# Backends

SQLite is the default backend. For embedded Redis, install `etcher[redislite]`
and pass the adapter class:

```python
from etcher import DB
from redislite import Redis

db = DB("redislite.rdb", redis_adapter=Redis)
```

To use a running Redis server, install `etcher[redis]` and pass a client:

```python
import redis
from etcher import DB

client = redis.Redis(host="localhost", port=6379)
db = DB(redis=client)
```

## Closing and reopening SQLite

Call `db.shutdown()` when finished. A new `DB(path)` can reopen the same file
and read the saved data, using the remembered prefix by default.

```python
from etcher import DB

db = DB("state.db")
db["saved"] = "preserved"
db.shutdown()

reopened = DB("state.db")
try:
    assert reopened["saved"] == "preserved"
finally:
    reopened.shutdown()
```

Within one process, DB objects opened with the same path and adapter share a
live backend. `shutdown()` closes that backend and removes it from the
connection cache. Existing DB objects and RD/RL handles using it are no longer
usable; construct a new `DB` to reopen the file.

## SQLite maintenance

Maintenance is optional housekeeping for optimizing or compacting the SQLite
file. Use `db.maintenance()` in synchronous code or
`await db.maintenance_async()` in async code. These methods are no-ops if the
backend doesn't provide the corresponding maintenance operation.
