from pathlib import Path
path = Path(__file__).parent.resolve()
from ulid import ULID
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="redislite")

isa = isinstance
   
from .exceptions import WatchError

sym = '@'

from pprint import pformat


def encode(db, value, parent):
    
    if value is None:
        return '#N'
    if value is True:
        return '#T'
    if value is False:
        return '#F'
    
    if isinstance(value, (RL, RD)): 
        obj_uid = value.uid
        add_ref(db, obj_uid, parent)
        return obj_uid
    
    if isa(value, list):
        new_list = RL(db)
        new_list.extend(value)
        add_ref(db, new_list.uid, parent)
        return new_list.uid
    
    if isa(value, dict):
        new_dict = RD(db)
        encoded_values = {k: encode(db, v, new_dict.uid) for k, v in value.items()}
        if encoded_values:
            db.pipe.hset(new_dict.uid, mapping=encoded_values)
        add_ref(db, new_dict.uid, parent)
        return new_dict.uid
    
    if isa(value, str):
        return '$' + value
    
    return value


def decode(db, value, key=None):

    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8')
    # If it's already a native number or bool, return as-is
    if isinstance(value, (int, float, bool)):
        return value

    try:
        return int(value)
    except:
        try:
            return float(value)
        except:
            if value is None:
                if key is None:
                    raise KeyError()
                else:
                    # Print the original key for debug purposes.
                    raise KeyError(f'Key "{key}" not found')
            # Ensure we’re working with a string for sentinel and UID handling
            value = str(value)

    if value == '#N':
        return None
    if value == '#T':
        return True
    if value == '#F':
        return False

    if value.startswith('$'):
        return value[1:]
    
    dbk = db_key_type(value)
    if dbk == 'D':
        return RD(db, uid=value)
    if dbk == 'L':
        return RL(db, uid=value)
    return value


def evaluate(v):
    mapping = {}

    def walk(node):
        if isa(node, RD):
            uid = node.uid
            if uid in mapping:
                return mapping[uid]
            out = {}
            mapping[uid] = out
            raw = node.db.pipe.hgetall(uid)
            for k_b, v_b in raw.items():
                k = decode(node.db, k_b)
                out[k] = walk(decode(node.db, v_b, k))
            return out
        elif isa(node, RL):
            uid = node.uid
            if uid in mapping:
                return mapping[uid]
            out = []
            mapping[uid] = out
            raw = node.db.pipe.lrange(uid, 0, -1)
            for x_b in raw:
                out.append(walk(decode(node.db, x_b)))
            return out
        return node

    return walk(v)


def is_valid_ulid(value):
    try:
        ULID.from_str(str(value))
        return True
    except ValueError:
        return False


def db_key_type(value):
    if isa(value, bytes):
        value = value.decode('utf-8')
    if isa(value, str):
        if not value:
            return ''
        # Strip prefix
        value = value.split(':')[1:]
        value = ':'.join(value)
        # Look for datastruct
        if value and value[0] in ['D', 'L']:
            if is_valid_ulid(str(value[1:])):
                return value[0]
    return ''

def find_refs(db, key):
    if isa(key, bytes):
        key = key.decode('utf-8')
    dbk = db_key_type(key)
    if dbk == 'D':   
        return db.pipe.hvals(key)
    if dbk == 'L':
        return db.pipe.lrange(key, 0, -1)
    return []


def check_ref(db,ref,root=':root:',visited=None):
    '''
    Do depth first traversal on the backreferences to see if we can reach the root.
    If we can't reach the root, we've been orphaned, which means we can get deleted.
    Note - we only need to do this if theres multiple references to the same object.
    '''

    if visited is None:
        visited = set()
    if ref in visited:
        return False
    visited.add(ref)

    backrefs = db.pipe.hkeys('back:'+ref)
    backrefs = [k.decode('utf-8') for k in backrefs]
    # TODO: there's a potential optimization here for large graphs, but it requires storing by depth of the backrefs, 
    # which might not be worth it in practice.
    #backrefs = sort_refs_by_depth(backrefs)
    for backref in backrefs:
        if backref == root:
            return True
        if check_ref(db,backref,root,visited.copy()):
            return True
    return False



