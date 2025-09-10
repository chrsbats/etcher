try:
    import redis  # ensure present in sys.modules for aliasing
except Exception:
    pass

from .exceptions import WatchError
from .db import DB, DBConnections, db_connections, RD, RL, list_db

