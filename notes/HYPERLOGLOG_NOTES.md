# Redis HyperLogLog — Notes

Practice script: [`src/hyperloglog_redis.py`](../src/hyperloglog_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/probabilistic/hyperloglogs

---

## What it is

Counts **distinct items** in roughly **12 KB**, regardless of whether you feed
it a hundred items or a billion.

The trade is absolute: you get the **count** and nothing else. You cannot ask
"is X in there?", you cannot list the members, you cannot remove anything.
There is no `PFMEMBERS`, and there never will be — the structure does not
retain the items.

---

## Key facts

- **Fixed size: 12 KB** at full (dense) encoding. Small cardinalities use a
  sparse encoding and take far less.
- **Standard error ≈ 0.81%.** Measured in the practice script: 100,000 distinct
  items estimated as 100,479 — a 0.479% error.
- **No module required.** HLLs are stored as ordinary Redis strings, so
  `STRLEN`, `DEL`, `EXPIRE`, `TYPE` (returns `string`) all work.
- **Not exact, ever** — but the error is bounded and does not grow with
  cardinality.
- Max cardinality it can represent: about 2^64.

---

## Complexity

| Operation | Cost |
|---|---|
| `PFADD` | O(1) per element |
| `PFCOUNT` on one key | O(1) |
| `PFCOUNT` on N keys | O(N) — and it computes the union on the fly |
| `PFMERGE` | O(N) in the number of source keys |

`PFCOUNT` on a single key is technically a write command — it may cache the
computed cardinality inside the value.

---

## The commands

There are only three you'll ever use.

```bash
PFADD key element [element ...]
PFCOUNT key [key ...]
PFMERGE destkey sourcekey [sourcekey ...]
```

That's the entire API.

---

## `PFADD`

```bash
PFADD visitors user:1 user:2 user:3
```

Returns **`1` if the internal registers changed**, `0` if nothing new was
observed. It is *not* a count of added elements.

Because the structure is approximate, `PFADD` returning `0` is a hint, not a
guarantee, that the item was already present. Don't build membership logic on
it — that's what a [Bloom filter](BLOOM_FILTER_NOTES.md) is for.

`PFADD key` with **no elements** creates an empty HLL, which is occasionally
useful for initialization.

---

## `PFCOUNT`

```bash
PFCOUNT visitors                  # cardinality of one HLL
PFCOUNT day:1 day:2 day:3         # cardinality of their UNION
```

**Multi-key `PFCOUNT` computes the union without storing it.** This is the
feature people miss: you don't need to `PFMERGE` first to answer "how many
unique users across these seven days?".

The union is a genuine set union — users appearing on several days are counted
once.

---

## `PFMERGE`

```bash
PFMERGE week:37 day:1 day:2 day:3
```

Materialises the union into `destkey`. The destination is still 12 KB — merging
does not accumulate size.

**Merging is idempotent.** Re-merging the same sources changes nothing, so a
rollup job that runs twice is harmless. If `destkey` already exists it is
included in the union rather than overwritten, which is what makes incremental
rollups work:

```bash
PFMERGE week:37 day:4      # adds day 4 into the existing weekly rollup
```

---

## Sparse vs dense encoding

Redis starts an HLL in a **sparse** encoding that costs far less than 12 KB for
small cardinalities, then converts to **dense** once it grows past
`hll-sparse-max-bytes` (default 3000).

In the practice script: 4 items → 30 bytes; 100,000 items → 12,304 bytes.

The conversion is **one-way** and automatic. It's transparent to your code, but
it explains why a nearly-empty HLL isn't 12 KB.

---

## Choosing between the approximate structures

| Question | Structure |
|---|---|
| **How many distinct?** | **HyperLogLog** |
| Have I seen this before? | [Bloom](BLOOM_FILTER_NOTES.md) / [Cuckoo](CUCKOO_FILTER_NOTES.md) |
| How often has this appeared? | [Count-min sketch](COUNT_MIN_SKETCH_NOTES.md) |
| Which items are most frequent? | [Top-K](TOP_K_NOTES.md) |
| What's the p99? | [t-digest](T_DIGEST_NOTES.md) |

And versus the exact alternative:

| | Set | HyperLogLog |
|---|---|---|
| Exact count | Yes | No (~0.81% error) |
| Membership test | Yes | **No** |
| List members | Yes | **No** |
| Remove a member | Yes | **No** |
| Memory for 100k items | ~500 KB+ | **12 KB** |
| Memory for 1 billion items | Hundreds of GB | **12 KB** |

Use a [Set](SET_NOTES.md) until the memory hurts. That's the only reason to
switch — you're giving up every capability except counting.

---

## Gotchas worth remembering

- **`PFADD` returns 0/1 for "registers changed", not the number added.**
- **There is no way to get the items back.** No `PFMEMBERS`, no iteration, no
  deletion of individual elements.
- **You cannot un-add.** The only way to shrink an HLL is `DEL` and rebuild.
- **`PFCOUNT` accepts multiple keys** — you rarely need `PFMERGE` just to get a
  union count.
- **`PFMERGE` includes the existing destination** in the union rather than
  replacing it.
- **The error is a percentage, not a constant.** At 100 items ~0.81% is under
  one item, so small counts often look exact. They are not guaranteed to be.
- **It's a string.** `TYPE` returns `string`, and you can accidentally destroy
  an HLL with `SET` or `APPEND`. Redis will reject `PFADD` on a string that
  isn't a valid HLL ("WRONGTYPE Key is not a valid HyperLogLog string value").
- **Don't compare HLL byte contents** to test equality — two HLLs with the same
  cardinality can differ, and the sparse/dense encoding changes the bytes.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `PFADD key [element ...]` | Add element(s); returns `1` if the registers changed |
| `PFCOUNT key [key ...]` | Approximate cardinality; several keys = union |
| `PFMERGE dest source [source ...]` | Union sources (and any existing dest) into dest |
| `STRLEN key` | Bytes used (it's a string) |
| `PFDEBUG` / `PFSELFTEST` | Internal debugging commands, not for application use |
