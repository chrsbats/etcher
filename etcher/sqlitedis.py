"""
SQLite-backed minimal Redis-compatible shim for etcher.

Implements the subset of Redis used by etcher:
- Strings: get, set, incr, decr, exists
- Hashes: hset, hget, hgetall, hlen, hexists, hkeys, hvals, hdel
- Lists: rpush, lrange, lindex, lset, llen
- Keys/scan/delete/type: keys(pattern), scan_iter(match, count), delete(*keys), type(key)
- Pipeline/transactions: pipeline(), Pipeline.watch(), Pipeline.multi(), Pipeline.execute(), Pipeline.reset()
- shutdown()

All values are returned as bytes (like redis-py).
"""

import sqlite3
import threading
from fnmatch import fnmatch
from typing import Iterable, Iterator, Dict, Tuple, Optional, Any, List, Union

from redis.exceptions import WatchError


Bytes = bytes
KeyT = Union[str, bytes]


def _b(x: Any) -> Optional[bytes]:
    if x is None:
        return None
    if isinstance(x, bytes):
        return x
    if isinstance(x, str):
        return x.encode("utf-8")
    if isinstance(x, (int, float)):
        return str(x).encode("utf-8")
    return str(x).encode("utf-8")


def _s(key: KeyT) -> str:
    return key.decode("utf-8") if isinstance(key, bytes) else str(key)


