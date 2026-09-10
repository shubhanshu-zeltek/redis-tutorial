# Redis Cuckoo Filter — Notes

Practice script: [`src/cuckoo_filter_redis.py`](../src/cuckoo_filter_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/probabilistic/cuckoo-filter

---

## What it is

The same job as a [Bloom filter](BLOOM_FILTER_NOTES.md) — approximate
"have I seen this?" in tiny memory — with two differences that decide which one
you pick:

1. **Cuckoo filters can DELETE** (`CF.DEL`) and **count** (`CF.COUNT`).
2. **Cuckoo filters can FAIL TO INSERT** when buckets get crowded.

Same one-sided guarantee: **"no" is always correct, "yes" may be a false
positive.**

---

## Requirements

Needs the **Bloom module** (RedisBloom) — Redis Stack or Redis 8. In redis-py
the accessor is `.cf()`: `client.cf().add(...)`.

---

## How it works, briefly

Instead of setting bits like a Bloom filter, a cuckoo filter stores a short
**fingerprint** of each item in one of two candidate **buckets**. If both are
full, it *evicts* an existing fingerprint and re-homes it in that
fingerprint's alternate bucket — cascading until everything fits or the
`MAXITERATIONS` budget runs out.

Two consequences follow directly:

- Deletion works, because you can find and remove a specific fingerprint.
- Insertion can fail, because the eviction cascade can run out of moves.

---

## Creating a filter

```bash
CF.RESERVE key <capacity> [BUCKETSIZE n] [MAXITERATIONS n] [EXPANSION n]
```

| Parameter | Effect |
|---|---|
| `capacity` | Expected number of items |
| `BUCKETSIZE` | Fingerprints per bucket (default 2). Larger = fewer insert failures, higher false-positive rate |
| `MAXITERATIONS` | How many evictions to attempt before giving up (default 20) |
| `EXPANSION` | Growth factor when full (default 1); `0` disables growth |

Unlike Bloom, **there is no error-rate parameter.** The false-positive rate is
a function of the fingerprint size and bucket size, which Redis derives from
capacity. You tune it indirectly via `BUCKETSIZE`.

---

## Adding

```bash
CF.ADD key item      # ALWAYS adds — even if a copy is already there
CF.ADDNX key item    # add only if probably absent; 0 = already present
CF.INSERT key [CAPACITY n] [NOCREATE] ITEMS item [...]
CF.INSERTNX key [CAPACITY n] [NOCREATE] ITEMS item [...]
```

**`CF.ADD` does not deduplicate.** Calling it twice on the same item stores two
fingerprints and `CF.COUNT` reports `2`. That is the mechanism behind counting,
but it is a trap if you wanted set semantics — use **`CF.ADDNX`** for that.

---

## Checking and counting

```bash
CF.EXISTS key item                # 1 = probably, 0 = definitely not
CF.MEXISTS key item [item ...]
CF.COUNT key item                 # how many copies were added
```

`CF.COUNT` is approximate in the same way `CF.EXISTS` is — collisions can
inflate it.

---

## Deleting — the headline feature

```bash
CF.DEL key item      # removes ONE copy; returns 1 if something was removed
```

**Only delete items you actually added.** This is a genuine correctness
constraint, not a style note. Deleting an item that was never inserted can
remove a *different* item's fingerprint that happens to collide — silently
introducing a **false negative**, which breaks the filter's one guarantee.

Delete the last copy and the item genuinely disappears; `CF.EXISTS` then
returns `0`.

---

## Introspection and serialization

```bash
CF.INFO key
CF.SCANDUMP key iterator
CF.LOADCHUNK key iterator chunk
```

`CF.INFO` reports size, bucket count, bucket size, max iterations, expansion,
and counters for insertions and deletions. In redis-py this comes back as a
`CFInfo` **object** — use `vars()` to print it.

---

## Bloom vs Cuckoo — the decision

| | Bloom | Cuckoo |
|---|---|---|
| Delete | **No** | **Yes** |
| Count duplicates | No | Yes |
| Insert can fail | Only if `NONSCALING` | **Yes**, when crowded |
| Configurable error rate | **Yes** (`ERROR`) | No, indirect via `BUCKETSIZE` |
| Lookup speed | Slower as it scales (many sub-filters) | Constant, 2 bucket probes |
| Memory at low error rates | Better | Worse |
| Memory at ~3% error and above | Worse | Better |
| Deleting a never-added item | N/A | **Can corrupt the filter** |

**Default to Bloom.** Reach for Cuckoo when you specifically need deletion or
duplicate counting, and you can guarantee you only ever delete items you added.

---

## Gotchas worth remembering

- **`CF.ADD` does not deduplicate** — it happily stores the same item twice.
  Use `CF.ADDNX` if you want set behaviour.
- **Deleting an item you never inserted can corrupt the filter**, producing
  false negatives. This is the single most important rule here.
- **Insertion can fail.** A crowded filter returns an error or `0` from
  `CF.ADD`. Bloom filters (scaling ones) never do this.
- **No `ERROR` parameter.** You can't dial the false-positive rate directly.
- **`EXPANSION 0` disables growth**, making the filter strictly bounded.
- **`CF.INSERT` requires the `ITEMS` keyword**, like `BF.INSERT`.
- **`NOCREATE` on a missing key errors** ("not found") rather than creating.
- **`CF.INFO` returns an object in redis-py**, not a dict.
- Same as Bloom: **`0` is trustworthy, `1` is not.**

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `CF.RESERVE key capacity [BUCKETSIZE n] [MAXITERATIONS n] [EXPANSION n]` | Create a filter |
| `CF.ADD key item` | Add unconditionally (duplicates allowed) |
| `CF.ADDNX key item` | Add only if probably absent |
| `CF.INSERT key [CAPACITY n] [NOCREATE] ITEMS item [...]` | Bulk add |
| `CF.INSERTNX key [CAPACITY n] [NOCREATE] ITEMS item [...]` | Bulk add, skipping duplicates |
| `CF.EXISTS key item` | `1` = probably, `0` = definitely not |
| `CF.MEXISTS key item [item ...]` | Batch check |
| `CF.COUNT key item` | Approximate number of copies |
| `CF.DEL key item` | Remove **one** copy |
| `CF.INFO key` | Size, buckets, iterations, insert/delete counters |
| `CF.SCANDUMP key iterator` | Serialize in chunks |
| `CF.LOADCHUNK key iterator chunk` | Restore from chunks |
