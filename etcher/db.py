from inspect import getsourcefile
from pathlib import Path, PurePath
path = Path.absolute(PurePath(getsourcefile(lambda: 0)).parent)
from ulid import ULID
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="redislite")
from redislite import Redis

isa = isinstance

class DBFileRedis(Redis):
    pass
   
from redis import WatchError, ResponseError

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
            value = value.decode('utf-8')

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
    
    def walk(v):
        if isa(v, RD):
            if v.uid in mapping:
                return mapping[v.uid]
            # Create a pointer
            mapping[v.uid] = {}
            d = v.db.pipe.hgetall(v.uid)
            d = {decode(v.db, k): walk(decode(v.db, x, k)) for k, x in d.items()}
            # Fill the pointer with data
            for k,val in d.items():
                mapping[v.uid][k] = val
            return d
        elif isa(v, RL):
            if v.uid in mapping:
                return mapping[v.uid]
            # Create a pointer
            mapping[v.uid] = []
            d = v.db.pipe.lrange(v.uid, 0, -1)
            d = [walk(decode(v.db, x)) for x in d]
            # Fill the pointer with data
            mapping[v.uid].extend(d)
            return d
        return v
    
    v = walk(v)
    return v


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

    connections = defaultdict(lambda: None)

    def connect(self, fname) -> Redis:
        fname = str(fname)

        self.lock = threading.RLock()
        with self.lock:
            if not self.connections[fname]:          
                self.connections[fname] = DBFileRedis(fname)
        return self.connections[fname]

db_connections = DBConnections()


