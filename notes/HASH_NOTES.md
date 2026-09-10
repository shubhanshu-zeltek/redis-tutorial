# Redis Hashes — Notes

Practice script: [`src/hash_redis.py`](../src/hash_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/hashes

---

## What it is

A single Redis key holding a **flat map of field → value**, where both are
strings. The Redis equivalent of a Python dict, a Java HashMap, or a database
row.

The alternative it replaces: storing `user:1:name`, `user:1:email`,
`user:1:role` as three separate string keys. As a hash it's **one key** with
three fields — cheaper in memory, atomically deletable, and individually
addressable all at once.

---

## Key facts

- Max fields per hash: **2^32 - 1**.
- **Flat only.** Values are strings; a hash cannot nest another hash. If you
  need nesting, use [JSON](JSON_NOTES.md).
- Deleting the last field **deletes the key**. An empty hash doesn't exist.
- `HSET` returns the number of fields that were **newly created** — not the
  number written. Overwriting an existing field returns `0`.
- Since **Redis 7.4**, individual fields can have their own TTL. Before that,
  expiration was key-level only.

---

## Complexity

| Operation | Cost |
|---|---|
| `HSET`, `HGET`, `HDEL`, `HEXISTS`, `HINCRBY`, `HSTRLEN` | O(1) |
| `HMGET`, `HDEL` with N fields | O(N) |
| `HGETALL`, `HKEYS`, `HVALS`, `HLEN` | O(N) in the hash size |
| `HSCAN` | O(1) per call, O(N) for a full iteration |

`HLEN` is O(1) despite the table above suggesting otherwise — Redis stores the
count. `HGETALL` is the one to watch: it is O(N) **and** ships every field over
the wire, which blocks the server on a large hash.

---

## Writing

```bash
HSET key field value                    # returns 1 if new, 0 if it overwrote
HSET key f1 v1 f2 v2 f3 v3              # multiple pairs in one call
HSETNX key field value                  # write ONLY if the field doesn't exist
HDEL key field [field ...]              # returns how many were actually removed
HMSET key f1 v1 f2 v2                   # DEPRECATED — HSET does this now
```

`HMSET` was deprecated in Redis 4.0. Use multi-field `HSET`; it does exactly the
same thing and returns a more useful value.

---

## Reading

```bash
HGET key field                # one field, nil if absent
HMGET key f1 f2 f3            # several fields; missing ones come back as nil
HGETALL key                   # every field and value
HKEYS key                     # field names only
HVALS key                     # values only
HLEN key                      # number of fields
HEXISTS key field             # 1 / 0
HSTRLEN key field             # byte length of a field's VALUE (0 if absent)
HRANDFIELD key                # one random field name
HRANDFIELD key 3              # 3 DISTINCT random fields
HRANDFIELD key -5             # 5 random fields, REPEATS allowed
HRANDFIELD key 3 WITHVALUES   # fields plus their values
```

**`HRANDFIELD` with a negative count allows duplicates** and can return more
entries than the hash contains. Positive counts are capped at the hash size.

---

## Iterating safely

```bash
HSCAN key 0                        # returns [next_cursor, [f1, v1, f2, v2, ...]]
HSCAN key 0 MATCH "prefix:*"
HSCAN key 0 COUNT 100              # a HINT for batch size, not a guarantee
HSCAN key 0 NOVALUES               # field names only (Redis 7.4+)
```

`HSCAN` is the safe alternative to `HGETALL` on a big hash. You loop until the
returned cursor is `0`.

**`HSCAN` guarantees**: every element present for the whole iteration **will**
be returned at least once. It does **not** guarantee each element appears only
once, and elements added or removed mid-iteration may or may not show up. Your
code has to tolerate duplicates.

`COUNT` is a hint about work per call, not a page size — you can get more or
fewer elements than you asked for.

---

## Counters inside a hash

```bash
HINCRBY key field 1          # integer, atomic; creates the field at 0 if missing
HINCRBY key field -1         # negative to decrement
HINCRBYFLOAT key field 1.5   # float version
```

There is no `HDECRBY` — pass a negative number.

Same guarantee as `INCR` on strings: atomic, no read-modify-write race. This is
the main reason to keep several related counters in one hash rather than as
separate string keys — they stay together and can be fetched in one `HGETALL`.

---

## Per-field TTL (Redis 7.4+)

Before 7.4, a TTL applied to the whole key. Now individual fields can expire:

```bash
HEXPIRE key 60 FIELDS 1 token             # 60s TTL on one field
HEXPIRE key 60 FIELDS 2 tokenA tokenB     # several fields
HPEXPIRE key 60000 FIELDS 1 token         # milliseconds
HEXPIREAT key <unix-sec> FIELDS 1 token   # absolute
HPEXPIREAT key <unix-ms> FIELDS 1 token
HTTL key FIELDS 1 token                   # seconds left per field
HPTTL key FIELDS 1 token                  # milliseconds left
HEXPIRETIME key FIELDS 1 token            # absolute expiry second
HPERSIST key FIELDS 1 token               # remove the field's TTL
```

Note the mandatory **`FIELDS <numfields>`** clause — an unusual syntax you have
to get right.

The reply is an array of status codes per field:

| Code | Meaning |
|---|---|
| `-2` | No such field (or no such key) |
| `-1` | Field exists but has no TTL |
| `0` | The condition (`NX`/`XX`/`GT`/`LT`) was not met, TTL unchanged |
| `1` | TTL was set |
| `2` | The field was deleted immediately (a TTL in the past) |

For `HTTL` specifically, a non-negative number is the remaining seconds.

In redis-py these are plain methods: `hexpire(key, seconds, *fields)`,
`httl(key, *fields)`, `hpersist(key, *fields)` — the client builds the `FIELDS`
clause for you.

---

## Atomic get + expire / get + delete (Redis 8.0+)

```bash
HGETEX key EX 30 FIELDS 1 field    # read the value AND set its TTL
HGETEX key PERSIST FIELDS 1 field  # read the value AND strip its TTL
HGETDEL key FIELDS 1 field         # read the value AND delete the field
```

The hash-field equivalents of `GETEX` / `GETDEL`. **Redis 8.0+ only** — on 7.x
these return an error, so guard them or fall back to `HGET` + `HDEL`.

---

## Internal encoding

```bash
OBJECT ENCODING key
```

| Encoding | When |
|---|---|
| `listpack` | Small hashes — stored as a flat array of field/value pairs, scanned linearly |
| `hashtable` | Larger hashes — a real hash table |

Thresholds: `hash-max-listpack-entries` (default 128) and
`hash-max-listpack-value` (default 64 bytes). Below both, Redis uses the compact
form, which is dramatically cheaper in memory.

**The conversion is one-way.** Once a hash grows past the threshold and becomes
a `hashtable`, deleting fields does not convert it back.

This is why "one hash per object, kept small" is such an effective memory
pattern — thousands of small hashes stay in `listpack` form.

---

## Gotchas worth remembering

- **`HSET` returns the count of NEW fields**, so updating an existing field
  returns `0`. That is not a failure.
- **`HGETALL` on a large hash blocks the server.** Use `HSCAN`.
- **Hashes are flat.** No nested structures — that's [JSON](JSON_NOTES.md)'s job.
- **Deleting the last field deletes the key**, taking any key-level TTL with it.
- **`HRANDFIELD` with a negative count can return duplicates.**
- **The `FIELDS <numfields>` clause is mandatory** on the `HEXPIRE` family, and
  the count must match.
- **`HGETEX` / `HGETDEL` need Redis 8.0+**; per-field TTL needs 7.4+. Redis
  Stack images have lagged behind on both.
- **`HSCAN` may return the same field twice** across an iteration.
- **`HSTRLEN` measures the value, not the field name.**

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `HSET key f v [f v ...]` | Set field(s); returns count of **newly created** fields |
| `HSETNX key f v` | Set only if the field doesn't exist |
| `HGET key f` | Get one field |
| `HMGET key f [f ...]` | Get several fields |
| `HGETALL key` | Every field and value |
| `HKEYS key` / `HVALS key` | Field names / values only |
| `HLEN key` | Number of fields |
| `HEXISTS key f` | Does the field exist |
| `HSTRLEN key f` | Byte length of the field's value |
| `HDEL key f [f ...]` | Delete field(s); returns how many were removed |
| `HINCRBY key f n` | Atomic integer increment |
| `HINCRBYFLOAT key f n` | Atomic float increment |
| `HRANDFIELD key [count] [WITHVALUES]` | Random field(s); negative count allows repeats |
| `HSCAN key cursor [MATCH p] [COUNT n] [NOVALUES]` | Cursor iteration |
| `HEXPIRE key sec FIELDS n f [f ...]` | Per-field TTL (7.4+) |
| `HPEXPIRE key ms FIELDS n f [...]` | Per-field TTL in ms |
| `HEXPIREAT` / `HPEXPIREAT` | Per-field TTL at an absolute time |
| `HTTL` / `HPTTL key FIELDS n f [...]` | Per-field time remaining |
| `HEXPIRETIME key FIELDS n f [...]` | Absolute expiry second per field |
| `HPERSIST key FIELDS n f [...]` | Remove per-field TTL |
| `HGETEX key [EX n\|PERSIST] FIELDS n f [...]` | Get + set TTL, atomically (8.0+) |
| `HGETDEL key FIELDS n f [...]` | Get + delete field, atomically (8.0+) |
| `HMSET key f v [f v ...]` | **Deprecated** — use `HSET` |
| `OBJECT ENCODING key` | `listpack` / `hashtable` |

---

## Hashes vs. the alternatives

| Want | Use |
|---|---|
| A flat record, fields read/written individually | **Hash** |
| Nested objects and arrays, queryable by path | [JSON](JSON_NOTES.md) |
| One value per key | [String](STRING_NOTES.md) |
| Members ordered by a score | [Sorted set](SORTED_SET_NOTES.md) |
| Many tiny bounded counters, memory-critical | [Bitfield](BITFIELD_NOTES.md) |
