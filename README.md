# Etcher

Persistent Python dict/list containers that behave like plain JSON‑ish data. No server, no schema. Put your structures in; read them back.

- Store JSON-style Python data: strings, numbers, booleans, None, dict, list
- Nested structures are stored by reference (no deep copies)
- Durable on-disk storage (SQLite by default)
- Use an optional Redis compatible backend without changing your code

## Install

- From this repo:
  - pip install -e .
- Optional extras:
  - pip install 'etcher[redislite]'
  - pip install 'etcher[redis]'

## Quick start

```python
from etcher import DB

# Create or open a persistent DB file
db = DB("state.db")

# Dump a JSON-like Python structure
db["person"] = {"id": "123", "name": "Alice", "tags": ["a", "b"]}

# Access fields naturally
assert db["person"]["name"] == "Alice"
assert db["person"]["tags"][0] == "a"

# Materialize the whole object to a normal Python dict/list when you need it
assert db["person"]() == {"id": "123", "name": "Alice", "tags": ["a", "b"]}
```

### What are RD and RL?

- RD is Etcher’s persistent dict container.
- RL is Etcher’s persistent list container.
- They behave like dict/list for field and index access, but values are stored persistently and nested structures are linked by reference.
- The printed form is a safe summary and starts with '@' to signal “this is a persisted RD/RL object,” not a plain Python container. Use RD() or RL() to materialize plain Python dict/list values.

### Printing RD/RL summaries

- RD prints like `@{'field': value, ...}`
- RL prints like `@[value, ...]`
- We don’t print entire subtrees by default because structures can be cyclic (which would expand infinitely). The printed form is a safe summary that shows links by identity instead of expanding them.
- If you want the full nested structure, use RD() or RL() to materialize it as a plain Python dict/list. See Materializing to plain Python (RD()/RL()) for details.
- The '@' prefix exists so RD/RL reprs are not confused with normal dict/list reprs: it tells you “this value is persisted on disk.” Without it, RD/RL would look identical to standard Python containers even though they are persisted.
- Star shorthand: If link_field is set and a child RD’s link value equals the dict key it’s under, the summary shows _ as shorthand for “same as the key.” Example: @{'alice': _}. This only affects printing.

#### Printing example:

```python
db["person"] = {"id": "123", "name": "Alice"}
db["task"] = {"owner": db["person"], "status": "waiting"}

print(db["task"])
# -> @{'owner': <UID-like token>, 'status': 'waiting'}  # internal identifier shown unquoted in the summary
# The printed summary shows a compact identifier for nested RD/RL nodes instead of expanding them.
```

#### Printing example with link_field:

- If your dicts include a field that identifies them (e.g., "id"), you can have summaries show that instead of the internal UID. This only affects printing (summaries), not storage.

```python
db = DB("state.db", link_field="id")
db["person"] = {"id": "123", "name": "Alice"}
db["task"] = {"owner": db["person"], "status": "waiting"}

print(db["task"])
# -> @{'owner': 123, 'status': 'waiting'}   # uses 'id' instead of the internal UID (rendered unquoted)
```

- IDs are treated like symbols in printed summaries. When link_field is set, the chosen field is shown unquoted (e.g., alice-42) for readability. This affects display only; storage and types are unchanged. Use RD() or RL() to materialize real Python values.

## Materializing to plain Python (RD()/RL())

- Call an RD or RL object (e.g., obj()) to materialize it into a plain Python dict or list. This is no longer an RD/RL object; it is a standard, in-memory Python datastructure.
- This returns a snapshot: a normal, in‑memory native Python datastructure that is detached from the database. Later DB edits won’t update your materialized copy.
- When printing data in the REPL, the '@' marker is used to distinguish between RD an RL persistent objects and normal dicts and lists.
- When materializing, shared substructures and cycles are preserved. If two parents reference the same child, the materialized dicts/lists share the same Python object. Cycles materialize as self‑referential dicts/lists without infinite recursion.

### Examples

```python
# Summaries vs materialized values
print(db["person"])      # -> starts with '@', summary view
p = db["person"]()       # materialize to plain dict
print(p)                 # -> {'id': '123', ...} (no '@')

# Edit offline and write back once (avoids repeated DB hits)
p["name"] = "Bob"
db["person"] = p
```

```python
# Shared structure preserved
db["x"] = {"child": {"n": 1}}
child = db["x"]["child"]
db["y"] = {"a": child, "b": child}

y = db["y"]()
assert y["a"] is y["b"]  # same Python object

# Cycles preserved (no infinite recursion)
db["a"] = {"name": "A"}
db["b"] = {"name": "B", "friend": db["a"]}
db["a"]["friend"] = db["b"]

a = db["a"]()
assert a["friend"]["friend"] is a  # cycle maintained
```

## Custom prefixes (namespaces)

Etcher automatically picks and remembers a prefix for you; you don’t need to set it.

If you want multiple independent namespaces in the same DB file, set your own:

```python
db1 = DB("state.db", prefix="app1")
db2 = DB("state.db", prefix="app2")

db1["x"] = {"value": 1}
db2["x"] = {"value": 2}

assert db1["x"]["value"] == 1
assert db2["x"]["value"] == 2
```

## Transactions

Use transactions for optimistic concurrency. You can either manage watch/multi/execute yourself or use the auto‑retry helper.

Manual watch/multi/execute

```python
t = db.transactor()
t.watch()          # watch the current keyspace lock
t.multi()          # begin a transaction
t["numbers"] = [1, 2, 3, 4, 5, 6]  # queued changes
t.execute()        # commit; raises WatchError if the keyspace changed
```

Auto‑retry helper

```python
t = db.transactor()

def txn():
    # Read current state through the transactor
    xs = t["numbers"]() if "numbers" in t else []
    t.multi()
    t["numbers"] = xs + [7, 8]

t.transact(txn)    # retries automatically on WatchError
```

## Sharing between processes

- Two or more Python processes can open the same SQLite DB path and share state.
- Many readers are fine; one writer at a time (keep write sections short).

```python
# Process A
db = DB("state.db")
db["counter"] = {"n": 0}

# Process B
db = DB("state.db")
db["counter"]["n"] = db["counter"]["n"] + 1
```

## Backends

- Default: SQLite (fast, durable, zero external services).
- Optional: redislite (embedded), or a real Redis server. Your RD/RL code stays the same; only the backend changes.

```python
# redislite
from redislite import Redis as RLRedis
db = DB("redislite.rdb", redis_adapter=RLRedis)

# real Redis
import redis
r = redis.Redis(host="localhost", port=6379)
db = DB(redis=r)  # use a live Redis client
```

## Maintenance (SQLite)

- Optional housekeeping to compact or optimize the SQLite file.
- Probably not needed for typical use; safe to ignore unless you care about reclaiming disk space.
- Exposed as DB.maintenance() and awaitable DB.maintenance_async().

```python
db.maintenance()          # synchronous; no-op if backend doesn’t support it

import asyncio
asyncio.run(db.maintenance_async())  # async; also a no-op on non-SQLite backends
```

## Notes and limits

- Data model: JSON-style primitives only (strings, numbers, booleans, None, dict, list).
- Transactions: optimistic and optional; great when coordinating writers.
- Prefixes: automatically handled; customize only if you want separate namespaces.
- Repr safety: summaries avoid expanding cycles; call () to materialize when you need full data.
- License: MIT (see LICENSE)
