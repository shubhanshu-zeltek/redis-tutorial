# Redis Streams — Notes

Practice script: [`src/stream_redis.py`](../src/stream_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/streams

---

## What it is

An **append-only log**. Each entry has an auto-generated, monotonically
increasing **id** and a flat map of field/value pairs — like a hash per entry.

Unlike a [list](LIST_NOTES.md) used as a queue, reading from a stream does not
consume it. Entries stay until you explicitly trim or delete them, and multiple
independent readers can each track their own position.

The part that makes streams genuinely different from every other Redis type is
**consumer groups**: server-side tracking of which entries have been delivered
to whom, which have been acknowledged, and which are stuck.

---

## Entry ids

Format: **`<milliseconds>-<sequence>`**, e.g. `1789051038208-0`.

| Id form | Meaning |
|---|---|
| `*` | Let Redis generate the id (in `XADD`) |
| `<ms>-<seq>` | An explicit id |
| `<ms>-*` | Explicit millisecond, auto sequence |
| `-` | The minimum possible id (in ranges) |
| `+` | The maximum possible id (in ranges) |
| `$` | "Only entries arriving **after** now" (in `XREAD`) |
| `>` | "Entries never delivered to this group" (in `XREADGROUP` **only**) |
| `(<id>` | Exclusive bound in ranges (Redis 6.2+) |

**Ids only ever increase, and are never reused** — even after `XDEL`. Deleting
an entry does not free its id.

**`$` and `>` are not interchangeable.** `$` is for `XREAD` (fan-out mode);
`>` is for `XREADGROUP` (consumer-group mode). Using `$` in `XREADGROUP` is a
common bug that silently delivers nothing.

---

## Complexity

| Operation | Cost |
|---|---|
| `XADD`, `XLEN` | O(1) |
| `XRANGE`, `XREVRANGE`, `XREAD` | O(log N + M), M = entries returned |
| `XDEL` | O(1) per id |
| `XTRIM` / `XADD MAXLEN` | O(N) evicted; **O(1) amortized with `~`** |
| `XACK`, `XCLAIM` | O(1) per id |
| `XAUTOCLAIM` | O(1) amortized per entry scanned |

---

## Writing

```bash
XADD key * field value [field value ...]        # auto id
XADD key 1000-1 temp 21.5                       # explicit id
XADD key NOMKSTREAM * f v                       # don't create the stream if absent
XADD key MAXLEN 1000 * f v                      # cap length, exact
XADD key MAXLEN ~ 1000 * f v                    # cap length, APPROXIMATE — much cheaper
XADD key MINID ~ 1690000000000 * f v            # evict by id instead of count
```

**The `~` matters a lot.** Exact trimming (`MAXLEN 1000`) has to remove entries
one at a time. Approximate trimming (`MAXLEN ~ 1000`) only drops whole macro
nodes, so it's O(1) amortized — it may leave a few extra entries around, which
is almost always fine. In redis-py this is `approximate=True`, and it is the
**default**.

That default bites: `xtrim(key, maxlen=2)` on a small stream can legitimately
do nothing at all. Pass `approximate=False` when you need an exact result.

`NOMKSTREAM` returns `nil` rather than creating the key.

---

## Trimming and deleting

```bash
XTRIM key MAXLEN [~] 1000
XTRIM key MINID  [~] <id>
XTRIM key MAXLEN ~ 1000 LIMIT 100    # bound the work per call
XDEL key id [id ...]                 # remove specific entries
XSETID key <id>                      # force the stream's last-id
XLEN key
```

`XDEL` removes the entry but **not** its id from the sequence, and does not
affect any consumer group's pending list.

---

## Reading without consumer groups

```bash
XRANGE key - +                # everything, oldest first
XRANGE key - + COUNT 10
XRANGE key <id1> <id2>        # inclusive at both ends
XRANGE key "(<id1>" <id2>     # exclusive start (6.2+)
XREVRANGE key + - COUNT 10    # newest first — note the REVERSED bounds
XREAD COUNT 10 STREAMS key 0            # everything after id 0
XREAD BLOCK 5000 STREAMS key $          # wait up to 5s for NEW entries
XREAD BLOCK 0 STREAMS key1 key2 $ $     # block forever, several streams
```

`XREVRANGE` takes **max first, then min** — the reverse of `XRANGE`.

In this mode **every reader sees every entry**. There's no tracking; each client
remembers its own last-seen id. This is fan-out / pub-sub-with-history.

---

## Consumer groups

The reason to choose a stream over a list.

```bash
XGROUP CREATE key groupname 0             # replay from the beginning
XGROUP CREATE key groupname $             # only new entries from now on
XGROUP CREATE key groupname 0 MKSTREAM    # create the stream too if absent
XGROUP DESTROY key groupname
XGROUP SETID key groupname 0              # rewind/fast-forward the group
XGROUP CREATECONSUMER key groupname consumer
XGROUP DELCONSUMER key groupname consumer
```

Reading as a member of a group:

```bash
XREADGROUP GROUP g c1 COUNT 2 STREAMS key >     # never-delivered entries
XREADGROUP GROUP g c1 COUNT 2 STREAMS key 0     # THIS consumer's own pending entries
XREADGROUP GROUP g c1 BLOCK 5000 STREAMS key >
XREADGROUP GROUP g c1 NOACK STREAMS key >       # skip the PEL entirely
```

The two id forms do completely different things:

- **`>`** — deliver entries no one in the group has seen. Each entry goes to
  exactly **one** consumer, and is recorded in the **PEL**.
- **`<id>` (usually `0`)** — re-deliver *this consumer's* already-pending
  entries. This is how a restarted worker recovers the work it had claimed but
  never finished.

`NOACK` skips PEL tracking entirely — at-most-once delivery, faster, no
recovery.

---

## The PEL (Pending Entries List)

Every entry delivered via `>` is added to the group's PEL, tagged with the
consumer, a delivery timestamp, and a delivery count. It stays there until
**`XACK`**.

```bash
XACK key groupname id [id ...]        # returns how many were actually acked
XPENDING key groupname                # summary: count, min id, max id, per-consumer
XPENDING key groupname - + 10                    # detailed, up to 10 rows
XPENDING key groupname - + 10 consumer1          # filtered to one consumer
XPENDING key groupname IDLE 60000 - + 10         # only entries idle > 60s
```

An unacked entry is a job someone claimed and may have died holding. That's what
makes recovery possible.

---

## Reclaiming stuck work

```bash
XCLAIM key g newconsumer <min-idle-ms> id [id ...]
XCLAIM key g newconsumer 0 id JUSTID          # don't return the payload
XCLAIM key g newconsumer 0 id FORCE           # create a PEL entry even if absent
XAUTOCLAIM key g newconsumer <min-idle-ms> 0-0 [COUNT n] [JUSTID]
```

- **`XCLAIM`** is targeted: you already know which ids to reassign.
- **`XAUTOCLAIM`** (6.2+) scans for you and returns
  `[next_cursor, claimed_entries, deleted_ids]`. Loop on the cursor until it
  comes back `0-0`.

The `min-idle-time` guard prevents two recovery processes from stealing the same
entry from each other — a claim only succeeds if the entry has genuinely been
idle that long.

---

## Introspection

```bash
XINFO STREAM key            # length, radix tree stats, first/last entry, group count
XINFO STREAM key FULL       # plus full PEL contents
XINFO GROUPS key            # per group: consumers, pending, last-delivered-id, LAG
XINFO CONSUMERS key group   # per consumer: pending count, idle time, inactive time
```

**`lag`** in `XINFO GROUPS` is the number of entries the group has not yet
delivered — the "how far behind are we" metric worth alerting on. It can be
reported as `nil` when Redis can't compute it exactly (usually after `XDEL`s).

---

## Streams vs. lists as a queue

| | List | Stream |
|---|---|---|
| Reading consumes | Yes (`LPOP`) | No — entries persist |
| Multiple independent readers | No | Yes |
| Server tracks delivery | No | Yes (PEL) |
| Acknowledgement | No | `XACK` |
| Recover a crashed worker's job | Manual (`LMOVE` pattern) | Built in (`XCLAIM`/`XAUTOCLAIM`) |
| History / replay | No | Yes |
| Memory | Lower | Higher |

Use a list when the queue is simple and throughput matters. Use a stream when
you need acknowledgement, replay, several consumer groups over the same data, or
crash recovery.

---

## Gotchas worth remembering

- **`$` vs `>`.** `$` for `XREAD`, `>` for `XREADGROUP`. Mixing them delivers
  nothing and looks like a hang.
- **`XREVRANGE` takes max before min.**
- **`approximate=True` is the redis-py default** for `XADD`/`XTRIM` maxlen — an
  exact trim needs `approximate=False`, and without it small-stream trims can
  silently do nothing.
- **Ids are never reused**, even after `XDEL`.
- **`XDEL` does not clear the PEL.** An acked-but-deleted entry and a
  deleted-but-unacked entry are different states.
- **Creating a group with `$` means it sees nothing that already exists.** Use
  `0` to replay history.
- **`XGROUP CREATE` errors if the stream doesn't exist** unless you pass
  `MKSTREAM`.
- **A consumer is created implicitly** the first time it reads — you rarely need
  `XGROUP CREATECONSUMER`.
- **Consumer groups don't expire.** A consumer that disappears leaves its PEL
  entries stuck forever until something claims them. Idle consumers accumulate;
  clean them up with `XGROUP DELCONSUMER`.
- **`XAUTOCLAIM` returns a 3-tuple** (cursor, entries, deleted ids) — the third
  element is easy to forget when unpacking.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `XADD key [NOMKSTREAM] [MAXLEN\|MINID [~] n] <*\|id> f v [f v ...]` | Append an entry |
| `XLEN key` | Number of entries |
| `XRANGE key start end [COUNT n]` | Range, oldest first |
| `XREVRANGE key end start [COUNT n]` | Range, newest first (**bounds reversed**) |
| `XDEL key id [id ...]` | Delete entries |
| `XTRIM key MAXLEN\|MINID [~] n [LIMIT m]` | Trim the stream |
| `XSETID key id` | Force the last-generated id |
| `XREAD [COUNT n] [BLOCK ms] STREAMS key [key ...] id [id ...]` | Read, no group |
| `XGROUP CREATE key g id [MKSTREAM]` | Create a consumer group |
| `XGROUP DESTROY key g` | Delete a group |
| `XGROUP SETID key g id` | Move the group's position |
| `XGROUP CREATECONSUMER\|DELCONSUMER key g c` | Manage consumers |
| `XREADGROUP GROUP g c [COUNT n] [BLOCK ms] [NOACK] STREAMS key >\|id` | Read as a group member |
| `XACK key g id [id ...]` | Acknowledge; removes from the PEL |
| `XPENDING key g` | PEL summary |
| `XPENDING key g [IDLE ms] start end count [consumer]` | PEL detail |
| `XCLAIM key g c min-idle-ms id [...] [JUSTID] [FORCE]` | Reassign specific entries |
| `XAUTOCLAIM key g c min-idle-ms start [COUNT n] [JUSTID]` | Scan and reassign (6.2+) |
| `XINFO STREAM key [FULL]` | Stream metadata |
| `XINFO GROUPS key` | Per-group state, including `lag` |
| `XINFO CONSUMERS key g` | Per-consumer state |
