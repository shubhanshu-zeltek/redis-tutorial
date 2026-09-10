# Redis Time Series — Notes

Practice script: [`src/timeseries_redis.py`](../src/timeseries_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/timeseries

---

## What it is

Purpose-built storage for **(timestamp, value) samples**, with four things you'd
otherwise have to build yourself:

1. **Compressed chunks** — Gorilla-style delta-of-delta encoding, far denser
   than storing pairs in a sorted set.
2. **Automatic retention** — old samples expire without a cleanup job.
3. **Label-based querying** — "every series where `sensor=temp` and `floor=2`",
   across many keys at once.
4. **Compaction rules** — server-side downsampling into coarser series as data
   arrives.

You *could* fake this with a [sorted set](SORTED_SET_NOTES.md) keyed by
timestamp, and people do. You'd lose all four of the above.

---

## Requirements

Needs the **timeseries module** (RedisTimeSeries) — Redis Stack or Redis 8. In
redis-py the accessor is `.ts()`.

**Timestamps are milliseconds since the Unix epoch**, or `*` meaning "now".

---

## Creating and configuring

```bash
TS.CREATE key [RETENTION ms] [ENCODING COMPRESSED|UNCOMPRESSED] [CHUNK_SIZE n]
              [DUPLICATE_POLICY policy] [LABELS l v [l v ...]]
TS.ALTER key [RETENTION ms] [LABELS l v ...] [DUPLICATE_POLICY policy]
TS.INFO key
```

```bash
TS.CREATE temp:room:1 RETENTION 3600000 LABELS sensor temp room 1 floor 2
```

- **`RETENTION`** is in **milliseconds**, and `0` (the default) means keep
  forever. An hour is `3600000` — easy to get wrong by three orders of
  magnitude.
- **`LABELS`** are what make cross-series queries possible. Design them
  deliberately; you cannot query on something you didn't label.
- **`TS.ALTER` replaces the label set entirely** — it does not merge. Omitting
  a label removes it.

`TS.ADD` on a missing key **creates it implicitly** with default settings and
no labels, which is usually not what you want. Create series explicitly.

---

## Writing samples

```bash
TS.ADD key <timestamp|*> <value> [RETENTION ms] [LABELS ...] [ON_DUPLICATE policy]
TS.MADD key ts value [key ts value ...]
TS.INCRBY key <value> [TIMESTAMP ts]
TS.DECRBY key <value> [TIMESTAMP ts]
TS.DEL key <from_ts> <to_ts>
```

`TS.MADD` writes to several series in one round trip — the right way to ingest
a batch of readings from different sensors.

`TS.INCRBY`/`TS.DECRBY` treat the series as a counter sampled over time,
adding to the most recent value rather than recording an independent sample.

**`TS.DEL` takes an inclusive range**, and there is no "delete one sample" —
pass the same timestamp twice.

---

## Duplicate timestamps

What happens when you write a timestamp that already exists is governed by
`DUPLICATE_POLICY`:

| Policy | Behaviour |
|---|---|
| `BLOCK` | Reject with an error. **The default.** |
| `FIRST` | Keep the existing value, ignore the new one |
| `LAST` | Overwrite with the new value |
| `MIN` / `MAX` | Keep whichever is smaller / larger |
| `SUM` | Add them together |

Set it at `TS.CREATE`/`TS.ALTER` time, or override it for a single write with
`ON_DUPLICATE`:

```bash
TS.ADD temp 1000 42.0 ON_DUPLICATE MAX
```

The `BLOCK` default surprises people ingesting from an at-least-once source —
a retried write errors out. `LAST` is usually the pragmatic choice there.

---

## Reading one series

```bash
TS.GET key [LATEST]
TS.RANGE key <from> <to> [COUNT n] [AGGREGATION type bucket_ms] [...]
TS.REVRANGE key <from> <to> [...]
```

`-` and `+` mean the first and last timestamp:

```bash
TS.RANGE key - +
```

**Downsampling on read** is the feature you'll use constantly:

```bash
TS.RANGE key - + AGGREGATION avg 60000     # one-minute averages
```

Available aggregators: `avg`, `sum`, `min`, `max`, `count`, `first`, `last`,
`range` (max−min), `std.p`, `std.s`, `var.p`, `var.s`, `twa` (time-weighted
average).

Other range modifiers:

| Modifier | Effect |
|---|---|
| `FILTER_BY_TS ts [ts ...]` | Only these exact timestamps |
| `FILTER_BY_VALUE min max` | Only samples in this value range |
| `ALIGN start\|end\|<ts>` | Where bucket boundaries begin |
| `EMPTY` | Report empty buckets instead of skipping them |
| `BUCKETTIMESTAMP start\|end\|mid` | Which timestamp labels each bucket |
| `LATEST` | Include the latest, still-open compaction bucket |

**`ALIGN` matters more than it looks.** Without it, buckets are aligned to
epoch 0, so a "1-minute average" may straddle wall-clock minutes.

---

## Reading many series by label

This is what separates a time series from a pile of sorted sets:

```bash
TS.QUERYINDEX <filter> [filter ...]         # which series match?
TS.MGET FILTER <filter> [WITHLABELS]        # last sample of each match
TS.MRANGE <from> <to> FILTER <filter> [...] # ranges across matches
TS.MREVRANGE <from> <to> FILTER <filter> [...]
```

Filter syntax:

| Filter | Matches |
|---|---|
| `label=value` | Equals |
| `label!=value` | Not equals |
| `label=` | The label is **absent** |
| `label!=` | The label **exists** |
| `label=(v1,v2)` | Any of these values |
| `label!=(v1,v2)` | None of these values |

At least one `label=value` (equality) filter is required — you can't query on
negations alone.

And the aggregation that makes it powerful:

```bash
TS.MRANGE - + FILTER sensor=temp AGGREGATION avg 300000 GROUPBY floor REDUCE avg
```

**`GROUPBY <label> REDUCE <fn>`** collapses many series into one per label
value — "average temperature per floor" in a single command. `REDUCE` accepts
`avg`, `sum`, `min`, `max`, `count`, `range`, `std.p`, `std.s`, `var.p`,
`var.s`.

---

## Compaction rules — downsampling on write

```bash
TS.CREATERULE <source> <dest> AGGREGATION <type> <bucket_ms> [alignTimestamp]
TS.DELETERULE <source> <dest>
```

```bash
TS.CREATE temp:1m LABELS sensor temp agg avg1m
TS.CREATERULE temp:raw temp:1m AGGREGATION avg 60000
```

As samples land in the source, Redis automatically maintains the aggregated
destination. The standard pattern: keep raw data for hours, keep 1-minute and
1-hour rollups for months, with different `RETENTION` on each.

**Rules only apply to samples written AFTER the rule is created.** Creating a
rule does not backfill. This catches everyone once.

The destination series must already exist, and a series can be the source of
several rules but the destination of only one.

---

## Compression

The default `COMPRESSED` encoding uses delta-of-delta timestamp encoding and
XOR value compression — typically **~90% smaller** than raw pairs, and it
works best on regularly-spaced samples with slowly-changing values.

`UNCOMPRESSED` exists for irregular or highly volatile data where compression
doesn't pay, and for workloads doing many out-of-order writes.

---

## Time series vs a sorted set

| | Sorted set | Time series |
|---|---|---|
| Store (ts, value) | Yes, score = ts | Yes, native |
| Compression | None | ~90% |
| Retention | Manual `ZREMRANGEBYSCORE` | Automatic |
| Aggregate on read | No | Yes, many functions |
| Downsample on write | No | Yes, compaction rules |
| Query across keys by metadata | No | Yes, labels |
| Duplicate timestamps | Overwrites the member | Configurable policy |
| Availability | Core Redis | Needs the module |

The sorted-set approach also has a subtle flaw: the *member* must be unique, so
two samples with the same value at different times work, but the same value
twice needs an artificial suffix.

---

## Gotchas worth remembering

- **Retention is in milliseconds.** One hour is `3600000`.
- **`DUPLICATE_POLICY` defaults to `BLOCK`** — retried writes error.
- **Compaction rules don't backfill.** Only future samples are aggregated.
- **`TS.ALTER` replaces labels wholesale**, it doesn't merge them.
- **`TS.ADD` creates missing series implicitly**, unlabelled and with defaults.
- **At least one equality filter is required** in `TS.QUERYINDEX`/`FILTER`.
- **Without `ALIGN`, buckets are epoch-aligned**, not aligned to your window.
- **`TS.DEL` ranges are inclusive** at both ends.
- **`TS.GET` returns `(timestamp, value)`**, a tuple, not just the value.
- **`LATEST` is needed to see the still-open compaction bucket** — without it,
  a downsampled series appears to lag behind by one bucket.
- **`TS.INFO` returns an object in redis-py**, not a dict.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `TS.CREATE key [RETENTION ms] [ENCODING e] [CHUNK_SIZE n] [DUPLICATE_POLICY p] [LABELS l v ...]` | Create a series |
| `TS.ALTER key [RETENTION ms] [LABELS ...] [DUPLICATE_POLICY p]` | Change retention / labels |
| `TS.ADD key ts value [...] [ON_DUPLICATE p]` | Add a sample (creates the series if absent) |
| `TS.MADD key ts value [key ts value ...]` | Add to several series at once |
| `TS.INCRBY key n [TIMESTAMP ts]` / `TS.DECRBY` | Counter-style updates |
| `TS.DEL key from to` | Delete samples in an inclusive range |
| `TS.GET key [LATEST]` | The most recent sample |
| `TS.RANGE key from to [COUNT n] [AGGREGATION t bucket] [ALIGN a] [FILTER_BY_TS ...] [FILTER_BY_VALUE min max] [EMPTY] [LATEST]` | Range query |
| `TS.REVRANGE key from to [...]` | Range query, newest first |
| `TS.QUERYINDEX filter [filter ...]` | Which series match these labels |
| `TS.MGET FILTER filter [WITHLABELS\|SELECTED_LABELS ...]` | Last sample of every match |
| `TS.MRANGE from to FILTER f [GROUPBY l REDUCE fn] [WITHLABELS] [...]` | Range across matching series |
| `TS.MREVRANGE from to FILTER f [...]` | Same, newest first |
| `TS.CREATERULE src dest AGGREGATION type bucket [align]` | Automatic downsampling |
| `TS.DELETERULE src dest` | Remove a compaction rule |
| `TS.INFO key [DEBUG]` | Chunks, retention, labels, rules |

**Aggregators:** `avg`, `sum`, `min`, `max`, `count`, `first`, `last`, `range`,
`std.p`, `std.s`, `var.p`, `var.s`, `twa`.
