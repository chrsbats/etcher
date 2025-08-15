# Etcher

Persistent, reference-counted Python containers backed by a Redis-like key/value store.

## Why use this?
- You want your Python app’s state to persist across restarts without running a separate database server.
- You just run Python and get a persistent dictionary/list that stores JSON-style data (strings, numbers, booleans, None, dicts, lists).
- Start simple with a single file on disk; swap backends later without changing your app logic.

Etcher gives you two containers:
- RD: a dict-like object persisted in a backend store
- RL: a list-like object persisted in a backend store

They support nested graphs, automatic garbage collection (including cycles), simple transactions, and cross‑process usage. Default backend is SQLite (fast, durable, zero external services). You can swap to embedded redislite or a real Redis server without changing your RD/RL code.

### Highlights
- Dict/list semantics: get/set/del, iteration, slicing, etc.
- Persistent nested graphs: store references, not deep copies.
- Automatic cleanup (including cycles): Etcher tracks backreferences and, on unlink, checks reachability from the root. Subgraphs no longer reachable are reclaimed recursively. This avoids leaks that plain refcounting would miss, even with cycles.
- Transactions (optional): optimistic transactions with auto‑retry.
- Cross-process friendly: safe with one writer at a time on SQLite (WAL).
- Pluggable backends: SQLite (default), redislite, or real Redis.

## Install
- Python 3.8+
- From this repo:
  - pip install -e .

## Quick start (SQLite backend, default)
```python
from etcher import DB

# Create or open a persistent DB file; "prefix" namespaces your app’s keys.
db = DB("state.db", prefix="app", link_field="id")

# Store a dict (RD) and a list (RL)
db["person"] = {"id": "123", "name": "Alice", "tags": ["a", "b"]}
assert db["person"]()["name"] == "Alice"         # materialize to a Python dict
assert db["person"]["tags"]() == ["a", "b"]      # RL materializes to a list

# References are preserved (no deep copy): nested graphs stay linked
ref = db["person"]
db["task"] = {"owner": ref, "status": "waiting"}
assert db["task"]["owner"]["name"] == "Alice"
assert db["person"].refcount >= 2  # referenced by top-level 'person' and inside 'task'
```

Cycle-safe GC (garbage collector)
- Etcher tracks links between objects and updates them automatically on set/del.
- When the last external reference to a structure goes away, anything no longer reachable from the database root is cleaned up automatically — even if it contains cycles.

```python
# Build a cycle
db["a"] = {"name": "A"}
db["b"] = {"name": "B", "ref_to_a": db["a"]}
db["a"]["ref_to_b"] = db["b"]

# Remove top-level references; the cycle is no longer reachable and gets collected
del db["a"]
del db["b"]
assert db() == {}  # root is empty; cycle was collected
```

Background worker pattern (two processes)
- App process creates tasks and polls a status field.
- Worker process marks tasks running/finished/failed.

```python
# App process
db["tasks"]["T1"] = {"status": "waiting", "result": None}

# Worker process (separate process with its own DB(...) instance)
db["tasks"]["T1"]["status"] = "running"
# ... do work ...
db["tasks"]["T1"]["result"] = {"ok": True}
db["tasks"]["T1"]["status"] = "finished"

# App polls
while db["tasks"]["T1"]["status"] not in ("finished", "failed"):
    pass  # sleep in real code
result = db["tasks"]["T1"]["result"]
```

Transactions (optional)
```python
# Only needed if you want optimistic concurrency with auto-retry
t = db.transactor()
def txn():
    t.watch()
    t.multi()
    t["tasks"]["T1"]["status"] = "running"
t.transact(txn)
```

## Backends
- SQLite (default, recommended for “one app + worker” on one machine)
  - WAL mode, synchronous=NORMAL, busy_timeout, mmap enabled for performance.
  - Create with DB("state.db", prefix="app").
- Embedded Redis via redislite
```python
from redislite import Redis as RLRedis
db = DB("redislite.rdb", prefix="app", redis_adapter=RLRedis)
```
- Real Redis server
```python
import redis
r = redis.Redis(host="localhost", port=6379)
db = DB(prefix="app", redis=r)
```

## Performance notes
- Optimized SQLite pragmas are enabled by default for interactive workloads.
- Single writer at a time; readers are concurrent (WAL). Keep write sections short.
- See docs/performance.md for tuning tips (busy_timeout, cache_size, batching).

## Concurrency
- Recommended: one writer at a time. SQLite WAL supports many readers with a single writer.
- Multi-writer caveat: GC is best‑effort under concurrency. Simultaneous edits that add or remove links can delay cleanup.
- If you use multiple writers:
  - Group related writes in short transactions with DB.transactor().
  - Consider a background "recheck and delete" pass for extra safety on long‑running jobs.
- Without coordination, treat GC as best‑effort.

## Limitations
- Data model: JSON-style primitives only (strings, numbers, booleans, None, dicts, lists). No custom classes or objects; store data as plain dicts/lists.
- Transactions and keyspace locking: transactions serialize writes for an entire Etcher keyspace (prefix). Within a prefix, only one writer can commit at a time. You can use multiple independent prefixes on the same Redis/SQLite backend to avoid cross-interference.
- Concurrency: GC is best-effort under concurrent mutation. For heavy multi-writer workloads on the same prefix, keep transactions short or consider a networked Redis backend.

## Testing
- Run tests:
  - pytest -q
- SQLite vs redislite parity tests:
  - pytest tests/test_sqlitedis.py -q

## License
- MIT. See LICENSE.
