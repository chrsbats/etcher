Performance notes for etcher (scenegraph editing)

Overview
- For single-process workloads that edit large nested dict/list structures, the SQLite-backed adapter (sqlitedis) is typically fast enough while providing durability.
- Your test suite completes quickly, which is a good proxy for the expected interactive editing speed.

What we optimized already
- WAL mode and synchronous=NORMAL to reduce fsync cost while keeping good durability.
- mmap for faster reads.
- Atomic counters (hincrby) implemented as a single write per increment within a transaction context.
- Hash housekeeping: we remove empty hashes from meta so keys() stays lean.

New tuning in this repo
- PRAGMA busy_timeout=5000 is enabled to reduce transient “database is locked” errors under short bursts of parallel work.

Tips to keep it fast
- Batch edits: Use DB.transactor() to group multiple updates into one transaction (fewer commits = fewer fsyncs).
- For many edits to a single object, materialize once (x = db["k"]()), modify in memory, then assign back once (db["k"] = x) to reduce DB churn.
- Prefer structural reuse: When possible, reuse existing RD/RL nodes to avoid creating/deleting many small objects.
- Avoid unnecessary materialization: Only call RD()/RL() when you truly need full Python structures; otherwise access fields/indices directly.
- Keep transactions small: Many short transactions are usually better than one massive one.

When to consider another backend
- If you need very high write concurrency across multiple processes or sustained 100k+ increments per second, use a networked Redis or a write-optimized KV store. The adapter mechanism lets you swap backends easily.

Measuring locally
- Use pytest -q to verify correctness and get a feel for end-to-end performance.
- Add targeted benchmarks around your critical edit paths if needed (pytest-benchmark is already present).

Configuration knobs (advanced)
- journal_mode=WAL, synchronous=NORMAL (default here): good durability and speed balance.
- synchronous=OFF (not recommended for most uses): faster, reduced crash durability.
- Busy timeout: increased to 5s to reduce “database is locked” errors during short lock contention.
- Cache size: consider PRAGMA cache_size=-20000 (approx 20MB) if your workload benefits from more page cache.
Reference counting semantics:
RD.refcount and RL.refcount report the number of distinct parent objects referencing an item. This is implemented as HLEN on back:<uid>. The hash values are per-parent counters to handle duplicate references (e.g., a list containing the same child multiple times). When a counter reaches zero it is deleted, so HLEN accurately reflects the number of parents.
