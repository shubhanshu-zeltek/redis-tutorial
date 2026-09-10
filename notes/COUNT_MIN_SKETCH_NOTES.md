# Redis Count-Min Sketch — Notes

Practice script: [`src/count_min_sketch_redis.py`](../src/count_min_sketch_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/probabilistic/count-min-sketch

---

## What it is

Estimates **how many times each item has appeared** in a stream, in fixed
memory.

Where a [Bloom filter](BLOOM_FILTER_NOTES.md) answers *"seen it?"*, a
count-min sketch answers *"seen it how often?"*.

The critical property: **a CMS never undercounts.** Hash collisions can only
add to a counter, never subtract, so every estimate is an **upper bound** on
the true count. Verified in the practice script — zero undercounts across 500
sampled keys.

---

## Requirements

Needs the **Bloom module** (RedisBloom) — Redis Stack or Redis 8. In redis-py
the accessor is `.cms()`.

---

## How it works, briefly

A 2D array of counters: **`depth`** rows, **`width`** counters per row, with a
different hash function per row.

- **Increment**: hash the item once per row, bump that counter in each row.
- **Query**: hash the same way, read all `depth` counters, return the
  **minimum**.

Taking the minimum is why it never undercounts: at least one of the counters
must be at least the true count, and collisions only inflate the others. The
more rows, the better the chance that one row was collision-free for this item.

---

## Creating a sketch

Two ways, and you must use exactly one — a sketch cannot be resized later.

```bash
CMS.INITBYDIM key <width> <depth>
CMS.INITBYPROB key <error> <probability>
```

**`INITBYDIM`** — you choose the dimensions directly.

```bash
CMS.INITBYDIM hits 2000 5      # 2000 counters wide, 5 hash rows
```

**`INITBYPROB`** — you state the accuracy you want and Redis derives the
dimensions.

```bash
CMS.INITBYPROB hits 0.001 0.999   # error <= 0.1% of total, held with 99.9% probability
```

- `error` is **relative to the total count ingested**, not to the individual
  item's count. With 1,000,000 total increments and `error` 0.001, the absolute
  error bound is ~1,000 — which is nothing for a heavy hitter and everything
  for an item that appeared twice.
- `probability` is the confidence that the bound holds.

`INITBYPROB` is usually the right choice — reasoning about error rates is
easier than reasoning about widths and depths.

---

## Incrementing and querying

```bash
CMS.INCRBY key item increment [item increment ...]
CMS.QUERY key item [item ...]
```

```bash
CMS.INCRBY hits /home 120 /docs 300
CMS.QUERY hits /home /docs /never-seen
```

`CMS.INCRBY` takes **parallel item/increment pairs**, and batching many pairs
into one call is far cheaper than one call per event. In redis-py the signature
is `incrby(key, items, increments)` — two **separate lists**, not pairs.

Querying an item never inserted usually returns `0`, but may return a small
inflated number from collisions. There is no way to distinguish "never seen"
from "seen once, plus a collision".

---

## Merging

```bash
CMS.MERGE dest numkeys src [src ...] [WEIGHTS w [w ...]]
```

```bash
CMS.MERGE total 2 day1 day2
CMS.MERGE weighted 2 day1 day2 WEIGHTS 1 3     # count day2 three times over
```

**All sketches must have identical `width` and `depth`**, and the destination
must already exist with those same dimensions. Merging mismatched sketches is
an error.

Weighted merges let you decay old data or emphasise recent windows.

---

## Introspection

```bash
CMS.INFO key    # width, depth, and the total count ingested
```

Returns a `CMSInfo` object in redis-py — use `vars()` to print it.

---

## Accuracy in practice

From the practice script: a skewed stream of 5 hot keys plus a 50,000-key long
tail, sketched with `INITBYPROB 0.001 0.999`.

- **Heavy hitters** (`/home` at 60,000, `/docs` at 35,000): estimated exactly,
  error 0.
- **Long-tail items** (true count 1): frequently estimated as 2 or 3.

That pattern is the whole story. **A CMS is accurate for the items that
matter and noisy for the ones that don't** — the absolute error is roughly
constant, so it's negligible against a large count and proportionally huge
against a small one.

Memory from the same run: sketch **16 KB** fixed, versus an exact hash of
45,476 keys at **2.7 MB**.

---

## CMS vs Top-K

They answer different questions and are frequently confused:

| | Count-min sketch | [Top-K](TOP_K_NOTES.md) |
|---|---|---|
| Question | "How often did **X** appear?" | "**Which** items appear most?" |
| Needs you to name the item | **Yes** | No |
| Returns a ranking | **No** | Yes |
| Count accuracy | Overcounts, bounded | Undercounts, looser |

There is **no way to list the top items from a CMS** — it doesn't retain them.
If you need the ranking itself, that's Top-K. Using both together is common:
Top-K for *which*, CMS for *how many*.

---

## Gotchas worth remembering

- **It only overcounts, never undercounts.** Every answer is an upper bound.
- **`error` is relative to the TOTAL count**, not the item's count. This is the
  most misunderstood parameter.
- **You cannot list or enumerate items.** You must name what you're asking about.
- **You cannot resize.** Dimensions are fixed at init; to change them you
  rebuild from the source data.
- **`CMS.MERGE` requires identical dimensions** and a pre-created destination.
- **There is no decrement.** Counts only go up. Time-windowing means keeping
  per-window sketches and merging, not subtracting.
- **`0` from `CMS.QUERY` doesn't prove absence** — and neither does a small
  positive number prove presence.
- **redis-py's `incrby` takes two parallel lists**, not a list of pairs.
- **`CMS.INFO` returns an object in redis-py**, not a dict.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `CMS.INITBYDIM key width depth` | Create with explicit dimensions |
| `CMS.INITBYPROB key error probability` | Create from a target accuracy |
| `CMS.INCRBY key item n [item n ...]` | Increment item counts |
| `CMS.QUERY key item [item ...]` | Estimated count per item |
| `CMS.MERGE dest numkeys src [src ...] [WEIGHTS w ...]` | Merge sketches of identical dimensions |
| `CMS.INFO key` | Width, depth, total count |