def decr_ref(db, key, parent):
    # Check if the encoded value represents an RD or RL object UID
    if isa(key,bytes):
        key = key.decode('utf-8')
    
    if not db_key_type(key):
        return # Not a reference counted object

    if isa(parent,bytes):
        parent = parent.decode('utf-8')
    
    backref_key = 'back:' + key
    new_count = db.pipe.hincrby(backref_key, parent, -1)

    if new_count <= 0:
        if new_count < 0:
            print('WARNING: A reference count is less than zero')
        db.pipe.hdel(backref_key, parent) 
        is_reachable = check_ref(db, key)                       
        if not is_reachable:
        
            if not db.pipe.exists(key):
                return # Already processed/deleted in this GC cycle
            
            child_references = find_refs(db, key) 

            db.pipe.delete(key,backref_key)             
            
            for child in child_references:
                decr_ref(db, child, key)




def add_ref(db, key, parent):
    '''
    Link a key to the object that references it (the backref).
    We use a counter here in case the parent has multiple links to the same object, 
    such as x = [y,y,y,y]
    '''
    if db_key_type(key):
        db.pipe.hincrby('back:'+key,parent,1)


from copy import copy
from collections import defaultdict

def list_db(db):
    db = db.pipe
    keys = db.keys()
    data = {}
    for key in keys:
        type = db.type(key)
        if type == b"string":
            vals = db.get(key).decode('utf-8')
        if type == b"hash":
            vals = db.hgetall(key)
            vals = {k.decode('utf-8'):v.decode('utf-8') for k,v in vals.items()}
        if type == b"zset":
            vals = db.zrange(key, 0, -1)
        if type == b"list":
            vals = db.lrange(key, 0, -1)
            vals = [x.decode('utf-8') for x in vals]
        if type == b"set":
            vals = db.smembers(key)
        data[key.decode('utf-8')] = vals
    return data

import threading 

class DBConnections:
    def __init__(self):
        self.connections = {}
        self.lock = threading.RLock()

    def connect(self, fname, adapter_cls=None, **kwargs):
        fname = str(fname)
        if adapter_cls is None:
            from etcher.sqlitedis import Redis as DefaultRedis
            adapter_cls = DefaultRedis
        key = (adapter_cls, fname)
        with self.lock:
            inst = self.connections.get(key)
            if inst is None:
                try:
                    inst = adapter_cls(fname, **kwargs)
                except TypeError:
                    # Fallback for adapters that don't take a filename
                    inst = adapter_cls(**kwargs)
                self.connections[key] = inst
            return inst

db_connections = DBConnections()


