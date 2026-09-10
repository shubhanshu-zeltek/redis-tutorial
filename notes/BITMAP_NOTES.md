# Redis Bitmaps — Notes

Practice script: [`src/bitmap_redis.py`](../src/bitmap_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/strings/bitmaps

---

## What it is

**Not a separate data type.** A bitmap is an ordinary Redis [string](STRING_NOTES.md)
that you address one **bit** at a time instead of one byte at a time.

`TYPE` on a bitmap key returns `string`. `STRLEN` works on it. `GET` returns the
raw bytes. The "bitmap" is entirely in how you choose to read and write it.

The appeal is density: one bit per entity. A million user ids costs **125 KB**,
versus several megabytes for a Set of the same ids.

---

## Key facts

- Max size: **2^32 bits** (512 MB), i.e. offsets `0` to `4,294,967,295`.
- Bits are indexed **from 0**, most-significant-bit-first within each byte.
- **Setting a high offset allocates everything below it.** `SETBIT key 1000000 1`
  immediately allocates ~125 KB, even though only one bit is set. Bitmaps are
  *dense*, unlike [Arrays](ARRAY_NOTES.md), which are sparse.
- Reading a bit past the end is **not an error** — unset bits read as `0`.
- Redis grows the string in whole bytes, so `STRLEN` is `ceil((max_offset+1)/8)`.

---

## Complexity

| Operation | Cost |
|---|---|
| `SETBIT`, `GETBIT` | O(1) |
| `BITCOUNT`, `BITPOS` | O(N) in the size of the range |
| `BITOP` | O(N) in the size of the largest input |

`BITCOUNT` on a huge bitmap is a real cost — Redis is single-threaded, so a
`BITCOUNT` over 512 MB blocks everything. Use the range arguments.

---

## The basic operations

```bash
SETBIT key 42 1      # set bit at offset 42 to 1. Returns the bit's PREVIOUS value.
GETBIT key 42        # read bit at offset 42
STRLEN key           # bytes actually allocated
```

**`SETBIT` returns the old bit, not the new one.** This is the single most
common surprise. It's what makes "did this change anything?" answerable in one
command — `SETBIT` returning `0` means you just flipped it on for the first
time.

---

## Counting

```bash
BITCOUNT key                  # count of set bits in the whole string
BITCOUNT key 0 5              # BYTE range: bytes 0..5, i.e. bit offsets 0..47
BITCOUNT key 0 100 BIT        # BIT range: bit offsets 0..100  (Redis 7.0+)
```

**The `BYTE`/`BIT` distinction matters.** Without the `BIT` keyword, `start` and
`end` are **byte** offsets, so `BITCOUNT key 0 5` covers ids 0-47, not 0-5. The
`BIT` modifier (Redis 7.0+) makes them mean what you probably intended.

Both forms accept negative indexes, counting from the end.

---

## Searching

```bash
BITPOS key 1              # offset of the first SET bit
BITPOS key 0              # offset of the first CLEAR bit
BITPOS key 1 2            # search from byte 2 onward
BITPOS key 1 0 -1 BIT     # search a BIT range (Redis 7.0+)
```

**Gotcha:** `BITPOS key 0` on a string of all-ones returns the offset *just past*
the end of the string, because Redis treats the (nonexistent) space beyond the
value as zeros. If you specify an explicit range, it returns `-1` instead.

---

## Combining bitmaps

```bash
BITOP AND dest src1 src2 [src3 ...]
BITOP OR  dest src1 src2 [src3 ...]
BITOP XOR dest src1 src2 [src3 ...]
BITOP NOT dest src                   # NOT takes EXACTLY one source
```

The result is written to `dest` and the length of `dest` is returned (in bytes,
equal to the longest input). Shorter inputs are treated as zero-padded.

**`BITOP NOT` inverts whole bytes.** If your bitmap only meaningfully covers ids
0-300, the `NOT` result will have every padding bit up to the byte boundary set
too, and `BITCOUNT` on it will be misleadingly large. Only trust `NOT` results
within a range you explicitly bound.

Newer Redis versions also add `DIFF`, `DIFF1`, `ANDOR`, and `ONE` operations to
`BITOP`; check `COMMAND DOCS BITOP` on your server for what it actually supports.

---

## Bitmaps vs. the alternatives

| Want | Use |
|---|---|
| Dense integer ids, membership only | **Bitmap** |
| Sparse or non-integer members | [Set](SET_NOTES.md) |
| Approximate distinct count, no membership | [HyperLogLog](HYPERLOGLOG_NOTES.md) |
| Approximate membership, tiny memory | [Bloom filter](BLOOM_FILTER_NOTES.md) |
| Small integers, not single bits | [Bitfield](BITFIELD_NOTES.md) |

The decision hinges on **density**. Bitmaps win when ids are contiguous integers
and a good fraction of them are set. With 100 users out of an id space of
10,000,000, a bitmap wastes 1.25 MB to store 100 bits — a Set would be far
cheaper.

---

## Gotchas worth remembering

- **`SETBIT` returns the OLD bit.** Not the new one, not success.
- **Byte ranges vs bit ranges** in `BITCOUNT`/`BITPOS` — add `BIT` to get bit
  semantics (Redis 7.0+).
- **A high offset pre-allocates everything below it**, and that allocation is
  immediate and permanent until the key is deleted.
- **`BITOP NOT` sets padding bits**, inflating any subsequent `BITCOUNT`.
- **`BITPOS key 0` can return an offset past the end** of the string.
- The bitmap is a string, so `DEL`, `EXPIRE`, `TTL`, `RENAME`, `TYPE` all behave
  exactly as they do for strings.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `SETBIT key offset 0\|1` | Set a bit; returns its **previous** value |
| `GETBIT key offset` | Read a bit (out-of-range reads as `0`) |
| `BITCOUNT key [start end [BYTE\|BIT]]` | Count set bits, optionally in a range |
| `BITPOS key 0\|1 [start [end [BYTE\|BIT]]]` | Offset of the first matching bit |
| `BITOP AND\|OR\|XOR dest src [src ...]` | Bitwise fold across bitmaps |
| `BITOP NOT dest src` | Bitwise NOT (exactly one source) |
| `STRLEN key` | Bytes allocated for the bitmap |
| `GET key` | The raw bytes (it's a string, after all) |

Everything in the [string key-lifecycle section](STRING_NOTES.md#key-lifecycle-not-string-specific-but-used-constantly-with-strings)
(`DEL`, `EXPIRE`, `TTL`, `COPY`, `TYPE`, …) applies unchanged.