class DB:
    def __init__(self, db_path=None, prefix=None, link_field='', new_prefix=False):
        if db_path is None:
            db_path = path / 'redis.db'
        self.path = db_path
        self.rdb = db_connections.connect(str(db_path))
        self.pubsub = self.rdb.pubsub(ignore_subscribe_messages=True)
        self.pipe = self.rdb
        self.data = None
        if prefix is not None:
            self.set_prefix(prefix)
        else:
            if new_prefix:
                prefix = self.new_prefix()
            else:
                # Load the last prefix used
                prefix = self.pipe.get(':dbs:')
                if prefix is None:
                    prefix = self.new_prefix()
                else:
                    prefix = prefix.decode('utf8')
                
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
        if not prefix.endswith(':'):
            prefix += ':'

        all_keys_to_delete = []
        root_data_key = f"{prefix}data:"

        # --- Find data keys using KEYS ---
        data_pattern = f"{prefix}[DL]*"
        data_keys = self.rdb.keys(data_pattern) # Blocking call!

        # Determine expected type (usually bytes)
        key_type_example = type(data_keys[0]) if data_keys else bytes
        root_data_key_typed = root_data_key.encode('utf-8') if key_type_example is bytes else root_data_key

        if self.rdb.exists(root_data_key):
             if root_data_key_typed not in data_keys:
                data_keys.append(root_data_key_typed)

        for key in data_keys:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            if db_key_type(key_str) in ['D', 'L'] or key_str == root_data_key:
                all_keys_to_delete.append(key) # Appends bytes or potentially the str root key

        # --- Find backreference keys using KEYS ---
        backref_pattern = f"back:{prefix}[DL]*"
        backref_keys = self.rdb.keys(backref_pattern) # Blocking call!
        for key in backref_keys:
            original_key_ref = key[5:]
            if db_key_type(original_key_ref) in ['D', 'L']:
                all_keys_to_delete.append(key) # Appends bytes

        # --- Perform deletion ---
        deleted_count = 0
        if all_keys_to_delete:
            # No need for type homogenization - redis-py handles mixed bytes/str
            deleted_count = self.rdb.delete(*all_keys_to_delete)

        return deleted_count > 0

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
        if not prefix.endswith(':'):
            prefix += ':'

        deleted_in_call = 0
        keys_to_delete_batch = []
        root_data_key = f"{prefix}data:"

        # --- Scan and collect data keys ---
        data_pattern = f"{prefix}[DL]*"
        found_data_keys = False
        for key in self.rdb.scan_iter(match=data_pattern, count=count): # Iterates keys matching pattern
            found_data_keys = True
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            # *** TYPE CHECK 1: Ensure scanned key is D or L type ***
            if db_key_type(key_str) in ['D', 'L']:
                 keys_to_delete_batch.append(key)

        # Determine expected type for root key handling
        key_type_example = type(keys_to_delete_batch[0]) if keys_to_delete_batch else (type(key) if 'key' in locals() and found_data_keys else bytes) # Default to bytes
        root_data_key_typed = root_data_key.encode('utf-8') if key_type_example is bytes else root_data_key

        # *** EXPLICIT CHECK 2: Handle the root data key ***
        if self.rdb.exists(root_data_key):
             if root_data_key_typed not in keys_to_delete_batch:
                 keys_to_delete_batch.append(root_data_key_typed)

        # --- Delete collected data keys ---
        if keys_to_delete_batch:
            deleted_count = self.rdb.delete(*keys_to_delete_batch)
            deleted_in_call += deleted_count
            keys_to_delete_batch = [] # Reset

        # --- Scan and collect backreference keys ---
        backref_pattern = f"back:{prefix}[DL]*"
        for key in self.rdb.scan_iter(match=backref_pattern, count=count): # Iterates backref keys matching pattern
            original_key_ref = key[5:] # Get the key the backref points TO
            # *** TYPE CHECK 3: Ensure backref points to a D or L key ***
            if db_key_type(original_key_ref) in ['D', 'L']:
                 keys_to_delete_batch.append(key) # Add the BACKREF key itself

        # --- Delete collected backreference keys ---
        if keys_to_delete_batch:
            deleted_count = self.rdb.delete(*keys_to_delete_batch)
            deleted_in_call += deleted_count

        return deleted_in_call > 0

    def shutdown(self):
        self.pipe.shutdown()

    def new_prefix(self):
        x = self.pipe.incr(':dbs:')
        return str(x)

    def get_prefix(self):
        return str(self.pfx[:-1])

    def set_prefix(self, prefix):
        self.pfx = str(prefix) + ':'
        key = self.pfx + 'data:'
        if not self.pipe.exists(key):
            # Set up its backref
            self.pipe.hset('back:'+key, ':root:',1)
        self.data = RD(self, uid=key) 
            
    # Counters
    def incr(self, key, x=None):
        key = self.pfx + key
        if x:
            self.pipe.incr(key, x)
        return self.pipe.incr(key)

    def decr(self, key, x=None):
        key = self.pfx + key
        if x:
            self.pipe.decr(key, x)
        return self.pipe.decr(key)

    def count(self, key):
        key = self.pfx + key
        return decode(self,self.pipe.get(key))

    def __getitem__(self, key):
        return self.data[key]

    def get_via_uid(self,uid):
        return self.data.get_via_uid(uid)

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
            while True:
                try:
                    self.watch()
                    transaction_function()
                    self.execute()
                    break
                except WatchError:
                    continue
            self.pipe.reset()
        else:
            raise Exception(
                'Attempted transaction while not in trasaction mode')

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
    def __init__(self, db, data={}, uid=None):
        self.db = db
        if uid is None:
            self.uid = self.db.pfx + 'D' + str(ULID())
        else:
            self.uid = uid
        if data:
            self.db.pipe.hset(self.uid, mapping=data)

    @property
    def refcount(self):
        return int(self.db.pipe.hlen('back:'+self.uid))

    
    @property
    def backrefs(self):
        return {k.decode('utf-8'): int(v) for k,v in self.db.pipe.hgetall('back:'+self.uid).items()}

    def __getitem__(self, key):
        r = self.db.pipe.hget(self.uid, key)
        return decode(self.db, r, key)
    
    def get_via_uid(self,uid):
        r = self.db.pipe.hgetall(uid)
        return decode(self.db, r)
    
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
        Return self as a python dict.  Will throw error if recursive.
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
    def __init__(self, db, data=[], uid=None):
        self.db = db
        if uid is None:
            self.uid = self.db.pfx + 'L' + str(ULID())
        else:
            self.uid = uid
        if data:
            self.extend(data)

    @property
    def refcount(self):
        return self.db.pipe.hlen('back:'+self.uid)
    
    @property
    def backrefs(self):
        return self.db.pipe.hgetall('back:'+self.uid)    
    
    def __getitem__(self, key):

        if isa(key, slice):
            start = key.start
            stop = key.stop
            if start is None: start = 0
            if stop is None: stop = 0
            r = self.db.pipe.lrange(self.uid, start, stop - 1)
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
        Return self as a python list.  Will throw error if recursive.
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