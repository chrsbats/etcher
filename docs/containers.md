# Persistent containers

`RD` and `RL` behave like mutable mappings and sequences. Equality (`==`)
compares contents; use `is` for Python object identity or compare `.uid` values
for persisted identity within the same store.

## Printed summaries

Summaries start with `@` and show identifiers for nested containers instead of
expanding them. This keeps the output compact even when references form a cycle.

Set `link_field` to display a field from a child `RD` instead of its internal UID.
The field is displayed unquoted; if its value matches the key under which the
child is stored, the summary displays `*` as shorthand for “same as the key.”
This affects display only, not the stored values or their types.

```python
from etcher import DB

db = DB("people.db", link_field="id")
db["people"] = {
    "alice": {"id": "alice", "name": "Alice"},
    "bob": {"id": "bob-42", "name": "Bob"},
}
print(db["people"])  # @{'alice': *, 'bob': bob-42}
```

## Materializing cycles

Calling a persistent container produces a plain Python snapshot. If links form
a cycle, the resulting dicts and lists refer back to one another:

```python
from etcher import DB

db = DB("friends.db")
db["a"] = {"name": "A"}
db["b"] = {"name": "B", "friend": db["a"]}
db["a"]["friend"] = db["b"]

a = db["a"]()
assert a["friend"]["friend"] is a
```
