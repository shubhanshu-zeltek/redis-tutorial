# Redis Vector Sets — Notes

Practice script: [`src/vector_set_redis.py`](../src/vector_set_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/vector-sets

---

## What it is

A [sorted set](SORTED_SET_NOTES.md), but ordered by **vector similarity**
instead of a numeric score.

Each element carries a high-dimensional vector. `VSIM` returns the elements
whose vectors point most nearly the same direction — **cosine similarity** —
backed by an **HNSW** (Hierarchical Navigable Small World) graph so search stays
fast as the set grows.

This is the native building block for semantic search, recommendations and RAG
retrieval. The part that makes it more than a vector index is **filtered
search**: each element can carry JSON attributes, and `VSIM` can apply a
predicate over them during the graph traversal.

---

## Requirements

**Redis 8.0+.** Vector sets are not in Redis 7.x, and were not in the
`redis/redis-stack` image at the time these notes were written. Verified
against `redis:8-alpine` (8.10.1):

```bash
docker run -d --rm --name redis8 -p 6380:6379 redis:8-alpine
python src/vector_set_redis.py 6380
```

**In redis-py the commands live behind the `.vset()` accessor** —
`client.vset().vadd(...)`, **not** `client.vadd(...)`. Calling them on the
client directly raises `AttributeError: 'Redis' object has no attribute 'vadd'`.

---

## Adding vectors

```bash
VADD key [REDUCE dim] (FP32 <blob> | VALUES <n> <v1> ... <vn>) <element>
         [CAS] [NOQUANT|Q8|BIN] [EF n] [SETATTR <json>] [M n]
```

```bash
VADD catalog VALUES 4 0.9 0.1 0.05 0.2 keyboard SETATTR '{"price":4999,"stock":12}'
```

| Option | Effect |
|---|---|
| `REDUCE dim` | Random-projection the vector down to `dim` before storing |
| `CAS` | Do the expensive graph insert without holding the lock |
| `NOQUANT` / `Q8` / `BIN` | Quantization (see below) |
| `EF n` | Build-time search effort — higher builds a better graph, slower |
| `SETATTR json` | Attach JSON attributes |
| `M n` | HNSW links per node (`numlinks`) |

**The vector dimension is fixed by the first `VADD`.** Every later element must
match, or you get an error. If you use `REDUCE`, the stored dimension is the
reduced one — `VDIM` reports the projected size, not the input size.

---

## Quantization

The memory/recall dial, chosen at first insert:

| Option | Storage | Notes |
|---|---|---|
| `NOQUANT` | full float32 | Best recall, most memory |
| `Q8` | int8 | **The default.** Near-full recall at ~4× less memory |
| `BIN` | 1 bit per dimension | Smallest, big recall loss |

Measured on the 8-element, 4-dimensional toy set in the practice script:
`NOQUANT` and `Q8` both ranked correctly; **`BIN` produced nonsense**, because
collapsing 4 dimensions to 4 bits discards essentially everything. On real
768- or 1536-dimensional embeddings `BIN` holds up far better — the toy result
is a property of the tiny dimension, not a bug.

**`VEMB` returns the stored, quantized vector**, so it will not equal what you
inserted. Add `RAW` to see the internal representation plus its quantization
metadata.

In redis-py, quantization must be a **`QuantizationOptions` enum member**, not
a string:

```python
from redis.commands.vectorset.commands import QuantizationOptions
client.vset().vadd(key, vec, elem, quantization=QuantizationOptions.Q8)
```

Passing `"Q8"` fails with `AttributeError: 'str' object has no attribute
'value'`.

---

## Searching

```bash
VSIM key (ELE <element> | FP32 <blob> | VALUES <n> <v...>)
         [WITHSCORES] [WITHATTRIBS] [COUNT n] [EF n]
         [FILTER <expr>] [FILTER-EF n] [TRUTH] [NOTHREAD] [EPSILON e]
```

Two ways to specify the query:

```bash
VSIM catalog ELE keyboard WITHSCORES              # "more like this"
VSIM catalog VALUES 4 0.85 0.15 0.05 0.2 COUNT 3  # a raw query vector
```

The second is the semantic-search path: embed the user's text with your model,
hand the vector straight to `VSIM`.

**Scores are cosine similarity normalised to `0..1`**, where `1.0` is identical
and `0.0` is opposite. Higher is better — the reverse of a distance metric, and
worth double-checking if you're porting code from another vector database.

| Option | Effect |
|---|---|
| `COUNT n` | Return at most `n` results |
| `WITHSCORES` | Include similarity scores |
| `WITHATTRIBS` | Include each element's JSON attributes |
| `EF n` | Search effort — higher is more accurate and slower |
| `TRUTH` | **Exact linear scan.** The ground truth to validate against |
| `NOTHREAD` | Run in the main thread instead of a background one |

---

## Filtered (hybrid) search

```bash
VSIM catalog ELE keyboard FILTER '.stock > 0'
VSIM catalog ELE monitor  FILTER '.price < 20000'
VSIM catalog ELE keyboard FILTER '.category == "peripherals" and .stock > 5'
```

The filter expression addresses attributes with a **leading dot** and supports
comparisons, `and`/`or`/`not`, and `in`.

**`FILTER-EF`** controls how many candidates the graph traversal examines
before giving up. With a very restrictive filter, the default effort may find
too few matches — raise `FILTER-EF` when a filtered search returns fewer
results than you expect. This is the most common tuning knob in practice.

Attributes are live: `VSETATTR` to change one, and the next filtered search
reflects it immediately.

---

## Other commands

```bash
VDIM key                       # stored dimension (post-REDUCE)
VCARD key                      # number of elements
VREM key element               # remove from the set and the graph
VEMB key element [RAW]         # the stored vector
VLINKS key element [WITHSCORES]  # HNSW neighbours, per graph layer
VGETATTR key element           # read JSON attributes
VSETATTR key element <json>    # write JSON attributes (empty string clears)
VRANDMEMBER key [count]        # random element(s); negative count allows repeats
VRANGE key <start> <end> [COUNT n]   # LEXICOGRAPHIC range, ignoring similarity
VINFO key                      # dimension, quantization, HNSW params, node counts
```

**`VRANGE` has nothing to do with similarity** — it's a plain lexicographic
range over element names, using the same `[`/`(`/`-`/`+` bound syntax as
[`ZRANGEBYLEX`](SORTED_SET_NOTES.md#3-by-lexicographic-order). Useful for
enumerating or paging through elements, not for search.

`VLINKS` exposes the raw HNSW graph structure — diagnostic, not something an
application normally calls.

---

## Vector sets vs. the search module

Redis has two ways to do vector similarity:

| | Vector sets (`V*`) | Search module (`FT.*`) |
|---|---|---|
| Availability | Redis 8.0+, core | Redis Stack / Redis 8 |
| Distance metrics | Cosine only | Cosine, L2, inner product |
| Index types | HNSW | HNSW and FLAT |
| Filtering | JSON attributes, `FILTER` expression | Full query language over indexed fields |
| Setup | None — just `VADD` | Define a schema, create an index |
| Combine with full-text search | No | Yes |

Vector sets are the lightweight option: no schema, no index definition, one
command to start. Use the search module when you need multiple metrics, full
text, or complex structured queries alongside the vectors.

---

## Gotchas worth remembering

- **redis-py needs `.vset()`.** `client.vadd(...)` does not exist.
- **Quantization must be a `QuantizationOptions` enum**, not a string.
- **Higher score = more similar.** These are similarities, not distances.
- **Dimension is locked by the first `VADD`.**
- **`VEMB` doesn't return what you inserted** — it's quantized.
- **`BIN` quantization needs high dimensionality** to be usable at all.
- **`VRANGE` is lexicographic**, not similarity-ordered.
- **A restrictive `FILTER` can silently under-return.** Raise `FILTER-EF`.
- **`REDUCE` changes what `VDIM` reports** — the projected dimension, not the
  input.
- **Cosine similarity ignores magnitude.** Normalise your embeddings if
  magnitude carries meaning; most embedding models already produce normalised
  vectors.
- **Not in Redis 7 or the current Redis Stack image.** Check
  `INFO server` → `redis_version` before assuming availability.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `VADD key [REDUCE d] VALUES n v... element [CAS] [NOQUANT\|Q8\|BIN] [EF n] [SETATTR json] [M n]` | Add an element with its vector |
| `VSIM key ELE e \| VALUES n v... [WITHSCORES] [WITHATTRIBS] [COUNT n] [EF n] [FILTER expr] [FILTER-EF n] [TRUTH] [NOTHREAD] [EPSILON e]` | Similarity search |
| `VDIM key` | Stored vector dimension |
| `VCARD key` | Number of elements |
| `VREM key element` | Remove an element |
| `VEMB key element [RAW]` | The stored (quantized) vector |
| `VLINKS key element [WITHSCORES]` | HNSW neighbours per layer |
| `VGETATTR key element` | Read JSON attributes |
| `VSETATTR key element json` | Write JSON attributes |
| `VRANDMEMBER key [count]` | Random element(s) |
| `VRANGE key start end [COUNT n]` | **Lexicographic** range over element names |
| `VINFO key` | Dimension, quantization, HNSW parameters, node counts |
