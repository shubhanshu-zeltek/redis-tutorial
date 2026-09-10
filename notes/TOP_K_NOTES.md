# Redis Top-K — Notes

Practice script: [`src/top_k_redis.py`](../src/top_k_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/probabilistic/top-k

---

## What it is

Maintains a running list of the **K most frequent items** in a stream, in fixed
memory — and crucially, **it maintains the list itself**.

That's the difference from a [count-min sketch](COUNT_MIN_SKETCH_NOTES.md). A
CMS can tell you how often `/docs` was hit, but only if you already know to ask
about `/docs`. Top-K tells you **which** items are hot without you naming them
in advance.

---

## Requirements

Needs the **Bloom module** (RedisBloom) — Redis Stack or Redis 8. In redis-py
the accessor is `.topk()`.

---

## How it works — HeavyKeeper

Top-K implements the **HeavyKeeper** algorithm. Roughly: incoming items
probabilistically **decay** the counters of items already tracked. Genuinely
frequent items get reinforced faster than they decay and survive; one-off items
get squeezed out.

Two consequences worth internalising:

- The algorithm optimises for identifying **the correct set of leaders**, not
  for accurate counts.
- The counts it does report **tend to undercount** — the opposite bias to a
  count-min sketch.

---

## Creating

```bash
TOPK.RESERVE key <k> [<width> <depth> <decay>]
```

```bash
TOPK.RESERVE trending 10                    # defaults: width 8, depth 7, decay 0.9
TOPK.RESERVE trending 10 500 8 0.9          # explicit
```

| Parameter | Effect |
|---|---|
| `k` | How many leaders to track |
| `width` | Counters per hash row. Wider = fewer collisions = better accuracy |
| `depth` | Number of hash rows |
| `decay` | Decay probability, `0` to `1`. Lower decays faster, favouring recent items |

**The defaults (8, 7, 0.9) are tiny.** For a real stream with thousands of
distinct items, widen it substantially — the practice script uses `width 500`.
Too small a width and unrelated items collide, corrupting the ranking.

`decay` closer to `1` means counters persist longer, favouring all-time
frequency. Lower values adapt faster to shifts in what's trending.

---

## Adding

```bash
TOPK.ADD key item [item ...]
TOPK.INCRBY key item increment [item increment ...]
```

**`TOPK.ADD` returns, per item, the element it EVICTED from the list** — or
`nil` if nothing was pushed out. This is unusual and easy to misread as an
error or a status code. It's genuinely useful: a non-nil reply is your
notification that the leaderboard changed.

`TOPK.INCRBY` applies arbitrary weights, for replaying batched counts. In
redis-py the signature is `incrby(key, items, increments)` — two parallel
lists.

---

## Querying

```bash
TOPK.QUERY key item [item ...]     # is this item currently in the top-K? 1/0
TOPK.COUNT key item [item ...]     # estimated frequency
TOPK.LIST key                      # the ranking, highest first
TOPK.LIST key WITHCOUNT            # ranking plus counts
TOPK.INFO key                      # k, width, depth, decay
```

**`TOPK.COUNT` is deprecated upstream** and can undercount noticeably. If the
number itself matters, keep a [count-min sketch](COUNT_MIN_SKETCH_NOTES.md)
alongside and use Top-K only for the ranking.

**`TOPK.LIST ... WITHCOUNT` returns a FLAT list** in redis-py:
`[item, count, item, count, ...]`. Unpack it with
`zip(flat[::2], flat[1::2])`, not by iterating pairs directly.

`TOPK.INFO` returns a `TopKInfo` object in redis-py — use `vars()` to print it.

---

## Accuracy in practice

From the practice script: 100,000 events, 5 genuinely hot terms (20k, 15k, 11k,
8k, 5k occurrences) plus a 2,000-term long tail.

- The **five real heavy hitters were identified correctly** and ranked
  correctly.
- The **counts reported were substantially lower** than the true values.
- The remaining slots were filled with long-tail terms whose true counts were
  in the 30-40 range — reasonable, since below the top 5 the tail is nearly
  uniform and any of them is a defensible "6th place".

That's the expected behaviour: **trust the set and the order, not the numbers.**

Memory: 34 KB fixed for Top-K, versus 112 KB for an exact hash of 2,000 terms —
and the gap widens without bound as the number of distinct terms grows.

---

## Choosing between the frequency structures

| Question | Structure |
|---|---|
| **Which items are most frequent?** | **Top-K** |
| How often did *this specific* item appear? | [Count-min sketch](COUNT_MIN_SKETCH_NOTES.md) |
| How many *distinct* items? | [HyperLogLog](HYPERLOGLOG_NOTES.md) |
| Have I seen this item? | [Bloom](BLOOM_FILTER_NOTES.md) / [Cuckoo](CUCKOO_FILTER_NOTES.md) |
| Exact ranking, memory is fine | [Sorted set](SORTED_SET_NOTES.md) + `ZINCRBY` |

**The exact alternative is a sorted set.** `ZINCRBY` per event, `ZREVRANGE` for
the ranking — exact, listable, and it supports removal. Use Top-K only when the
number of distinct items is large enough that a sorted set's memory becomes a
problem.

---

## Gotchas worth remembering

- **`TOPK.ADD` returns evicted items**, not a success code.
- **The default `width` of 8 is far too small** for anything real. Widen it.
- **Counts undercount.** Opposite bias to a CMS, which overcounts.
- **`TOPK.COUNT` is deprecated** — prefer a CMS for actual numbers.
- **`TOPK.LIST WITHCOUNT` is flat**, not a list of pairs.
- **There's no removal.** You cannot un-add an item or evict one manually.
- **You cannot resize.** `k`, width and depth are fixed at reserve time.
- **`TOPK.QUERY` answers "is it in the list?", not "have I seen it?"** — a term
  seen a thousand times can legitimately return `0` if it's not in the top K.
- **redis-py's `incrby` takes two parallel lists.**
- **`TOPK.INFO` returns an object in redis-py**, not a dict.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `TOPK.RESERVE key k [width depth decay]` | Create a Top-K structure |
| `TOPK.ADD key item [item ...]` | Add item(s); returns **evicted** items |
| `TOPK.INCRBY key item n [item n ...]` | Add with weights |
| `TOPK.QUERY key item [item ...]` | Is each item currently in the top-K (1/0) |
| `TOPK.COUNT key item [item ...]` | Estimated count (**deprecated**, undercounts) |
| `TOPK.LIST key [WITHCOUNT]` | The ranking, highest first |
| `TOPK.INFO key` | k, width, depth, decay |
