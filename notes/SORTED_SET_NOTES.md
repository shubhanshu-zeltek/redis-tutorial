# Redis Sorted Sets — Notes

Practice script: [`src/sorted_set_redis.py`](../src/sorted_set_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/sorted-sets

---

## What it is

A [Set](SET_NOTES.md) where every member carries a **float score**, and Redis
keeps the members permanently ordered by that score.

**Members are unique. Scores are not.** When two members share a score, they are
ordered **lexicographically by the member string** — that tie-breaking rule is
not a detail, it is what makes the whole `BYLEX` family work.

Probably the most versatile type Redis has: the same structure serves as a
leaderboard, a priority queue, a time index, a rate limiter, and a secondary
index, depending only on what you put in the score.

---

## Key facts

- Scores are **IEEE 754 double-precision floats**. Integers above 2^53 lose
  precision — relevant if you store nanosecond timestamps as scores.
- Special score values: `+inf`, `-inf`, and `nan` is rejected.
- Max members: **2^32 - 1**.
- Removing the last member **deletes the key**.
- Ranks are **0-based**. `ZRANK` counts from the lowest score, `ZREVRANK` from
  the highest.
- Internally a **skip list plus a hash table**, which is why both "rank of a
  member" and "score of a member" are fast.

---

## Complexity

| Operation | Cost |
|---|---|
| `ZADD`, `ZSCORE`, `ZINCRBY`, `ZREM`, `ZRANK` | O(log N) |
| `ZCARD` | O(1) |
| `ZRANGE` and friends | O(log N + M), M = elements returned |
| `ZCOUNT`, `ZLEXCOUNT` | O(log N) |
| `ZPOPMIN` / `ZPOPMAX` | O(log N) |
| `ZUNIONSTORE` / `ZINTERSTORE` | O(N log N) roughly, N = total input members |
| `ZRANDMEMBER`, `ZSCAN` | O(1) / O(N) per call |

`ZCOUNT` is O(log N) — it does **not** walk the range, it locates both ends in
the skip list. `ZRANGE` is the one that costs per element returned.

---

## Adding and updating

```bash
ZADD key 100 member
ZADD key 100 m1 200 m2 300 m3      # several at once
```

The flags are where the real behaviour lives:

| Flag | Meaning |
|---|---|
| `NX` | Only **add new** members; never update an existing member's score |
| `XX` | Only **update existing** members; never add new ones |
| `GT` | Only update if the new score is **greater** than the current one |
| `LT` | Only update if the new score is **less** than the current one |
| `CH` | Change the return value to "members **changed**" (added *or* updated) |
| `INCR` | Behave like `ZINCRBY` — add to the score, return the new score |

```bash
ZADD key GT CH 500 player     # only ever raise a high score; report if it changed
ZADD key NX 50 newcomer       # register a player without resetting an existing one
ZADD key INCR 10 player       # == ZINCRBY key 10 player
```

**`GT` is the correct way to record a high score.** Without it you need a
read-compare-write, which is a race. `GT`/`LT` were added in Redis 6.2.

`NX` and `XX` are mutually exclusive, as are `GT`/`LT`/`NX`.

**By default `ZADD` returns only the number of NEW members**, so updating an
existing score returns `0`. Add `CH` if you want "how many rows did this touch".

```bash
ZINCRBY key 50 member     # add to a score; creates the member at 0 if missing
```

---

## Reading scores and ranks

```bash
ZSCORE key member              # nil if absent
ZMSCORE key m1 m2 m3           # several at once (6.2+); nil per missing member
ZCARD key                      # number of members
ZCOUNT key 1000 2000           # members with a score in a range
ZRANK key member               # 0-based rank, LOWEST score first
ZREVRANK key member            # 0-based rank, HIGHEST score first
ZRANK key member WITHSCORE     # rank + score in one call (7.2+)
```

---

## Range queries — the three coordinate systems

A sorted set can be sliced three different ways, and mixing them up is the
usual source of confusion:

### 1. By rank (index)

```bash
ZRANGE key 0 -1               # everything, lowest score first
ZRANGE key 0 9                # the ten lowest
ZRANGE key 0 9 REV            # the ten HIGHEST
ZRANGE key 0 -1 WITHSCORES
```

### 2. By score

```bash
ZRANGE key 1000 2000 BYSCORE
ZRANGE key "(1000" "+inf" BYSCORE        # '(' = exclusive bound
ZRANGE key 1000 2000 BYSCORE LIMIT 0 10  # LIMIT requires BYSCORE or BYLEX
ZRANGEBYSCORE key 1000 2000              # older dedicated command
ZREVRANGEBYSCORE key 2000 1000           # note: max comes FIRST
```

Bounds: a bare number is inclusive, `(` prefixes an exclusive bound, and
`-inf` / `+inf` are valid.

### 3. By lexicographic order

**Only meaningful when every member has the SAME score.** With equal scores the
set is ordered purely by member string, so you can do prefix range queries:

```bash
ZRANGE key "[redis" "[redis\xff" BYLEX
ZRANGEBYLEX key "[redis" "[redis\xff"
ZLEXCOUNT key "[redis" "[redis\xff"
```

Lex bound syntax is its own little language:

| Bound | Meaning |
|---|---|
| `[value` | Inclusive |
| `(value` | Exclusive |
| `-` | Negative infinity (the very first member) |
| `+` | Positive infinity (the very last member) |

The `"[prefix"` to `"[prefix\xff"` idiom is the standard prefix-match trick.

**If the scores are not all equal, `BYLEX` results are undefined.** Not an
error — just meaningless.

### And storing the result

```bash
ZRANGESTORE dst src 0 9 REV     # write a range into another sorted set (6.2+)
```

---

## The modern vs. legacy range commands

Redis 6.2 unified everything into `ZRANGE` with `BYSCORE` / `BYLEX` / `REV`
modifiers. The older commands still work and are not deprecated in practice:

| Legacy | Modern equivalent |
|---|---|
| `ZREVRANGE key 0 9` | `ZRANGE key 0 9 REV` |
| `ZRANGEBYSCORE key min max` | `ZRANGE key min max BYSCORE` |
| `ZREVRANGEBYSCORE key max min` | `ZRANGE key min max BYSCORE REV` |
| `ZRANGEBYLEX key min max` | `ZRANGE key min max BYLEX` |
| `ZREVRANGEBYLEX key max min` | `ZRANGE key min max BYLEX REV` |

**Watch the argument order on the `REV` legacy forms — max comes first.**

---

## Popping (priority-queue behaviour)

```bash
ZPOPMIN key [count]       # remove and return the lowest-scored member(s)
ZPOPMAX key [count]       # highest
BZPOPMIN key [key ...] timeout   # blocking; returns [key, member, score]
BZPOPMAX key [key ...] timeout
ZMPOP  numkeys key [key ...] MIN|MAX [COUNT n]        # 7.0+
BZMPOP timeout numkeys key [key ...] MIN|MAX [COUNT n]
```

Score = priority, `ZPOPMIN` = "next job". Blocking forms let workers wait
without polling, exactly as with [lists](LIST_NOTES.md).

`timeout` is in seconds and **`0` blocks forever**.

---

## Removing

```bash
ZREM key m [m ...]
ZREMRANGEBYRANK key 0 9              # drop the ten lowest-ranked
ZREMRANGEBYSCORE key "-inf" "(1000"  # drop everything below 1000
ZREMRANGEBYLEX key "[a" "[b"         # equal-scores sets only
```

`ZREMRANGEBYSCORE` is the workhorse for eviction — trimming a time-indexed
sorted set down to a window is a single command.

---

## Set algebra, score-aware

```bash
ZUNION  numkeys key [key ...] [WEIGHTS w ...] [AGGREGATE SUM|MIN|MAX] [WITHSCORES]
ZINTER  numkeys key [key ...] [WEIGHTS w ...] [AGGREGATE SUM|MIN|MAX] [WITHSCORES]
ZDIFF   numkeys key [key ...] [WITHSCORES]
ZUNIONSTORE dst numkeys key [...] [WEIGHTS ...] [AGGREGATE ...]
ZINTERSTORE dst numkeys key [...]
ZDIFFSTORE  dst numkeys key [...]
ZINTERCARD  numkeys key [...] [LIMIT n]     # 7.0+
```

The score-aware part: when a member appears in several inputs, its resulting
score is combined with **`AGGREGATE`**, which defaults to **`SUM`**. `MIN` and
`MAX` are the alternatives.

**`WEIGHTS` multiplies each input set's scores before aggregating** — the way
to say "this season counts double".

`ZDIFF` uses only membership, not scores, and takes the first key as the base.

In redis-py, weights are expressed by passing a **dict** instead of a list:
`zunion({key1: 1, key2: 2}, withscores=True)`.

---

## Random and iteration

```bash
ZRANDMEMBER key                  # one random member
ZRANDMEMBER key 3                # 3 distinct
ZRANDMEMBER key -5               # 5, repeats allowed
ZRANDMEMBER key 3 WITHSCORES
ZSCAN key 0 [MATCH p] [COUNT n]  # cursor iteration; returns member/score pairs
```

Same negative-count semantics as `SRANDMEMBER` and `HRANDFIELD`.

---

## Internal encoding

```bash
OBJECT ENCODING key
```

| Encoding | When |
|---|---|
| `listpack` | Small sorted sets — a flat member/score array, scanned linearly |
| `skiplist` | Larger — skip list + hash table |

Thresholds: `zset-max-listpack-entries` (default 128) and
`zset-max-listpack-value` (default 64 bytes). One-way conversion.

---

## Gotchas worth remembering

- **Ties break lexicographically by member.** Two players on 2300 always sort
  `arjun` before `kabir`, regardless of insertion order.
- **`ZADD` returns new members only** unless you pass `CH`.
- **`BYLEX` is garbage unless all scores are equal.** It fails silently.
- **`LIMIT` requires `BYSCORE` or `BYLEX`** — you can't `LIMIT` a rank range.
- **Legacy `ZREVRANGEBYSCORE` takes max before min.**
- **Scores are doubles.** Integers beyond 2^53 silently lose precision.
- **`AGGREGATE` defaults to `SUM`**, which quietly doubles scores for members
  present in two sets — often not what you meant.
- **`ZINTERCARD` / `ZMPOP` take `numkeys` first**, and redis-py wants the keys
  as a list.
- **`ZRANK` is 0-based** — the top player has `ZREVRANK` of `0`, not `1`.
- **`BZPOPMIN` returns `[key, member, score]`**, three elements, because you may
  have been watching several keys.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `ZADD key [NX\|XX] [GT\|LT] [CH] [INCR] score m [score m ...]` | Add / update members |
| `ZINCRBY key n m` | Add `n` to a member's score |
| `ZSCORE key m` / `ZMSCORE key m [m ...]` | Score of one / several members |
| `ZCARD key` | Number of members |
| `ZCOUNT key min max` | Members within a score range |
| `ZLEXCOUNT key min max` | Members within a lex range |
| `ZRANK key m [WITHSCORE]` | 0-based rank, lowest first |
| `ZREVRANK key m [WITHSCORE]` | 0-based rank, highest first |
| `ZRANGE key start stop [BYSCORE\|BYLEX] [REV] [LIMIT o n] [WITHSCORES]` | The unified range query |
| `ZREVRANGE` / `ZRANGEBYSCORE` / `ZREVRANGEBYSCORE` / `ZRANGEBYLEX` / `ZREVRANGEBYLEX` | Legacy range forms |
| `ZRANGESTORE dst src start stop [...]` | Store a range into another key (6.2+) |
| `ZREM key m [m ...]` | Remove members |
| `ZREMRANGEBYRANK key start stop` | Remove by rank |
| `ZREMRANGEBYSCORE key min max` | Remove by score |
| `ZREMRANGEBYLEX key min max` | Remove by lex range |
| `ZPOPMIN key [count]` / `ZPOPMAX key [count]` | Pop lowest / highest |
| `BZPOPMIN` / `BZPOPMAX key [key ...] timeout` | Blocking pop; `0` = forever |
| `ZMPOP numkeys key [...] MIN\|MAX [COUNT n]` | Pop from the first non-empty (7.0+) |
| `BZMPOP timeout numkeys key [...] MIN\|MAX [COUNT n]` | Blocking `ZMPOP` |
| `ZUNION` / `ZINTER` / `ZDIFF numkeys key [...]` | Set algebra, returning members |
| `ZUNIONSTORE` / `ZINTERSTORE` / `ZDIFFSTORE dst numkeys key [...]` | ...storing the result |
| `ZINTERCARD numkeys key [...] [LIMIT n]` | Intersection **size** only (7.0+) |
| `ZRANDMEMBER key [count] [WITHSCORES]` | Random member(s) |
| `ZSCAN key cursor [MATCH p] [COUNT n]` | Cursor iteration |
| `OBJECT ENCODING key` | `listpack` / `skiplist` |

---

## Sorted sets vs. the alternatives

| Want | Use |
|---|---|
| Unique members ordered by a score you control | **Sorted set** |
| Unique members, no order needed | [Set](SET_NOTES.md) |
| Insertion order, duplicates allowed | [List](LIST_NOTES.md) |
| Timestamped numeric samples with retention & aggregation | [Time series](TIMESERIES_NOTES.md) |
| Locations on a map | [Geospatial](GEOSPATIAL_NOTES.md) — literally a sorted set |
| An append-only log with consumer groups | [Stream](STREAM_NOTES.md) |