class DB:
    def __init__(self, db_path=None, prefix=None, link_field='', new_prefix=False, redis=None, redis_adapter=None, redis_kwargs=None):
        if db_path is None:
            db_path = path / 'redis.db'
        self.path = db_path

        # Resolve backend: explicit instance > adapter class > env var > default (redislite)
        if redis is not None:
            self.rdb = redis
        else:
            adapter_cls = redis_adapter
            if adapter_cls is None:
                from etcher.sqlitedis import Redis
                adapter_cls = Redis
            self.rdb = db_connections.connect(str(db_path), adapter_cls=adapter_cls, **(redis_kwargs or {}))


        self.pipe = self.rdb
        self.data = None
        if prefix is not None:
            self.set_prefix(prefix)
        else:
            if new_prefix:
                prefix = self.new_prefix()
            else:
                # Load last used prefix if available; otherwise create a new one
                last = self.pipe.get(':last_prefix:')
                if last is None:
                    prefix = self.new_prefix()
                else:
                    last = last.decode('utf8')
                    prefix = last if self.prefix_in_use(last, include_anchor=True) else self.new_prefix()
                
            self.set_prefix(prefix)
        self.link_field = link_field
        self.transact_mode = False  # For future checks


    @property
    def refcount(self):
        return self.data.refcount
    
    @property
    def backrefs(self):
        return self.data.backrefs

    def delete_prefix_immediately(self, prefix):
        """
        Deletes ALL keys associated with a given prefix IMMEDIATELY using KEYS.
        WARNING: This uses the Redis KEYS command, which can block the server
        and impact performance.
        """
        if not isinstance(prefix, str):
            prefix = str(prefix)
        return self._delete_by_prefix(prefix, limit=None)

    def delete_prefix_batch(self, prefix, count=500):
        """
        Deletes a BATCH of keys associated with a given prefix using SCAN.

        This function is designed to be called repeatedly in a loop until it
        returns False. It uses the non-blocking SCAN command to iteratively
        find and delete keys, making it suitable for large prefixes or
        production environments where blocking is undesirable.

        Deletes data keys (prefix:D..., prefix:L..., prefix:data:) and
        their corresponding backreference keys (back:prefix:D..., back:prefix:L...).

        Args:
            prefix (str or int): The prefix to delete keys for.
            count (int): A hint to Redis for the number of keys to scan per
                         underlying SCAN iteration.

        Returns:
            bool: True if any keys matching the patterns were found and deleted
                  in this call (meaning more *might* exist, so call again),
                  False if no matching keys were found in this call's scan
                  iterations (cleanup for this prefix is likely complete).
        """
        if count is None:
            return self.delete_prefix_immediately(prefix)
        if not isinstance(prefix, str):
            prefix = str(prefix)
        return self._delete_by_prefix(prefix, limit=int(count))

    def shutdown(self):
        try:
            self.pipe.shutdown()
        except Exception:
            pass

    def maintenance(self):
        """
        Optionally perform backend maintenance (SQLite cleanup, etc.).
        No-op if the backend does not support maintenance.
        """
        fn = getattr(self.rdb, "maintenance", None)
        if callable(fn):
            return fn()

    async def maintenance_async(self):
        """
        Coroutine that optionally performs backend maintenance.

        If the backend exposes an async maintenance_async, it will be awaited.
        If it exposes a synchronous callable, it will be called directly.
        No-op if the backend does not support maintenance_async.
        """
        fn = getattr(self.rdb, "maintenance_async", None)
        if callable(fn):
            res = fn()
            if hasattr(res, "__await__"):
                return await res
            return res

    def new_prefix(self):
        x = self.pipe.incr(':dbs:')
        return str(x)

    def get_prefix(self):
        return str(self.pfx[:-1])

    def _norm_prefix(self, p):
        p = str(p)
        return p if p.endswith(':') else (p + ':')

    def _root_key(self, p):
        p = self._norm_prefix(p)
        return f"{p}data:"

    def _back_anchor(self, p):
        return 'back:' + self._root_key(p)

    def _ensure_root_initialized(self, prefix):
        # Ensure the root backref anchor exists and the root hash has a meta type
        back = self._back_anchor(prefix)
        if not self.pipe.hexists(back, ':root:'):
            self.pipe.hset(back, ':root:', 1)
        self.pipe.hset(self._root_key(prefix), mapping={})

    def _collect_keys(self, patterns, limit):
        ks = []
        if limit is None:
            for patt in patterns:
                ks.extend(self.rdb.keys(patt))
        else:
            for patt in patterns:
                for k in self.rdb.scan_iter(match=patt, count=limit):
                    ks.append(k)
                    if len(ks) >= limit:
                        return ks
        return ks

    def _post_delete_housekeeping(self, pfx_str):
        # Clean :last_prefix: if it points to pfx_str and that prefix is no longer in use (ignoring anchor)
        lp = self.rdb.get(':last_prefix:')
        if lp is not None:
            lp_s = lp.decode('utf-8') if isinstance(lp, (bytes, bytearray)) else str(lp)
            if lp_s == pfx_str and not self.prefix_in_use(pfx_str):
                self.rdb.delete(':last_prefix:')
        # Recreate anchor for current prefix only
        if pfx_str == self.get_prefix():
            self.rdb.hset(self._back_anchor(pfx_str), ':root:', 1)

    def _delete_by_prefix(self, prefix, limit):
        p = self._norm_prefix(prefix)
        patterns = [f"{p}*", f"back:{p}*"]
        keys_to_delete = self._collect_keys(patterns, limit)
        if keys_to_delete:
            self.rdb.delete(*keys_to_delete)
            # In immediate mode (limit=None), finalize now if everything is gone
            if limit is None:
                if not self._collect_keys(patterns, limit=1):
                    self._post_delete_housekeeping(p[:-1])  # without trailing ':'
            return True
        # Nothing to delete this pass: finalize and report done
        self._post_delete_housekeeping(p[:-1])  # without trailing ':'
        return False

    def prefix_in_use(self, prefix, include_anchor=False):
        if not isinstance(prefix, str):
            prefix = str(prefix)
        p = self._norm_prefix(prefix)
        root = self._root_key(prefix)
        if self.rdb.exists(root):
            return True
        if include_anchor:
            if self.rdb.exists(self._back_anchor(prefix)) or self.rdb.exists('back:' + self._norm_prefix(prefix)):
                return True
        it = self.rdb.scan_iter(match=f"{p}[DL]*", count=1)
        try:
            next(it)
            return True
        except StopIteration:
            return False

    def set_prefix(self, prefix, require_empty=False):
        if require_empty and self.prefix_in_use(prefix):
            raise ValueError(f"Prefix '{prefix}' is already in use")
        self.pfx = self._norm_prefix(prefix)
        self._ensure_root_initialized(prefix)
        self.data = RD(self, uid=self._root_key(prefix))
        self.pipe.set(':last_prefix:', str(prefix))
            
    # Counters
    def incr(self, key, x=None):
        key = self.pfx + key
        if x is not None:
            return self.pipe.incr(key, x)
        return self.pipe.incr(key)

    def decr(self, key, x=None):
        key = self.pfx + key
        if x is not None:
            return self.pipe.decr(key, x)
        return self.pipe.decr(key)

    def count(self, key):
        key = self.pfx + key
        v = self.pipe.get(key)
        return int(v.decode('utf-8')) if v is not None else 0

    def __getitem__(self, key):
        return self.data[key]

    def get_via_uid(self, uid):
        if isinstance(uid, (bytes, bytearray)):
            uid_s = uid.decode('utf-8')
        else:
            uid_s = str(uid)
        typ = db_key_type(uid_s)
        if typ == 'D':
            return RD(self, uid=uid_s)
        if typ == 'L':
            return RL(self, uid=uid_s)
        raise KeyError(f'Key "{uid_s}" not found or not an RD/RL UID')

    def __setitem__(self, key, value):
        self.data[key] = value

    def __delitem__(self, key):
        del self.data[key]

    def __contains__(self, key):
        return key in self.data

    def __call__(self):
        return self.data()

    def keys(self):
        return self.data.keys()

    def values(self):
        return self.data.values()

    def items(self):
        return self.data.items()

    def __iter__(self):
        yield from self.data

    def transactor(self):
        # Create copy of self but set db to a new pipe.
        db = copy(self)
        pipe = db.rdb.pipeline()
        db.pipe = pipe
        db.transact_mode = True
        return db

    def watch(self):
        self.pipe.watch(self.pfx + '_lock_')

    def multi(self):
        if self.transact_mode:
            self.pipe.multi()
        else:
            raise Exception('Attempted multi while not in trasaction mode')

    def execute(self):
        if self.transact_mode:
            self.pipe.set(self.pfx + '_lock_', str(ULID()))
            self.pipe.execute()
        else:
            raise Exception('Attempted execute while not in trasaction mode')

    def transact(self, transaction_function):
        if self.transact_mode:
            try:
                while True:
                    try:
                        self.watch()
                        transaction_function()
                        self.execute()
                        break
                    except WatchError:
                        continue
            finally:
                self.pipe.reset()
        else:
            raise Exception('Attempted transaction while not in trasaction mode')

    def flush(self):
        for k in self.data:
            del self.data[k]
 
    def __repr__(self):
        return self.data.__repr__()

    def __str__(self):
        return self.__repr__()


