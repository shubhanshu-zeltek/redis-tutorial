# Redis t-digest — Notes

Practice script: [`src/t_digest_redis.py`](../src/t_digest_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/probabilistic/t-digest

---

## What it is

Estimates **percentiles** over a stream of numbers **without keeping the
numbers**.

This is the structure behind "what's our p99 latency?". Computing an exact p99
means sorting every observation, which means storing every observation. A
t-digest keeps a few hundred **centroids** — weighted cluster summaries — and
answers percentile queries from those.

Its defining property: **accuracy is much higher at the extremes** (p1, p99,
p999) than in the middle. That is exactly the right bias for latency and SLA
work, where nobody cares whether the median is 20.03 or 20.05 but everyone
cares about the tail.

---

## Requirements

Needs the **Bloom module** (RedisBloom) — Redis Stack or Redis 8. In redis-py
the accessor is `.tdigest()`.

---

## Creating

```bash
TDIGEST.CREATE key [COMPRESSION n]     # default compression 100
```

**`compression`** is the accuracy/memory dial. Higher means more centroids,
tighter estimates, more memory. 100 is the default and is fine for most
monitoring; the practice script uses 500 for the accuracy comparison.

`TDIGEST.ADD` on a missing key creates one with default compression, so
`CREATE` is optional — but explicit is better when you care about accuracy.

---

## Adding observations

```bash
TDIGEST.ADD key value [value ...]
```

Values are floats. Batching many values per call matters — the practice script
feeds 100,000 samples in chunks of 5,000.

In redis-py the signature is `add(key, values)` — a **list**, not varargs.

---

## Querying

The four ways to interrogate a digest, and they are easy to mix up:

```bash
TDIGEST.QUANTILE key 0.5 0.9 0.99     # fraction  -> VALUE
TDIGEST.CDF key 15.0 50.0             # value     -> FRACTION  (the inverse)
TDIGEST.RANK key 9.8 15.0             # value     -> COUNT of observations <=
TDIGEST.REVRANK key 250.0             # value     -> COUNT of observations >=
TDIGEST.BYRANK key 0 5 9              # rank      -> VALUE
TDIGEST.BYREVRANK key 0 1             # reverse rank -> VALUE
```

| Command | Input | Output |
|---|---|---|
| `QUANTILE` | A fraction (0.99) | The value at that percentile |
| `CDF` | A value (50ms) | The fraction of observations at or below it |
| `RANK` | A value | How many observations are ≤ it |
| `BYRANK` | A rank (integer) | The value at that position |

`QUANTILE`/`CDF` work in fractions; `RANK`/`BYRANK` work in absolute counts.

**Edge cases for `RANK`**: a value below the minimum returns `-1`; a value above
the maximum returns the total observation count.

---

## Summary statistics

```bash
TDIGEST.MIN key
TDIGEST.MAX key
TDIGEST.TRIMMED_MEAN key <low_quantile> <high_quantile>
```

`MIN` and `MAX` are **exact** — the digest tracks them separately.

**`TRIMMED_MEAN` is the underrated one.** The plain arithmetic mean is dragged
around by outliers; trimming the tails gives the typical case. From the
practice script, ten latencies including one 250 ms outlier:

- plain mean: **41.18**
- trimmed mean (10-90%): **15.36**

The second number is the one that describes normal behaviour.

---

## Merging and resetting

```bash
TDIGEST.MERGE dest numkeys src [src ...] [COMPRESSION n] [OVERRIDE]
TDIGEST.RESET key
```

**Merging is lossless in the sense that matters** — you can compute a
fleet-wide p99 by merging per-service digests, which you fundamentally cannot
do with pre-computed percentiles. (Averaging the p99s of ten services gives a
meaningless number; merging their digests gives the real one.) This is the main
operational reason to use t-digest over storing percentiles directly.

- Without `OVERRIDE`, sources are merged **into** the destination's existing
  contents.
- With **`OVERRIDE`**, the destination is reset first.

`TDIGEST.RESET` empties a digest but keeps the key and its compression setting.

In redis-py: `merge(destination_key, num_keys, *keys, compression=None,
override=False)`.

---

## Introspection

```bash
TDIGEST.INFO key
```

Reports compression, capacity, merged/unmerged node counts and weights, total
compressions, and memory usage. Returns a `TDigestInfo` object in redis-py —
use `vars()`.

---

## Accuracy in practice

From the practice script: 100,000 log-normal samples, compression 500, compared
against exact sorted percentiles.

| Quantile | Exact | t-digest | Error |
|---|---|---|---|
| p50 | 20.036 | 20.030 | 0.033% |
| p90 | 43.436 | 43.448 | 0.027% |
| p95 | 53.826 | 53.865 | 0.074% |
| p99 | 81.526 | 81.588 | 0.075% |
| p99.9 | 130.072 | 129.374 | 0.537% |

Sub-0.1% error through p99. Memory: **48 KB** for the digest, versus ~780 KB to
store 100,000 raw doubles — and the digest's size is bounded by compression, not
by how many observations pass through it.

---

## t-digest vs the alternatives

| Want | Use |
|---|---|
| **Percentiles over a stream** | **t-digest** |
| Frequency of a named item | [Count-min sketch](COUNT_MIN_SKETCH_NOTES.md) |
| The most frequent items | [Top-K](TOP_K_NOTES.md) |
| Distinct count | [HyperLogLog](HYPERLOGLOG_NOTES.md) |
| Timestamped samples with retention and aggregation | [Time series](TIMESERIES_NOTES.md) |
| Exact percentiles, small dataset | [Sorted set](SORTED_SET_NOTES.md) + `ZRANGE` by rank |

t-digest and [time series](TIMESERIES_NOTES.md) are complementary, not
competing: the time series keeps the samples over time, the t-digest answers
distributional questions about them cheaply.

---

## Gotchas worth remembering

- **`QUANTILE` and `CDF` are inverses.** Fraction→value vs value→fraction.
  Reaching for the wrong one is the most common mistake here.
- **Accuracy is deliberately uneven** — tight at the tails, looser in the
  middle. Don't be surprised that p50 is less precise than p99 in relative
  terms.
- **`MIN`/`MAX` are exact**, unlike everything else.
- **`RANK` of a below-minimum value is `-1`**, not `0`.
- **Merging digests is valid; averaging percentiles is not.** This is the whole
  reason to store digests rather than computed percentiles.
- **`MERGE` accumulates into the destination** unless you pass `OVERRIDE`.
- **`RESET` keeps the compression setting**; `DEL` throws it away.
- **`TDIGEST.ADD` takes a list in redis-py**, not varargs.
- **`TDIGEST.INFO` returns an object in redis-py**, not a dict.
- Higher compression costs memory and CPU on merge; don't crank it without
  measuring.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `TDIGEST.CREATE key [COMPRESSION n]` | Create a digest |
| `TDIGEST.ADD key value [value ...]` | Add observations |
| `TDIGEST.QUANTILE key q [q ...]` | Value at each quantile |
| `TDIGEST.CDF key value [value ...]` | Fraction of observations ≤ each value |
| `TDIGEST.RANK key value [value ...]` | Count of observations ≤ each value (`-1` if below min) |
| `TDIGEST.REVRANK key value [value ...]` | Count ≥ each value |
| `TDIGEST.BYRANK key rank [rank ...]` | Value at each rank |
| `TDIGEST.BYREVRANK key rank [rank ...]` | Value at each reverse rank |
| `TDIGEST.MIN key` / `TDIGEST.MAX key` | Exact minimum / maximum |
| `TDIGEST.TRIMMED_MEAN key low high` | Mean with the tails discarded |
| `TDIGEST.MERGE dest numkeys src [...] [COMPRESSION n] [OVERRIDE]` | Merge digests |
| `TDIGEST.RESET key` | Empty the digest, keep its settings |
| `TDIGEST.INFO key` | Compression, nodes, weights, memory |