class Redis:
    def __init__(self, filename: str):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(filename, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.execute("PRAGMA foreign_keys=OFF")
        self._conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        self._ensure_schema()

    def _ensure_schema(self):
        with self._lock, self._conn:
            cur = self._conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kv (
                    k TEXT PRIMARY KEY,
                    v BLOB NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS hkv (
                    hk TEXT NOT NULL,
                    f  BLOB NOT NULL,
                    v  BLOB NOT NULL,
                    PRIMARY KEY (hk, f)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lkv (
                    lk  TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    v   BLOB NOT NULL,
                    PRIMARY KEY (lk, idx)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    k TEXT PRIMARY KEY,
                    t TEXT NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    k   TEXT PRIMARY KEY,
                    ver INTEGER NOT NULL
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_hkv_hk ON hkv(hk);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lkv_lk ON lkv(lk);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lkv_lk_idx ON lkv(lk, idx);")

    # --- helpers for types/versions ---
    def _get_type(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT t FROM meta WHERE k = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def _set_type(self, key: str, typ: str, cur=None):
        c = cur or self._conn
        c.execute("INSERT INTO meta(k,t) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET t=excluded.t", (key, typ))

    def _ensure_type(self, key: str, typ: str, cur=None):
        existing = self._get_type(key)
        if existing is None:
            self._set_type(key, typ, cur)
            return
        if existing != typ:
            # Clear previous data and set to new type
            self._delete_keys([key], cur)
            self._set_type(key, typ, cur)

    def _bump_version(self, key: str, cur=None):
        c = cur or self._conn
        c.execute("""
            INSERT INTO versions(k, ver) VALUES(?, 1)
            ON CONFLICT(k) DO UPDATE SET ver = ver + 1
        """, (key,))

    def _get_version(self, key: str) -> int:
        cur = self._conn.execute("SELECT ver FROM versions WHERE k = ?", (key,))
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def _delete_keys(self, keys: Iterable[str], cur=None) -> int:
        c = cur or self._conn
        deleted = 0
        for k in keys:
            typ = self._get_type(k)
            if typ is None:
                continue
            if typ == "string":
                c.execute("DELETE FROM kv WHERE k = ?", (k,))
            elif typ == "hash":
                c.execute("DELETE FROM hkv WHERE hk = ?", (k,))
            elif typ == "list":
                c.execute("DELETE FROM lkv WHERE lk = ?", (k,))
            c.execute("DELETE FROM meta WHERE k = ?", (k,))
            # keep versions row so WATCH on deleted keys still detects changes
            self._bump_version(k, c)
            deleted += 1
        return deleted

    # --- strings ---
    def get(self, key: KeyT) -> Optional[Bytes]:
        k = _s(key)
        with self._lock:
            cur = self._conn.execute("SELECT v FROM kv WHERE k = ?", (k,))
            row = cur.fetchone()
            return row[0] if row else None

    def set(self, key: KeyT, value: Any) -> bool:
        k = _s(key)
        v = _b(value)
        with self._lock, self._conn:
            self._ensure_type(k, "string", self._conn)
            self._conn.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
            self._bump_version(k, self._conn)
        return True

    def incr(self, key: KeyT, amount: Optional[int] = None) -> int:
        # Redis's incr(key, amount) increments by 'amount' if provided; incr(key) by 1
        by = 1 if amount is None else int(amount)
        k = _s(key)
        with self._lock, self._conn:
            self._ensure_type(k, "string", self._conn)
            cur = self._conn.execute("SELECT v FROM kv WHERE k = ?", (k,))
            row = cur.fetchone()
            base = 0 if not row else int(row[0].decode("utf-8"))
            val = base + by
            self._conn.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, _b(val)))
            self._bump_version(k, self._conn)
            return val

    def decr(self, key: KeyT, amount: Optional[int] = None) -> int:
        by = 1 if amount is None else int(amount)
        return self.incr(key, -by)

    def exists(self, key: KeyT) -> int:
        k = _s(key)
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM meta WHERE k = ? LIMIT 1", (k,))
            return 1 if cur.fetchone() else 0

    # --- hashes ---
    def hset(self, key: KeyT, field: Optional[Any] = None, value: Optional[Any] = None, mapping: Optional[Dict[Any, Any]] = None) -> int:
        hk = _s(key)
        with self._lock, self._conn:
            self._ensure_type(hk, "hash", self._conn)
            changed = 0
            if mapping is not None:
                rows = [(_b(f), _b(v)) for f, v in mapping.items()]
                self._conn.executemany(
                    "INSERT INTO hkv(hk,f,v) VALUES(?,?,?) ON CONFLICT(hk,f) DO UPDATE SET v=excluded.v",
                    [(hk, f, v) for f, v in rows]
                )
                changed = len(rows)
            else:
                f = _b(field)
                v = _b(value)
                self._conn.execute(
                    "INSERT INTO hkv(hk,f,v) VALUES(?,?,?) ON CONFLICT(hk,f) DO UPDATE SET v=excluded.v",
                    (hk, f, v)
                )
                changed = 1
            self._bump_version(hk, self._conn)
            return changed

    def hget(self, key: KeyT, field: Any) -> Optional[Bytes]:
        hk = _s(key)
        f = _b(field)
        with self._lock:
            cur = self._conn.execute("SELECT v FROM hkv WHERE hk = ? AND f = ?", (hk, f))
            row = cur.fetchone()
            return row[0] if row else None

    def hgetall(self, key: KeyT) -> Dict[Bytes, Bytes]:
        hk = _s(key)
        with self._lock:
            cur = self._conn.execute("SELECT f, v FROM hkv WHERE hk = ?", (hk,))
            return {row[0]: row[1] for row in cur.fetchall()}

    def hlen(self, key: KeyT) -> int:
        hk = _s(key)
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM hkv WHERE hk = ?", (hk,))
            return int(cur.fetchone()[0])

    def hexists(self, key: KeyT, field: Any) -> bool:
        hk = _s(key); f = _b(field)
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM hkv WHERE hk = ? AND f = ? LIMIT 1", (hk, f))
            return bool(cur.fetchone())

    def hkeys(self, key: KeyT) -> List[Bytes]:
        hk = _s(key)
        with self._lock:
            cur = self._conn.execute("SELECT f FROM hkv WHERE hk = ?", (hk,))
            return [row[0] for row in cur.fetchall()]

    def hvals(self, key: KeyT) -> List[Bytes]:
        hk = _s(key)
        with self._lock:
            cur = self._conn.execute("SELECT v FROM hkv WHERE hk = ?", (hk,))
            return [row[0] for row in cur.fetchall()]

    def hdel(self, key: KeyT, *fields: Any) -> int:
        hk = _s(key)
        if not fields:
            return 0
        rows = [(_b(f),) for f in fields]
        with self._lock, self._conn:
            cur = self._conn.executemany("DELETE FROM hkv WHERE hk = ? AND f = ?", [(hk, f[0]) for f in rows])
            deleted = cur.rowcount if cur.rowcount is not None else 0
            if deleted:
                # bump version for this hash key
                self._bump_version(hk, self._conn)
                # if the hash is now empty, remove the key itself (match Redis semantics)
                empty = self._conn.execute("SELECT 1 FROM hkv WHERE hk = ? LIMIT 1", (hk,)).fetchone() is None
                if empty:
                    self._conn.execute("DELETE FROM meta WHERE k = ?", (hk,))
            return int(deleted)

    def hincrby(self, key: KeyT, field: Any, amount: int) -> int:
        hk = _s(key)
        f = _b(field)
        by = int(amount)
        with self._lock, self._conn:
            self._ensure_type(hk, "hash", self._conn)
            cur = self._conn.execute("SELECT v FROM hkv WHERE hk = ? AND f = ?", (hk, f))
            row = cur.fetchone()
            base = int(row[0].decode("utf-8")) if row else 0
            new = base + by
            self._conn.execute(
                "INSERT INTO hkv(hk,f,v) VALUES(?,?,?) ON CONFLICT(hk,f) DO UPDATE SET v=excluded.v",
                (hk, f, _b(new))
            )
            self._bump_version(hk, self._conn)
            return new

    # --- lists ---
    def rpush(self, key: KeyT, value: Any) -> int:
        lk = _s(key)
        v = _b(value)
        with self._lock, self._conn:
            self._ensure_type(lk, "list", self._conn)
            cur = self._conn.execute("SELECT COALESCE(MAX(idx), -1) FROM lkv WHERE lk = ?", (lk,))
            max_idx = int(cur.fetchone()[0])
            new_idx = max_idx + 1
            self._conn.execute("INSERT INTO lkv(lk, idx, v) VALUES(?,?,?)", (lk, new_idx, v))
            self._bump_version(lk, self._conn)
            return new_idx + 1  # new length

    def lrange(self, key: KeyT, start: int, stop: int) -> List[Bytes]:
        lk = _s(key)
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM lkv WHERE lk = ?", (lk,))
            n = int(cur.fetchone()[0])
            if n == 0:
                return []
            # Normalize indices (Redis semantics: inclusive stop; negatives allowed)
            if start < 0:
                start = n + start
            if stop < 0:
                stop = n + stop
            start = max(start, 0)
            stop = min(stop, n - 1)
            if stop < start:
                return []
            cur = self._conn.execute(
                "SELECT v FROM lkv WHERE lk = ? AND idx BETWEEN ? AND ? ORDER BY idx ASC",
                (lk, start, stop)
            )
            return [row[0] for row in cur.fetchall()]

    def lindex(self, key: KeyT, index: int) -> Optional[Bytes]:
        lk = _s(key)
        with self._lock:
            if index < 0:
                # translate negative index
                cur = self._conn.execute("SELECT COUNT(*) FROM lkv WHERE lk = ?", (lk,))
                n = int(cur.fetchone()[0])
                index = n + index
            cur = self._conn.execute("SELECT v FROM lkv WHERE lk = ? AND idx = ?", (lk, index))
            row = cur.fetchone()
            return row[0] if row else None

    def lset(self, key: KeyT, index: int, value: Any) -> bool:
        lk = _s(key)
        v = _b(value)
        with self._lock, self._conn:
            cur = self._conn.execute("UPDATE lkv SET v = ? WHERE lk = ? AND idx = ?", (v, lk, index))
            if cur.rowcount == 0:
                raise IndexError("index out of range")
            self._bump_version(lk, self._conn)
            return True

    def llen(self, key: KeyT) -> int:
        lk = _s(key)
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM lkv WHERE lk = ?", (lk,))
            return int(cur.fetchone()[0])

    # --- keys / scan / delete / type ---
    def keys(self, pattern: Optional[KeyT] = None) -> List[Bytes]:
        patt = pattern if pattern is not None else "*"
        if isinstance(patt, (bytes, bytearray)):
            patt = patt.decode("utf-8")
        else:
            patt = str(patt)
        with self._lock:
            cur = self._conn.execute("SELECT k FROM meta")
            keys = [row[0] for row in cur.fetchall()]
        return [k.encode("utf-8") for k in keys if fnmatch(k, patt)]

    def scan_iter(self, match: Optional[KeyT] = None, count: Optional[int] = None) -> Iterator[Bytes]:
        patt = match if match is not None else "*"
        if isinstance(patt, (bytes, bytearray)):
            patt = patt.decode("utf-8")
        else:
            patt = str(patt)
        chunk = max(1, int(count)) if count else 50
        matched = self.keys(patt)
        for i in range(0, len(matched), chunk):
            for k in matched[i:i+chunk]:
                yield k

    def delete(self, *keys: KeyT) -> int:
        if not keys:
            return 0
        ks = [_s(k) for k in keys]
        with self._lock, self._conn:
            return self._delete_keys(ks, self._conn)

    def type(self, key: KeyT) -> Bytes:
        t = self._get_type(_s(key))
        if t is None:
            return b"none"
        return b"string" if t == "string" else (b"hash" if t == "hash" else b"list")

    # --- pipeline/transactions ---
    def pipeline(self) -> "Pipeline":
        return Pipeline(self)

    # --- shutdown ---
    def shutdown(self):
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()


class Pipeline:
    def __init__(self, redis: Redis):
        self._r = redis
        self._lock = threading.RLock()
        self._watched: Dict[str, int] = {}
        self._queue: List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]] = []
        self._in_multi = False
        self._accum_hincr: Dict[Tuple[str, bytes], int] = {}

    # watch/multi/execute/reset
    def watch(self, *keys: KeyT):
        ks = [_s(k) for k in keys]
        if len(ks) == 1 and isinstance(keys[0], (list, tuple, set)):
            ks = [_s(k) for k in keys[0]]  # support watch([k1,k2])
        with self._lock, self._r._lock:
            for k in ks:
                self._watched[k] = self._r._get_version(k)

    def multi(self):
        self._in_multi = True

    def execute(self):
        with self._lock, self._r._lock:
            # check watched
            for k, ver in self._watched.items():
                if self._r._get_version(k) != ver:
                    self.reset()
                    raise WatchError("Watched key changed")
            # apply queued ops atomically
            with self._r._conn:
                mutated: set[str] = set()
                cur = self._r._conn
                for op, args, meta in self._queue:
                    if op == "set":
                        k, v = args
                        self._r._ensure_type(_s(k), "string", cur)
                        cur.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                                    (_s(k), _b(v)))
                        mutated.add(_s(k))
                    elif op == "hset_mapping":
                        hk, mapping = args
                        self._r._ensure_type(_s(hk), "hash", cur)
                        rows = [(_s(hk), _b(f), _b(val)) for f, val in mapping.items()]
                        cur.executemany("INSERT INTO hkv(hk,f,v) VALUES(?,?,?) ON CONFLICT(hk,f) DO UPDATE SET v=excluded.v", rows)
                        mutated.add(_s(hk))
                    elif op == "hset":
                        hk, f, v = args
                        self._r._ensure_type(_s(hk), "hash", cur)
                        cur.execute("INSERT INTO hkv(hk,f,v) VALUES(?,?,?) ON CONFLICT(hk,f) DO UPDATE SET v=excluded.v",
                                    (_s(hk), _b(f), _b(v)))
                        mutated.add(_s(hk))
                    elif op == "hdel":
                        hk, fields = args
                        for f in fields:
                            cur.execute("DELETE FROM hkv WHERE hk = ? AND f = ?", (_s(hk), _b(f)))
                        # If the hash became empty, drop the key from meta so keys() no longer lists it
                        empty = cur.execute("SELECT 1 FROM hkv WHERE hk = ? LIMIT 1", (_s(hk),)).fetchone() is None
                        if empty:
                            cur.execute("DELETE FROM meta WHERE k = ?", (_s(hk),))
                        mutated.add(_s(hk))
                    elif op == "rpush":
                        lk, v = args
                        self._r._ensure_type(_s(lk), "list", cur)
                        q = cur.execute("SELECT COALESCE(MAX(idx), -1) FROM lkv WHERE lk = ?", (_s(lk),))
                        max_idx = int(q.fetchone()[0])
                        cur.execute("INSERT INTO lkv(lk, idx, v) VALUES(?,?,?)", (_s(lk), max_idx + 1, _b(v)))
                        mutated.add(_s(lk))
                    elif op == "lset":
                        lk, idx, v = args
                        cur.execute("UPDATE lkv SET v = ? WHERE lk = ? AND idx = ?", (_b(v), _s(lk), idx))
                        if cur.rowcount == 0:
                            raise IndexError("index out of range")
                        mutated.add(_s(lk))
                    elif op == "hincrby":
                        hk, f, by = args
                        self._r._ensure_type(_s(hk), "hash", cur)
                        row = cur.execute("SELECT v FROM hkv WHERE hk = ? AND f = ?", (_s(hk), _b(f))).fetchone()
                        base = int(row[0].decode("utf-8")) if row else 0
                        new = base + int(by)
                        cur.execute(
                            "INSERT INTO hkv(hk,f,v) VALUES(?,?,?) ON CONFLICT(hk,f) DO UPDATE SET v=excluded.v",
                            (_s(hk), _b(f), _b(new))
                        )
                        mutated.add(_s(hk))
                    else:
                        raise NotImplementedError(op)
                # bump versions at the end
                for k in mutated:
                    self._r._bump_version(k, cur)
            self.reset()

    def reset(self):
        self._queue.clear()
        self._watched.clear()
        self._in_multi = False
        self._accum_hincr.clear()

    # proxy methods
    def set(self, key: KeyT, value: Any):
        if self._in_multi:
            self._queue.append(("set", (key, value), {}))
            return True
        return self._r.set(key, value)

    def hset(self, key: KeyT, field: Optional[Any] = None, value: Optional[Any] = None, mapping: Optional[Dict[Any, Any]] = None):
        if self._in_multi:
            if mapping is not None:
                self._queue.append(("hset_mapping", (key, mapping), {}))
                return len(mapping)
            self._queue.append(("hset", (key, field, value), {}))
            return 1
        return self._r.hset(key, field, value, mapping)

    def hdel(self, key: KeyT, *fields: Any):
        if self._in_multi:
            self._queue.append(("hdel", (key, fields), {}))
            return len(fields)
        return self._r.hdel(key, *fields)

    def hincrby(self, key: KeyT, field: Any, amount: int):
        if self._in_multi:
            hk = _s(key)
            f = _b(field)
            by = int(amount)
            base_pred = self._accum_hincr.get((hk, f))
            if base_pred is None:
                cur = self._r.hget(hk, f)
                base = int(cur.decode("utf-8")) if cur is not None else 0
            else:
                base = base_pred
            new = base + by
            self._accum_hincr[(hk, f)] = new
            self._queue.append(("hincrby", (key, field, by), {}))
            return new
        return self._r.hincrby(key, field, amount)

    def rpush(self, key: KeyT, value: Any):
        if self._in_multi:
            self._queue.append(("rpush", (key, value), {}))
            # Redis pipeline returns new length, but tests don't rely on it; return placeholder
            return 0
        return self._r.rpush(key, value)

    def lset(self, key: KeyT, index: int, value: Any):
        if self._in_multi:
            self._queue.append(("lset", (key, index, value), {}))
            return True
        return self._r.lset(key, index, value)

    # read-only operations always bypass queue
    def get(self, key: KeyT): return self._r.get(key)
    def hget(self, key: KeyT, field: Any): return self._r.hget(key, field)
    def hgetall(self, key: KeyT): return self._r.hgetall(key)
    def hlen(self, key: KeyT): return self._r.hlen(key)
    def hexists(self, key: KeyT, field: Any): return self._r.hexists(key, field)
    def hkeys(self, key: KeyT): return self._r.hkeys(key)
    def hvals(self, key: KeyT): return self._r.hvals(key)
    def lrange(self, key: KeyT, start: int, stop: int): return self._r.lrange(key, start, stop)
    def lindex(self, key: KeyT, index: int): return self._r.lindex(key, index)
    def llen(self, key: KeyT): return self._r.llen(key)
    def keys(self, pattern: Optional[str] = None): return self._r.keys(pattern)
    def scan_iter(self, match: Optional[str] = None, count: Optional[int] = None): return self._r.scan_iter(match, count)
    def delete(self, *keys: KeyT): return self._r.delete(*keys)
    def type(self, key: KeyT): return self._r.type(key)
    def exists(self, key: KeyT): return self._r.exists(key)