class RD:
    '''
    redis dict
    '''
    def __init__(self, db, data=None, uid=None):
        self.db = db
        if uid is None:
            self.uid = self.db.pfx + 'D' + str(ULID())
        else:
            self.uid = uid
        if data:
            self.db.pipe.hset(self.uid, mapping=data)

    @property
    def refcount(self):
        # Number of distinct parents that reference this UID.
        return self.db.pipe.hlen('back:' + self.uid)

    
    @property
    def backrefs(self):
        return {k.decode('utf-8'): int(v) for k,v in self.db.pipe.hgetall('back:'+self.uid).items()}

    def __getitem__(self, key):
        r = self.db.pipe.hget(self.uid, key)
        return decode(self.db, r, key)
    
    def get(self, key, default=None):
        try:
            return self[key]          
        except KeyError:
            return default
        
    def get_via_uid(self, uid):
        return self.db.get_via_uid(uid)
    
    def __setitem__(self, key, value):
        x = encode(self.db, value, self.uid)
        if key in self:
            del self[key]
        self.db.pipe.hset(self.uid, key, x)

    def __delitem__(self, key):
        value = self.db.pipe.hget(self.uid, key)
        decr_ref(self.db, value, self.uid)
        self.db.pipe.hdel(self.uid, key)
        
    def __contains__(self, key):
        return bool(self.db.pipe.hexists(self.uid, key))

    def __len__(self):
        return self.db.pipe.hlen(self.uid)

    def __bool__(self):
        if len(self) > 0:
            return True
        return False

    def __call__(self):
        '''
        Materialize this RD as a plain Python dict. Preserves shared substructures and cycles
        (object identity is maintained). Detached snapshot; further DB edits won't affect it.
        '''
        return evaluate(self)

    def keys(self):
        r = self.db.pipe.hgetall(self.uid)
        r = [decode(self.db, k) for k in r.keys()]
        return r

    def values(self):
        r = self.db.pipe.hgetall(self.uid)
        r = [decode(self.db, v) for v in r.values()]
        return r

    def items(self):
        r = self.db.pipe.hgetall(self.uid)
        r = [(decode(self.db, k), decode(self.db, v)) for k, v in r.items()]
        return r

    def __iter__(self):
        yield from self.keys()

    def _summarize(self, repr_format=True):
        r = self.db.pipe.hgetall(self.uid)
        r = {decode(self.db, k): decode(self.db, v) for k, v in r.items()}
        summary = {}
        for k, v in r.items():
            if isa(v, RD):
                data = None
                if self.db.link_field and self.db.link_field in v:
                    link = v[self.db.link_field]
                else:
                    link = v.uid

                if repr_format:
                    if link != k:
                        data = '##' + str(link) + '##'
                    else:
                        data = '####'
                else:
                    data = str(link)
                if data is None:
                    data = v
                summary[k] = data
            else:
                summary[k] = v
        return summary

    def __repr__(self):
        summary = self._summarize()
        rep = pformat(summary, sort_dicts=False, indent=2, width=120)
        rep = rep.replace("'####'", '*')
        rep = rep.replace("'##", '').replace("##'", '')
        return sym + rep

    def __str__(self):
        return self.__repr__()

    def __eq__(self, other):
        if isinstance(other, RD):
            return self.uid == other.uid  # Compare by identity (UID)
        elif isinstance(other, dict):
            return self() == other  # Compare by content
        return NotImplemented

