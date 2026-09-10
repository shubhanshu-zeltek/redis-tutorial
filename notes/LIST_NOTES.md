# Redis Lists — Notes

Practice script: [`src/list_redis.py`](../src/list_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/lists

---

## What it is

An ordered sequence of strings, kept in **insertion order**, implemented as a
linked list of compact nodes. Duplicates are allowed. Elements are addressed by
**position**, not by key or index-you-choose.

The defining property: pushing and popping **at either end is O(1)**, no matter
how long the list is. Everything else about lists follows from that.

---

## Key facts

- Max length: **2^32 - 1** elements (~4.29 billion).
- `LPUSH` / `RPUSH` return the **new length** of the list after the push.
- Pushing multiple values in one `LPUSH` pushes them **one at a time**, so
  `LPUSH k a b c` leaves the list as `[c, b, a]` — the last argument ends up
  at the head.
- Popping the last element **deletes the key**. An empty list does not exist in
  Redis; `EXISTS` returns 0.
- Operations on a **missing key** behave as if it were an empty list: `LPUSH`
  creates it, `LPOP` returns `nil`, `LLEN` returns `0`.

---

## Mental model — head and tail

```
        LPUSH →  [ head ... tail ]  ← RPUSH
        LPOP  ←                    →  RPOP
```

"Left" = head = index `0`. "Right" = tail = index `-1`.

| Pattern | Push with | Pop with | Why |
|---|---|---|---|
| **Stack (LIFO)** | `LPUSH` | `LPOP` | Same end — last in, first out |
| **Queue (FIFO)** | `LPUSH` | `RPOP` | Opposite ends — first in, first out |
| **Queue (FIFO)** | `RPUSH` | `LPOP` | Equivalent, reads more naturally |

The push side alone doesn't determine stack-vs-queue. What matters is **which
end you pop from relative to the end you push to.**

---

## Complexity

| Operation | Cost |
|---|---|
| `LPUSH`, `RPUSH`, `LPOP`, `RPOP`, `LLEN` | **O(1)** |
| `LINDEX`, `LSET` | O(N) — O(1) near either end |
| `LINSERT`, `LREM`, `LPOS` | O(N) |
| `LRANGE` | O(S+N), S = offset of start, N = elements returned |
| `LTRIM` | O(N) in the number of elements **removed** |

The recurring theme: **the ends are cheap, the middle is not.** `LINDEX` on
element 500,000 of a million-element list walks half the list.

---

## Pushing

```bash
LPUSH key v [v ...]    # push to head; returns new length
RPUSH key v [v ...]    # push to tail
LPUSHX key v           # push to head ONLY if the key already exists (else 0, no-op)
RPUSHX key v           # same, at the tail
```

`LPUSHX`/`RPUSHX` exist so a producer can append to a list only if a consumer
has already established it — no accidental key creation from a typo.

---

## Popping

```bash
LPOP key            # one element from the head
LPOP key 3          # up to 3 elements, as an array (Redis 6.2+)
RPOP key [count]    # same, from the tail
```

---

## Reading without removing

```bash
LRANGE key 0 -1        # the whole list, head → tail
LRANGE key 0 9         # first 10 elements
LLEN key               # length
LINDEX key 0           # element at an index (0 = head, -1 = tail)
LPOS key "value"                 # index of the first match
LPOS key "value" RANK 2          # index of the SECOND match
LPOS key "value" RANK -1         # search from the tail backwards
LPOS key "value" COUNT 0         # indexes of EVERY match
LPOS key "value" MAXLEN 100      # give up after comparing 100 elements
```

**`LRANGE` never auto-reverses.** `LRANGE key -1 0` returns an **empty array**,
not the list backwards. If `start` resolves to a position after `stop`, you get
nothing. To read newest-first, either push to the other end or reverse in your
client.

Both `LRANGE` indexes are **inclusive**, and out-of-range indexes are clamped
rather than erroring — `LRANGE key 0 999999` on a 3-element list is fine.

---

## Modifying in place

```bash
LSET key 0 "new"                  # overwrite by index; ERRORS if index is out of range
LINSERT key BEFORE "pivot" "new"  # insert next to the FIRST match of pivot
LINSERT key AFTER  "pivot" "new"  # -> returns -1 if the pivot isn't found
LREM key 1 "v"     # remove up to 1 occurrence, searching head → tail
LREM key -1 "v"    # negative count searches tail → head
LREM key 0 "v"     # count 0 removes ALL occurrences
LTRIM key 0 4      # keep only elements 0..4, discard the rest
```

`LSET` on an out-of-range index is an **error**, unlike most Redis commands
which silently no-op. `LINSERT` with a missing pivot returns `-1` instead.

**`LTRIM` is the capping primitive.** `LPUSH` followed by `LTRIM key 0 N-1`
keeps a list at a fixed maximum length — the standard way to hold "the most
recent N items" without unbounded growth.

---

## Moving between lists, atomically

```bash
RPOPLPUSH src dst                  # tail of src → head of dst (older command)
LMOVE src dst LEFT RIGHT           # general version: pick the end on both sides (6.2+)
```

`LMOVE` supersedes `RPOPLPUSH` — same job, but you choose `LEFT`/`RIGHT`
independently for source and destination.

**Same key for source and destination rotates the list**, which is how you build
round-robin iteration without removing anything.

The reliability angle: popping from one list and pushing to another in a
**single atomic step** means a worker that crashes mid-job has still left the
job recorded somewhere. Pop-then-push as two commands loses the item if the
process dies in between.

---

## Blocking variants

```bash
BLPOP key [key ...] timeout       # block until an element is available at a head
BRPOP key [key ...] timeout       # same, at a tail
BLMOVE src dst LEFT RIGHT timeout # blocking LMOVE (6.2+)
BRPOPLPUSH src dst timeout        # blocking RPOPLPUSH (older)
```

- `timeout` is in **seconds**, and **`0` means block forever**.
- Multiple keys: returns from whichever key gets data first.
- The reply is `[key, value]` — you need the key name because you may have been
  watching several.
- Returns `nil` if the timeout expires with nothing arriving.

This is what makes lists usable as a work queue without polling: many workers
can block on the same key, and Redis hands the next pushed item to whichever
has been waiting longest.

---

## Popping across multiple lists (Redis 7.0+)

```bash
LMPOP  numkeys key [key ...] LEFT|RIGHT [COUNT n]
BLMPOP timeout numkeys key [key ...] LEFT|RIGHT [COUNT n]
```

Pops from the **first non-empty list** among those named. Useful when one worker
watches several queues and just wants work from whichever has some, without
checking each in turn.

Note the argument order differs from `BLPOP`: the key count comes first, and
the direction is a required keyword.

---

## Sorting

```bash
SORT key                       # numeric ascending (errors on non-numeric values)
SORT key DESC
SORT key ALPHA                 # lexicographic — required for non-numeric values
SORT key LIMIT 0 10            # offset / count
SORT key BY weight_*           # sort by an external key pattern
SORT key GET pattern_*         # return values from other keys instead
SORT key STORE dest            # write the result into a new list
SORT_RO key                    # read-only variant, replica-safe
```

`SORT` without `ALPHA` on non-numeric values is an error, not a fallback.

---

## Internal encoding

```bash
OBJECT ENCODING key
```

| Encoding | When |
|---|---|
| `listpack` | Small lists — a single contiguous, compact allocation |
| `quicklist` | Larger lists — a linked list of listpack nodes |

Controlled by `list-max-listpack-size`. Transparent: commands behave identically
either way, but the encoding explains why small lists are so cheap.

---

## Gotchas worth remembering

- **`LRANGE key -1 0` returns empty**, not a reversed list.
- **`LPUSH key a b c` yields `[c, b, a]`** — elements are pushed one at a time.
- **`LSET` on a bad index errors**; most other list commands quietly no-op.
- **Popping the last element deletes the key.** `EXISTS` then returns 0, and a
  `TTL` you had set is gone with it.
- **`BLPOP timeout` of `0` blocks forever** — not "don't block".
- **Blocking commands return `[key, value]`**, not just the value.
- **`LINDEX` in the middle of a long list is O(N).** Lists are not arrays; if
  you need indexed random access, use [Arrays](ARRAY_NOTES.md) (Redis 8.8+).
- `LMPOP`'s argument order (`numkeys` first, direction as a keyword) is unlike
  `BLPOP`'s.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `LPUSH key v [v ...]` | Push to the head; returns the new length |
| `RPUSH key v [v ...]` | Push to the tail; returns the new length |
| `LPUSHX key v` / `RPUSHX key v` | Push only if the key already exists |
| `LPOP key [count]` | Pop from the head |
| `RPOP key [count]` | Pop from the tail |
| `LLEN key` | Number of elements |
| `LRANGE key start stop` | Range of elements, head → tail, inclusive |
| `LINDEX key index` | Element at an index (`0` head, `-1` tail) |
| `LSET key index v` | Overwrite by index (errors if out of range) |
| `LINSERT key BEFORE\|AFTER pivot v` | Insert next to the first matching value |
| `LREM key count v` | Remove occurrences (`>0` head→tail, `<0` tail→head, `0` all) |
| `LTRIM key start stop` | Keep only the given range |
| `LPOS key v [RANK n] [COUNT n] [MAXLEN n]` | Find index/indexes of a value |
| `RPOPLPUSH src dst` | Atomic tail → head move |
| `LMOVE src dst LEFT\|RIGHT LEFT\|RIGHT` | Generalized atomic move (6.2+) |
| `BLPOP key [key ...] timeout` | Blocking `LPOP`; `0` = forever |
| `BRPOP key [key ...] timeout` | Blocking `RPOP` |
| `BLMOVE src dst LEFT\|RIGHT LEFT\|RIGHT timeout` | Blocking `LMOVE` (6.2+) |
| `BRPOPLPUSH src dst timeout` | Blocking `RPOPLPUSH` |
| `LMPOP numkeys key [key ...] LEFT\|RIGHT [COUNT n]` | Pop from the first non-empty list (7.0+) |
| `BLMPOP timeout numkeys key [...] LEFT\|RIGHT [COUNT n]` | Blocking `LMPOP` (7.0+) |
| `SORT key [BY p] [LIMIT o n] [GET p] [ASC\|DESC] [ALPHA] [STORE dst]` | Sort the list |
| `SORT_RO key ...` | Read-only `SORT` |
| `OBJECT ENCODING key` | `listpack` / `quicklist` |

---

## Lists vs. the alternatives

| Want | Use |
|---|---|
| Push/pop at the ends, ordered, duplicates OK | **List** |
| Ordered by a score you control | [Sorted set](SORTED_SET_NOTES.md) |
| Unique members, no order | [Set](SET_NOTES.md) |
| Append-only log with consumer groups and acks | [Stream](STREAM_NOTES.md) |
| Direct O(1) access by arbitrary index | [Array](ARRAY_NOTES.md) |
