# Redis Bloom Filter — Notes

Practice script: [`src/bloom_filter_redis.py`](../src/bloom_filter_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/probabilistic/bloom-filter

---

## What it is

Answers **"have I seen this before?"** in a small fraction of the memory a
[Set](SET_NOTES.md) would need.

The guarantee is **one-sided**, and this is the whole point:

- **"No" is always correct.** A false negative is impossible.
- **"Yes" may be wrong**, at approximately the configured error rate.

Measured in the practice script: 10,000 items at a 1% target error rate gave
101 false positives out of 10,000 probes (**1.01%**) and **zero** false
negatives.

You also **cannot remove items**. If you need deletes, use a
[Cuckoo filter](CUCKOO_FILTER_NOTES.md).

---

## Requirements

Needs the **Bloom module** (RedisBloom), which ships with **Redis Stack** and
is built into **Redis 8**. Not in plain `redis:7-alpine`.

```bash
docker compose -f docker-compose-stack.yaml.yaml up -d
```

In redis-py the commands live behind `.bf()`: `client.bf().add(...)`.

---

## Complexity

O(k) per operation, where k is the number of hash functions — effectively
**O(1)**, independent of how many items the filter holds.

---

## Creating a filter

```bash
BF.RESERVE key <error_rate> <capacity> [EXPANSION n] [NONSCALING]
```

```bash
BF.RESERVE seen 0.001 10000            # 0.1% error, sized for 10k items
BF.RESERVE seen 0.01 1000 EXPANSION 2  # scale by doubling when full
BF.RESERVE seen 0.01 100 NONSCALING    # refuse writes past capacity
```

- **`error_rate`** — the target false-positive probability. Lower costs more
  memory (roughly linearly in `log(1/error)`).
- **`capacity`** — the number of items you expect. Sizing matters: exceed it
  and either the filter scales (degrading accuracy) or errors.
- **`EXPANSION`** — the growth factor when a scaling filter fills up.
- **`NONSCALING`** — refuse to grow. `BF.ADD` past capacity returns an error
  ("non scaling filter is full") instead of silently degrading.

**If you don't `BF.RESERVE`, the first `BF.ADD` creates a filter with the
server defaults** (`bf-error-rate` 0.01, `bf-initial-size` 100). Those defaults
are almost certainly wrong for your workload — always reserve explicitly.

---

## Scaling vs non-scaling

A **scaling** filter (the default) handles overflow by stacking a new
sub-filter on top of the old one. That works, but:

- The effective error rate **grows** — the compound error across sub-filters is
  higher than the one you asked for.
- Lookups get slower, because every sub-filter must be checked.

A **non-scaling** filter keeps its guarantee exactly, at the cost of erroring
when full. If accuracy is what you're relying on, prefer `NONSCALING` and size
generously.

---

## Adding

```bash
BF.ADD key item                  # 1 = definitely new, 0 = probably present
BF.MADD key item [item ...]      # array of 1/0
BF.INSERT key [CAPACITY n] [ERROR e] [EXPANSION n] [NOCREATE] [NONSCALING] ITEMS item [...]
```

`BF.INSERT` is the do-everything command: it can create the filter with your
parameters *and* populate it in a single call. **`NOCREATE`** makes it error
rather than create a missing filter.

Note the mandatory **`ITEMS`** keyword before the item list.

---

## Checking

```bash
BF.EXISTS key item                # 1 = probably yes, 0 = definitely no
BF.MEXISTS key item [item ...]    # array of 1/0
BF.CARD key                       # number of items added
```

**Read `1` as "probably" and `0` as "certainly not".** That asymmetry is the
entire contract.

`BF.CARD` counts items **added**, which for a filter with duplicate adds is not
the number of distinct items.

---

## Introspection

```bash
BF.INFO key
BF.INFO key CAPACITY | SIZE | FILTERS | ITEMS | EXPANSION
```

Reports capacity, size in bytes, number of stacked sub-filters, items inserted,
and the expansion rate. A `FILTERS` count above 1 tells you the filter has
scaled and its real error rate is now worse than configured.

In redis-py this returns a `BFInfo` **object**, not a dict — wrap it in
`vars()` to print it usefully.

---

## Serialization

```bash
BF.SCANDUMP key iterator     # returns [next_iterator, chunk]; 0 means done
BF.LOADCHUNK key iterator chunk
```

For copying a filter between servers without re-adding every item. Loop
`SCANDUMP` from iterator `0` until it returns `0`, feeding each chunk to
`LOADCHUNK` on the destination.

---

## Bloom vs the alternatives

| | Set | Bloom | Cuckoo |
|---|---|---|---|
| False positives | No | **Yes** | Yes |
| False negatives | No | **No** | No |
| Delete items | Yes | **No** | **Yes** |
| Count duplicates | N/A | No | Yes (`CF.COUNT`) |
| List members | Yes | No | No |
| Memory (10k items) | ~500 KB | **~12 KB** | Comparable |
| Insert can fail | No | Only if `NONSCALING` | **Yes**, when buckets crowd |

**Bloom vs Cuckoo** in one line: Bloom is simpler and never fails to insert;
Cuckoo can delete and count but can refuse an insert. Pick Bloom unless you
specifically need deletion.

**Bloom vs Set**: only switch when the memory genuinely hurts. You are trading
away exactness, enumeration, and deletion.

---

## Gotchas worth remembering

- **`0` from `BF.EXISTS` is trustworthy; `1` is not.** Design around this — a
  Bloom filter is a *cache-miss filter*, not an authority. The usual pattern is
  "if the filter says no, skip the expensive lookup entirely; if it says yes,
  do the real lookup."
- **You cannot delete.** Not from a Bloom filter, ever.
- **A scaling filter silently degrades its error rate.** Check `BF.INFO`'s
  filter count.
- **Not reserving means server defaults** — 0.01 error, 100 capacity, which
  will scale immediately under real load.
- **`BF.CARD` counts adds, not distinct items.**
- **`BF.INSERT` requires the `ITEMS` keyword.**
- **redis-py names**: `client.bf().create(...)` and `client.bf().reserve(...)`
  are the same command; `insert` takes `noCreate`/`noScale` in camelCase, unlike
  most of the library.
- **`BF.INFO` returns an object in redis-py**, not a dict.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `BF.RESERVE key error capacity [EXPANSION n] [NONSCALING]` | Create a sized filter |
| `BF.ADD key item` | Add one; `1` = new, `0` = probably present |
| `BF.MADD key item [item ...]` | Add several |
| `BF.INSERT key [CAPACITY n] [ERROR e] [EXPANSION n] [NOCREATE] [NONSCALING] ITEMS item [...]` | Create and/or add |
| `BF.EXISTS key item` | `1` = probably, `0` = definitely not |
| `BF.MEXISTS key item [item ...]` | Batch check |
| `BF.CARD key` | Number of items added |
| `BF.INFO key [field]` | Capacity, size, sub-filter count, items, expansion |
| `BF.SCANDUMP key iterator` | Serialize the filter in chunks |
| `BF.LOADCHUNK key iterator chunk` | Restore from chunks |