class RL:
    '''
    redis list
    '''
    def __init__(self, db, data=None, uid=None):
        self.db = db
        if uid is None:
            self.uid = self.db.pfx + 'L' + str(ULID())
        else:
            self.uid = uid
        if data:
            self.extend(data)

    @property
    def refcount(self):
        # Number of distinct parents that reference this UID.
        return self.db.pipe.hlen('back:' + self.uid)
    
    @property
    def backrefs(self):
        return {k.decode('utf-8'): int(v) for k, v in self.db.pipe.hgetall('back:'+self.uid).items()}
    
    def __getitem__(self, key):

        if isa(key, slice):
            start = 0 if key.start is None else key.start
            stop_inclusive = -1 if key.stop is None else (key.stop - 1)
            r = self.db.pipe.lrange(self.uid, start, stop_inclusive)
            # If we create RL instance here, it will create an orphan
            r = [decode(self.db, x) for x in r]
            return r
        r = self.db.pipe.lindex(self.uid, key)
        return decode(self.db, r)


    def __setitem__(self, key, value):
        x = encode(self.db, value, self.uid)
        decr_ref(self.db, self.db.pipe.lindex(self.uid, key), self.uid)
        self.db.pipe.lset(self.uid, key, x)

    def __len__(self):
        return self.db.pipe.llen(self.uid)

    def append(self, value):
        self.db.pipe.rpush(self.uid, encode(self.db, value, self.uid))

    def extend(self, values):
        values = [encode(self.db, v, self.uid) for v in values]
        # TODO: Weird redislite bug stopping me sending *values
        for v in values:
            self.db.pipe.rpush(self.uid, v)

    def __bool__(self):
        if len(self) > 0:
            return True
        return False

    def __add__(self, x):
        r = self.db.pipe.lrange(self.uid, 0, -1)
        r = [decode(self.db, x) for x in r] + x
        return r

    def __iter__(self):
        r = self.db.pipe.lrange(self.uid, 0, -1)
        r = [decode(self.db, x) for x in r]
        yield from r

    def __call__(self):
        '''
        Materialize this RL as a plain Python list. Preserves shared substructures and cycles
        (object identity is maintained). Detached snapshot; further DB edits won't affect it.
        '''
        return evaluate(self)

    def __contains__(self, key):
        # Serializes self and then calls __contain__ on the list
        if key in self():
            return True
        return False

    def _summary(self):
        r = self.db.pipe.lrange(self.uid, 0, -1)
        r = [decode(self.db, x) for x in r]
        return r

    def __repr__(self):
        r = self._summary()
        return sym + pformat(r)

    def __str__(self):
        return self.__repr__()

    def __eq__(self, other):
        if isinstance(other, RL):
            return self.uid == other.uid  # Compare by identity (UID)
        elif isinstance(other, list):
            return self() == other  # Compare by content
        return NotImplemented
