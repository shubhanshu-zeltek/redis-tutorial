# Redis JSON — Notes

Practice script: [`src/json_redis.py`](../src/json_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/json

---

## What it is

Stores a **real, parsed JSON document** as a Redis value, and lets you read or
mutate any node inside it by **JSONPath** — without a GET-parse-modify-SET
round trip.

The problem it solves: with a [string](STRING_NOTES.md) holding serialized JSON,
incrementing one counter means fetching the whole blob, parsing it, changing one
number, re-serializing, and writing it all back — non-atomic and expensive. With
Redis JSON that's `JSON.NUMINCRBY key $.counter 1`.

Unlike a [hash](HASH_NOTES.md), it supports **nesting** — objects inside arrays
inside objects, to any depth.

---

## Requirements

Needs the **JSON module** (formerly ReJSON), which ships with **Redis Stack**
and is built into **Redis 8**. Plain `redis:7-alpine` does **not** have it.

```bash
docker compose -f docker-compose-stack.yaml.yaml up -d
```

In redis-py the commands live behind the `.json()` accessor:
`client.json().set(...)`, not `client.jsonset(...)`.

Values are stored **binary, in a tree format** — not as the original text. Key
ordering and whitespace are not preserved.

---

## JSONPath basics

`$` is the root. Everything else follows JSONPath syntax:

| Path | Selects |
|---|---|
| `$` | The whole document |
| `$.price` | A top-level field |
| `$.specs.layout` | A nested field |
| `$.tags[0]` | An array element |
| `$.tags[*]` | Every array element |
| `$..price` | **Recursive** — every `price` at any depth |
| `$.reviews[*].user` | A field from every array element |
| `$.reviews[?(@.rating==5)]` | A **filter** — elements matching a predicate |
| `$.tags[1:3]` | An array slice |

**A JSONPath returns a LIST of every match**, even when there's exactly one.
This is why `JSON.GET key $.price` gives `[4999.0]` rather than `4999.0`, and
why `JSON.NUMINCRBY` returns an array too. Get used to unwrapping.

The legacy path syntax (`.price`, or a bare `price`, no `$`) returns a scalar
instead of an array, and errors on missing paths rather than returning empty.
**Prefer `$` paths in new code** — the behaviour is more predictable and
`$`-paths are what the multi-match commands are designed around.

---

## Documents

```bash
JSON.SET key $ '{"name":"Keyboard","price":4999}'
JSON.SET key $.price 5999                # update a nested path
JSON.SET key $.warranty 24 NX            # only if the path does NOT exist
JSON.SET key $.price 1 XX                # only if the path DOES exist
JSON.GET key                             # the whole document
JSON.GET key $.price
JSON.GET key $.name $.price              # several paths -> a dict keyed by path
JSON.DEL key $.warranty                  # delete one node
JSON.DEL key $                           # delete the whole document
JSON.TYPE key $.price                    # object|array|string|integer|number|boolean|null
JSON.CLEAR key $.specs                   # empty containers / zero numbers, keep the key
JSON.RESP key                            # the document in RESP wire form
```

**`JSON.SET` on a nested path requires the parent to exist.** You can set
`$.specs.layout` only if `$.specs` is already an object; Redis will not create
intermediate levels for you.

**`JSON.CLEAR` vs `JSON.DEL`**: `CLEAR` empties an array or object and sets
numbers to `0`, leaving the key in place; `DEL` removes the node entirely.

---

## Multi-document commands

```bash
JSON.MGET key1 key2 key3 $.name          # the same path across many documents
JSON.MSET key1 $ '{...}' key2 $ '{...}'  # several documents atomically (7.0+)
JSON.MERGE key $.specs '{"a":1,"b":null}'
```

**`JSON.MERGE` implements RFC 7386 merge-patch**, which has one behaviour worth
memorising: **a `null` value deletes that field**. So merging
`{"switches":"red","backlit":null}` sets `switches` and *removes* `backlit`.
That's the spec, not a quirk, but it surprises people.

---

## Numbers

```bash
JSON.NUMINCRBY key $.stock -3
JSON.NUMMULTBY key $.price 1.1
```

Atomic, in place. There is no `NUMDIVBY` — multiply by a fraction. Both return
an array of new values (one per path match).

---

## Strings

```bash
JSON.STRAPPEND key $.name '" (v2)"'      # note: the value must itself be valid JSON
JSON.STRLEN key $.name
```

**The appended value has to be a JSON string**, i.e. quoted. redis-py handles
the quoting for you when you pass a Python `str`.

---

## Booleans

```bash
JSON.TOGGLE key $.in_stock     # flips true <-> false, returns the new value(s)
```

---

## Arrays inside the document

```bash
JSON.ARRAPPEND key $.tags '"new"' '"another"'
JSON.ARRINSERT key $.tags 1 '"inserted"'      # insert at index 1
JSON.ARRINDEX  key $.tags '"rgb"'             # index of a value, -1 if absent
JSON.ARRINDEX  key $.tags '"rgb"' 2 5         # search within a slice
JSON.ARRLEN    key $.tags
JSON.ARRPOP    key $.tags                     # last element (default index -1)
JSON.ARRPOP    key $.tags 0                   # first element
JSON.ARRTRIM   key $.tags 0 4                 # keep only indexes 0..4
```

You can append whole objects, not just scalars — `JSON.ARRAPPEND key $.reviews
'{"user":"x","rating":5}'` is fine.

---

## Objects inside the document

```bash
JSON.OBJKEYS key $.specs      # the field names of an object
JSON.OBJLEN  key $.specs      # how many fields
```

---

## Debugging

```bash
JSON.DEBUG MEMORY key         # memory used by the document, in bytes
JSON.DEBUG HELP
```

---

## JSON vs. Hash

| | Hash | JSON |
|---|---|---|
| Nesting | No — flat only | Yes, arbitrary depth |
| Types | Everything is a string | Real numbers, booleans, null, arrays, objects |
| Query a nested node | Impossible | JSONPath |
| Per-field TTL | Yes (7.4+) | No |
| Memory | Lower | Higher (parse tree overhead) |
| Availability | Core Redis | Needs the JSON module |
| Atomic single-field update | `HSET` / `HINCRBY` | `JSON.SET` / `JSON.NUMINCRBY` |

Rule of thumb: **flat record → hash; nested document → JSON.** Don't reach for
JSON just because your data arrived as JSON — if it flattens cleanly, a hash is
cheaper and works on any Redis.

---

## Gotchas worth remembering

- **`$` paths always return arrays.** `[4999.0]`, not `4999.0`.
- **Legacy paths (no `$`) behave differently** — scalar returns, errors on
  missing paths. Don't mix the two styles in one codebase.
- **`JSON.MERGE` deletes fields set to `null`.** RFC 7386 behaviour.
- **`JSON.SET` won't create intermediate parents.**
- **`JSON.STRAPPEND` needs a quoted JSON string**, not a bare word.
- **`JSON.ARRINDEX` returns `-1` for "not found"**, wrapped in an array — so
  `[-1]`, which is truthy in Python. Check the value, not the list.
- **No per-field TTL.** Expiration is key-level only, unlike hashes.
- **The module is required.** On plain Redis 7 you get
  `ERR unknown command 'JSON.SET'`.
- **Numbers are stored as JSON numbers**, so a value written as `5498.9` may
  read back as `5498.900000000001` — ordinary float representation, not a bug.
- **redis-py uses `.json()`**, and its `strappend` signature is
  `strappend(name, value, path)` — value **before** path, unlike most others.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `JSON.SET key path value [NX\|XX]` | Set the document or a node |
| `JSON.GET key [path ...]` | Get the document or node(s) |
| `JSON.MGET key [key ...] path` | The same path across many documents |
| `JSON.MSET key path value [...]` | Set several documents atomically (7.0+) |
| `JSON.MERGE key path value` | RFC 7386 merge-patch (`null` deletes) |
| `JSON.DEL key [path]` | Delete a node (or the whole document) |
| `JSON.FORGET key [path]` | Alias for `JSON.DEL` |
| `JSON.CLEAR key [path]` | Empty containers / zero numbers |
| `JSON.TYPE key [path]` | The JSON type at a path |
| `JSON.RESP key [path]` | The document in RESP form |
| `JSON.NUMINCRBY key path n` | Atomic add |
| `JSON.NUMMULTBY key path n` | Atomic multiply |
| `JSON.STRAPPEND key [path] value` | Append to a string node |
| `JSON.STRLEN key [path]` | Length of a string node |
| `JSON.TOGGLE key path` | Flip a boolean |
| `JSON.ARRAPPEND key path value [value ...]` | Append to an array |
| `JSON.ARRINSERT key path index value [...]` | Insert into an array |
| `JSON.ARRINDEX key path value [start [stop]]` | Find a value (`-1` if absent) |
| `JSON.ARRLEN key [path]` | Array length |
| `JSON.ARRPOP key [path [index]]` | Remove and return an element |
| `JSON.ARRTRIM key path start stop` | Keep only a slice |
| `JSON.OBJKEYS key [path]` | Field names of an object |
| `JSON.OBJLEN key [path]` | Number of fields |
| `JSON.DEBUG MEMORY key` | Bytes used by the document |
