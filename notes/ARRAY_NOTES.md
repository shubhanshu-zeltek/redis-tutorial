# Redis Arrays — Notes

Practice script: [`src/array_redis.py`](../src/array_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/arrays

---

## What it is

**Sparse, index-addressable sequences of strings.** Indexes run `0` to
`2^64 - 1`, and you can write index 1,000,000 **without allocating the million
slots before it**.

That sparseness is the whole point, and it's what separates arrays from every
existing Redis type:

| | [List](LIST_NOTES.md) | [Bitmap](BITMAP_NOTES.md) | **Array** |
|---|---|---|---|
| Addressed by | Position | Bit offset | **Arbitrary index** |
| Random access | O(N) | O(1) | **O(1)** |
| Gaps cost memory | N/A | **Yes** (dense) | **No** (sparse) |
| Push/pop at ends | O(1) | N/A | Cursor-based insert |
| Element type | String | One bit | String |

Verified: an array with only indexes `0` and `1,000,000` set reports
`ARLEN` 1,000,001, `ARCOUNT` 2, and uses **2,313 bytes**. The equivalent bitmap
would need 125 KB just for the gap.

---

## Requirements

**Redis 8.8+.** The `AR*` command group is not in Redis 7.x or the current
`redis/redis-stack` image. Verified against `redis:8-alpine` (8.10.1):

```bash
docker run -d --rm --name redis8 -p 6380:6379 redis:8-alpine
python src/array_redis.py 6380
```

**redis-py 8.1 has no `arset()`/`arget()` helpers yet**, so the practice script
goes through `execute_command("ARSET", ...)`. That's a useful pattern in its
own right for reaching any command your client predates.

---

## Two size measurements

This distinction is the first thing to internalise:

```bash
ARLEN key      # LOGICAL length: highest set index + 1
ARCOUNT key    # OCCUPIED slots: how many indexes actually hold a value
```

For a dense array these are equal. For a sparse one they can differ by orders
of magnitude — `ARLEN` 1,000,001 versus `ARCOUNT` 2 in the example above.

---

## Writing

```bash
ARSET key <index> <value> [value ...]        # CONTIGUOUS values starting at index
ARMSET key <index> <value> [<index> <value> ...]   # arbitrary, scattered indexes
```

```bash
ARSET events 0 login click purchase      # writes indexes 0, 1, 2
ARMSET metrics 0 10 5 20 100 30          # writes indexes 0, 5 and 100
```

`ARSET` is for runs; `ARMSET` is for scattered writes. Both return the number
of values written.

---

## Reading

```bash
ARGET key <index>                     # nil if the slot was never set
ARMGET key <index> [index ...]        # several indexes; gaps come back as nil
ARGETRANGE key <start> <end>          # values across a range, gaps INCLUDED as nil
ARSCAN key <start> <end> [LIMIT n]    # (index, value) pairs, gaps SKIPPED
ARLASTITEMS key <count> [REV]         # the most recently inserted elements
```

**`ARGETRANGE` vs `ARSCAN` is the choice that matters on a sparse array.**
`ARGETRANGE seq 0 3` on an array with indexes 0, 1, 3 set returns
`['a', 'b', None, 'd']` — every slot, nulls included. `ARSCAN seq 0 3` returns
`[[0,'a'], [1,'b'], [3,'d']]` — only what exists, with its index.

On a sparse array `ARGETRANGE` over a wide span returns mostly nulls and is
capped at **1,000,000 elements per call** as a guard.

`ARLASTITEMS` returns oldest-first by default; `REV` flips it.

---

## The insert cursor

Arrays keep an internal cursor so you can append without tracking indexes:

```bash
ARINSERT key <value> [value ...]   # write at the cursor, advancing it
ARNEXT key                          # what index the next ARINSERT will use
ARSEEK key <index>                  # move the cursor
```

```bash
ARINSERT log "event1"    # -> 0
ARINSERT log "event2"    # -> 1
ARNEXT log               # -> 2
ARSEEK log 10            # -> 10
ARINSERT log "event3"    # -> 10
```

`ARINSERT` returns the index it wrote to.

---

## Ring buffer mode

```bash
ARRING key <size> <value> [value ...]
```

Inserts into a **fixed-size ring**, wrapping and overwriting the oldest entry
once full:

```bash
ARRING readings 3 v0    # -> 0
ARRING readings 3 v1    # -> 1
ARRING readings 3 v2    # -> 2
ARRING readings 3 v3    # -> 0   (wraps, v0 is gone)
```

Combined with `ARGREP` below, this gives you a fixed-size, **searchable** tail
of the last N entries — a capped log you can query in place. That's the
capability a capped [list](LIST_NOTES.md) (`LPUSH` + `LTRIM`) doesn't have.

The ring size can change between calls; resizing is O(N+M).

---

## Aggregation — `AROP`

```bash
AROP key <start> <end> SUM|MIN|MAX|AND|OR|XOR|USED|MATCH <value>
```

Folds a range server-side, without shipping any values back:

| Operation | Returns |
|---|---|
| `SUM`, `MIN`, `MAX` | Numeric aggregate over the range |
| `AND`, `OR`, `XOR` | Bitwise fold over the range |
| `USED` | How many slots in the range are occupied |
| `MATCH <value>` | How many elements equal `<value>` |

**Note what is NOT here.** The docs page lists `AVG` and `COUNT`; the shipped
server has **`USED`** instead and no `AVG`. Verified against 8.10.1 — trust
`COMMAND DOCS AROP` on your server over the docs page.

---

## Search — `ARGREP`

```bash
ARGREP key <start> <end> <predicate...> [AND|OR] [LIMIT n] [WITHVALUES] [NOCASE]
```

Predicates, repeatable:

| Predicate | Matches |
|---|---|
| `EXACT <string>` | The whole value equals it |
| `MATCH <string>` | Substring |
| `GLOB <pattern>` | Glob pattern (`warn:*`) |
| `RE <pattern>` | Regular expression |

```bash
ARGREP syslog 0 4 MATCH error NOCASE
# -> [2, 4]

ARGREP syslog 0 4 GLOB "warn:*" GLOB "error:*" OR WITHVALUES
# -> [[1, "warn: disk"], [4, "error: net"]]
```

Without `WITHVALUES` you get indexes only. `AND`/`OR` combine multiple
predicates (default is `AND`), and `LIMIT` caps the hit count.

**There is no predicate-count argument.** The docs' Python example suggests a
count prefix; the wire protocol takes the predicates directly.

---

## The `-` / `+` bounds — only on `ARGREP`

`-` and `+` mean "first index" and "last index"... but **only `ARGREP` accepts
them.** Verified on 8.10.1:

| Command | `-` / `+` |
|---|---|
| `ARGREP` | **Works** |
| `ARGETRANGE` | Error: `invalid array index` |
| `ARSCAN` | Error: `invalid array index` |
| `AROP` | Error: `invalid array index` |
| `ARDELRANGE` | Error: `invalid array index` |

Everything except `ARGREP` needs real integers. And unlike lists, **negative
indexes are not supported** — `ARSCAN key 0 -1` is an error, not "to the end".
Use `ARLEN key - 1` to compute the last index yourself.

---

## Deleting

```bash
ARDEL key <index> [index ...]                    # specific indexes
ARDELRANGE key <start> <end> [<start> <end> ...] # one or MORE ranges
```

`ARDELRANGE` takes **multiple ranges in a single call** — `ARDELRANGE scores
0 1 3 4` deletes both spans at once.

**Deleting the last remaining element removes the key entirely**, as with every
other Redis collection.

---

## Introspection

```bash
ARINFO key         # len, count, next-insert-index, slices, directory-size, slice-size
ARINFO key FULL    # plus per-slice fill rates and dense/sparse slice counts
```

Arrays are stored as a directory of fixed-size **slices**, each of which is
independently dense or sparse. `ARINFO FULL` shows that breakdown, which is how
you'd diagnose an array that's using more memory than expected.

Configuration parameters: `array-slice-size`, `array-sparse-kmin`,
`array-sparse-kmax`.

---

## Performance

O(1): `ARSET`, `ARGET`, `ARDEL`, `ARINSERT`, `ARNEXT`, `ARSEEK`, `ARCOUNT`,
`ARLEN`.

O(N): `ARGETRANGE`, `ARSCAN`, `ARDELRANGE`, `AROP`, `ARLASTITEMS`, `ARGREP` —
proportional to positions visited, not to the numeric span of the range. A
range query across a mostly-empty million-index span is cheap.

---

## Gotchas worth remembering

- **`ARLEN` ≠ `ARCOUNT`.** Logical length versus occupied slots.
- **Only `ARGREP` accepts `-` and `+`.** Everything else wants integers.
- **Negative indexes don't work.** No `-1` for "the end".
- **`AROP` has `USED`, not `AVG`/`COUNT`** — the docs page is out of step with
  the shipped command.
- **`ARGREP` takes no predicate-count prefix.**
- **`ARGETRANGE` returns nulls for gaps**; `ARSCAN` skips them. Pick
  deliberately.
- **`ARGETRANGE` is capped at 1,000,000 elements** per call.
- **`ARDELRANGE` accepts multiple ranges**, which is easy to miss.
- **redis-py 8.1 has no array helpers** — use `execute_command`.
- **Not in Redis 7 or the current Redis Stack image.** Check `INFO server`.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `ARSET key index value [value ...]` | Write contiguous values from an index |
| `ARMSET key index value [index value ...]` | Write scattered index/value pairs |
| `ARGET key index` | Value at an index (nil if unset) |
| `ARMGET key index [index ...]` | Several indexes at once |
| `ARGETRANGE key start end` | Values across a range, gaps as nil (max 1M) |
| `ARSCAN key start end [LIMIT n]` | (index, value) pairs, gaps skipped |
| `ARLEN key` | Highest set index + 1 |
| `ARCOUNT key` | Number of occupied slots |
| `ARLASTITEMS key count [REV]` | Most recently inserted elements |
| `ARINSERT key value [value ...]` | Append at the cursor; returns the index used |
| `ARNEXT key` | The next index `ARINSERT` will use |
| `ARSEEK key index` | Move the insert cursor |
| `ARRING key size value [value ...]` | Insert into a fixed-size ring buffer |
| `AROP key start end SUM\|MIN\|MAX\|AND\|OR\|XOR\|USED\|MATCH v` | Aggregate a range |
| `ARGREP key start end <EXACT\|MATCH\|GLOB\|RE pattern>... [AND\|OR] [LIMIT n] [WITHVALUES] [NOCASE]` | Search a range |
| `ARDEL key index [index ...]` | Delete specific indexes |
| `ARDELRANGE key start end [start end ...]` | Delete one or more ranges |
| `ARINFO key [FULL]` | Structure metadata and slice statistics |

---

## When to use an array instead

| Want | Use |
|---|---|
| Push/pop at the ends, insert between elements | [List](LIST_NOTES.md) |
| Values addressed by name | [Hash](HASH_NOTES.md) |
| Append-only log with consumer groups and acks | [Stream](STREAM_NOTES.md) |
| One bit per dense integer id | [Bitmap](BITMAP_NOTES.md) |
| **Sparse or high-index access, O(1) by index** | **Array** |
