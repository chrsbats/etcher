# Etcher

[![PyPI](https://img.shields.io/pypi/v/etcher.svg)](https://pypi.org/project/etcher/)
[![Python](https://img.shields.io/pypi/pyversions/etcher.svg)](https://pypi.org/project/etcher/)
[![Build](https://github.com/chrsbats/etcher/actions/workflows/ci.yml/badge.svg)](https://github.com/chrsbats/etcher/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-90%25%2B-brightgreen)](https://github.com/chrsbats/etcher/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Persistent Python dicts and lists for JSON-style data that behave like ordinary Python data structures. No schema, no separate database server, no explicit loading or saving.

Etcher is designed for local database access, particularly for applications and background workers that need to share persistent state.

## Install

```sh
pip install etcher
```

## Quick start

```python
from etcher import DB

db = DB("state.db")
db["person"] = {"name": "Alice", "tags": ["a"]}
db["person"]["tags"].append("b")
assert db["person"]["tags"][1] == "b"
```

## Persistent containers and references

`RD` and `RL` are live, persistent versions of Python dicts and lists. Assigning a
plain dict or list creates persistent containers; assigning an existing `RD` or
`RL` from the same namespace stores a reference instead of making a deep copy.

```python
person = db["person"]
db["task"] = {"owner": person, "reviewer": person}
person["name"] = "Bob"
assert db["task"]["owner"]["name"] == "Bob"
```

Printed summaries start with `@` (for example, `@['a', 'b']`) to distinguish
persistent containers from plain Python values. Nested links are shown by
identifier rather than expanded.

## Materializing to plain Python

Call a persistent container to get a detached, in-memory dict or list. Changes
to the snapshot don't affect the database unless you write it back. A snapshot
preserves shared references and cycles within the materialized structure.

```python
task = db["task"]()
assert task["owner"] is task["reviewer"]
```

## Sharing between processes

Different Python processes can open the same SQLite file to share state. SQLite
supports concurrent readers and one writer at a time; keep writes short.

```python
# Process A
from etcher import DB

db = DB("shared.db")
db["ready"] = True
```

```python
# Process B, after A has written
from etcher import DB

db = DB("shared.db")
assert db["ready"] is True
```

Etcher remembers the last-used prefix. To keep multiple namespaces in one file,
specify the prefix explicitly, for example `DB("shared.db", prefix="app1")`.
Processes sharing a namespace should use the same prefix.

## Transactions

Use `transact()` for optimistic read-modify-write with cooperating writers. Read
through the transactor before `multi()`; the callback may run more than once.

```python
t = db.transactor()

def append_numbers():
    numbers = t["numbers"]() if "numbers" in t else []
    t.multi()
    t["numbers"] = numbers + [7, 8]

t.transact(append_numbers)
```

**Transaction limits:** Ordinary writes bypass conflict detection. Transactions
do not guarantee isolated reads, read-your-writes, or rollback on execution
failure. See [Transactions](docs/transactions.md) for details.

## Backends

- **SQLite** (default): local, durable storage with no extra dependencies or services.
- **redislite** (`pip install 'etcher[redislite]'`): embedded Redis.
- **Redis** (`pip install 'etcher[redis]'`): pass a Redis client to `DB(redis=client)`.

The container API is the same across backends, but fine-grained operations are
sensitive to network latency with a remote Redis server.

## Documentation

- [Container identity, printing, and cycles](docs/containers.md)
- [Transactions and failure guarantees](docs/transactions.md)
- [Backend setup, reopening, and SQLite maintenance](docs/backends.md)
- [Performance notes](docs/performance.md)
