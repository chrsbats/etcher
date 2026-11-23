# Transactions

Etcher uses Redis-style `WATCH`/`MULTI`/`EXEC` for optimistic concurrency between
cooperating transactors. Use the [auto-retry helper](../README.md#transactions)
or manage the transaction manually. Read inputs through the transactor before
calling `multi()`.

## Manual transactions

```python
from etcher import DB

db = DB("state.db")
t = db.transactor()
t.watch()
numbers = t["numbers"]() if "numbers" in t else []
t.multi()
t["numbers"] = numbers + [7, 8]
t.execute()  # raises WatchError if another transactor updated the watched lock
```

## Conflict detection and queued writes

`watch()` monitors the namespace lock, which transactor execution updates.
Ordinary writes do not update that lock, so all writers whose changes need to
be detected must use the transaction protocol. Transactions do not provide
isolated reads or read-your-writes semantics.

After `multi()`, writes and their reference bookkeeping, including orphan
cleanup, are queued until `execute()`. Abandoning an unexecuted batch leaves
committed data and reference metadata unchanged. `transact()` discards the
queue when its callback raises and retries on `WatchError`. Keep side effects
that should happen only once outside the callback.

## Execution failures

Redis and redislite follow native [`MULTI`/`EXEC` semantics](https://redis.io/docs/latest/develop/using-commands/transactions/):
a command error during execution does not roll back other commands. Once
execution is submitted, an error or lost acknowledgement can mean changes were
applied or the outcome is unknown. A batch that fails before execution is known
not to have written anything. SQLite may provide stronger native rollback, but
Etcher does not guarantee that across backends.
