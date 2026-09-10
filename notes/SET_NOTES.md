# Redis Sets — Notes

Practice script: [`src/set_redis.py`](../src/set_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/sets

---

## What it is

An **unordered collection of unique strings**. Adding a member that's already
present is a no-op. No ordering is maintained or promised.

What makes it more than a deduplicating list is that Redis implements the
**set algebra server-side**: union, intersection and difference across any
number of sets, in one command, without shipping members to the client.

---

## Key facts

- Max members: **2^32 - 1**.
- Members are unique; `SADD` on an existing member returns `0`.
- **No ordering guarantee at all.** `SMEMBERS` may return members in a different
  order on different calls or different servers. Never rely on it.
- Removing the last member **deletes the key**.
- `SADD`/`SREM` return the count of members **actually** added/removed, so they
  double as "was this new?" checks.

---

## Complexity

| Operation | Cost |
|---|---|
| `SADD`, `SREM`, `SISMEMBER`, `SCARD` | **O(1)** |
| `SMISMEMBER` | O(N) in the number of members checked |
| `SMEMBERS`, `SRANDMEMBER` with count | O(N) in the set size |
| `SINTER` | O(N*M) — N = smallest set size, M = number of sets |
| `SUNION`, `SDIFF` | O(N) total members across all sets |
| `SPOP` | O(1) for one, O(N) with a count |
| `SSCAN` | O(1) per call |

`SISMEMBER` being **O(1) regardless of set size** is the headline property —
membership testing against a ten-million-member set costs the same as against a
ten-member one.

---

## Membership

```bash
SADD key m [m ...]        # returns how many were NEWLY added
SREM key m [m ...]        # returns how many were actually removed
SISMEMBER key m           # 1 / 0
SMISMEMBER key m1 m2 m3   # array of 1/0, one per member (Redis 6.2+)
SCARD key                 # number of members
SMEMBERS key              # ALL members — O(N), dangerous on big sets
```

`SMISMEMBER` exists purely to save round trips — checking 50 members with
`SISMEMBER` is 50 commands, with `SMISMEMBER` it's one.

---

## Iterating safely

```bash
SSCAN key 0
SSCAN key 0 MATCH "prefix:*"
SSCAN key 0 COUNT 100
```

Loop until the returned cursor is `0`. Same guarantees as `HSCAN`: everything
present throughout the iteration is returned at least once, but **duplicates
are possible** and concurrent changes may or may not be reflected.

`SMEMBERS` is effectively `SSCAN` with no protection — prefer `SSCAN` on
anything large.

---

## Random access

```bash
SRANDMEMBER key        # one random member, NOT removed
SRANDMEMBER key 3      # 3 DISTINCT random members
SRANDMEMBER key -5     # 5 random members, REPEATS allowed
SPOP key               # one random member, REMOVED
SPOP key 3             # 3 random members, removed
```

The distinction:

- **`SRANDMEMBER` reads**, `SPOP` **removes**.
- **Negative count on `SRANDMEMBER` allows duplicates** and can return more
  members than the set holds. Positive counts are capped at the set size.
- `SPOP` has no negative-count form — you can't remove the same member twice.

---

## Moving members

```bash
SMOVE src dst member    # atomically move one member between sets
```

Returns `1` if the member was there and moved, `0` if it wasn't in `src`. Both
the remove and the add happen as one operation — no window where the member
exists in neither set or both.

---

## Set algebra

```bash
SINTER key [key ...]     # members present in ALL the sets
SUNION key [key ...]     # every distinct member across the sets
SDIFF  key [key ...]     # members of the FIRST key that are in none of the others
```

**`SDIFF` is not symmetric.** `SDIFF a b` and `SDIFF b a` give different
answers. The first key is the base; every other key subtracts from it.

Each has a `...STORE` variant that writes the result into a destination key
instead of returning it, and returns the resulting cardinality:

```bash
SINTERSTORE dest key [key ...]
SUNIONSTORE dest key [key ...]
SDIFFSTORE  dest key [key ...]
```

The `STORE` forms **overwrite** the destination, and if the result is empty they
**delete** it.

And a cardinality-only form (Redis 7.0+):

```bash
SINTERCARD numkeys key [key ...] [LIMIT n]
```

`SINTERCARD` computes the **size** of the intersection without materialising it.
`LIMIT n` stops counting once it reaches `n`, which bounds the worst case — the
right tool for "do these sets overlap by at least N?" without paying for the
full intersection.

Note the awkward signature: `numkeys` comes first, and in redis-py the keys go
in as a **list**: `sintercard(len(keys), keys, limit=0)`.

---

## Internal encoding

```bash
OBJECT ENCODING key
```

| Encoding | When |
|---|---|
| `intset` | **All** members are integers, and there are few enough of them |
| `listpack` | Small sets with non-integer members (Redis 7.2+) |
| `hashtable` | Anything larger |

Thresholds: `set-max-intset-entries` (default 512), `set-max-listpack-entries`
(default 128), `set-max-listpack-value` (default 64 bytes).

An **all-integer set is dramatically cheaper** — `intset` is a sorted array of
integers with no per-member overhead at all. Adding one non-integer member
converts the whole set and it never converts back. Worth knowing if you're
storing numeric ids: keep them numeric.

---

## Gotchas worth remembering

- **No ordering. Ever.** `SMEMBERS` order is an implementation detail that can
  change between calls. If you need order, use a
  [sorted set](SORTED_SET_NOTES.md) or a [list](LIST_NOTES.md).
- **`SMEMBERS` on a large set blocks the server.** Use `SSCAN`.
- **`SDIFF` is order-sensitive** — the first key is the minuend.
- **`SRANDMEMBER` with a negative count can return duplicates**, and more
  results than the set has members.
- **`SINTERCARD` takes `numkeys` first**, and redis-py wants the keys as a list,
  not varargs.
- **`SPOP` on a multi-member set is genuinely random** — don't use it expecting
  insertion order.
- **Removing the last member deletes the key** along with any TTL on it.
- **The `intset` encoding is one-way.** One non-integer member converts the set
  permanently.
- **`SSCAN` may return duplicates** across a full iteration.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `SADD key m [m ...]` | Add member(s); returns count **newly** added |
| `SREM key m [m ...]` | Remove member(s); returns count actually removed |
| `SISMEMBER key m` | Is this a member (1/0) |
| `SMISMEMBER key m [m ...]` | Batch membership check (6.2+) |
| `SCARD key` | Number of members |
| `SMEMBERS key` | All members — O(N) |
| `SSCAN key cursor [MATCH p] [COUNT n]` | Cursor iteration |
| `SRANDMEMBER key [count]` | Random member(s), **not** removed |
| `SPOP key [count]` | Random member(s), **removed** |
| `SMOVE src dst m` | Atomically move a member between sets |
| `SINTER key [key ...]` | Intersection |
| `SUNION key [key ...]` | Union |
| `SDIFF key [key ...]` | First key minus all the others |
| `SINTERSTORE dst key [...]` | Intersection → a key; returns cardinality |
| `SUNIONSTORE dst key [...]` | Union → a key |
| `SDIFFSTORE dst key [...]` | Difference → a key |
| `SINTERCARD numkeys key [...] [LIMIT n]` | Intersection **size** only (7.0+) |
| `OBJECT ENCODING key` | `intset` / `listpack` / `hashtable` |

---

## Sets vs. the alternatives

| Want | Use |
|---|---|
| Unique members, O(1) membership, set algebra | **Set** |
| Unique members **with an order/score** | [Sorted set](SORTED_SET_NOTES.md) |
| Duplicates allowed, insertion order | [List](LIST_NOTES.md) |
| Only the distinct **count**, huge scale | [HyperLogLog](HYPERLOGLOG_NOTES.md) |
| Membership only, memory-critical, approximate OK | [Bloom](BLOOM_FILTER_NOTES.md) / [Cuckoo](CUCKOO_FILTER_NOTES.md) |
| Dense integer ids, membership only | [Bitmap](BITMAP_NOTES.md) |
