# Redis Bitfields — Notes

Practice script: [`src/bitfield_redis.py`](../src/bitfield_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/strings/bitfields

---

## What it is

Like [bitmaps](BITMAP_NOTES.md), **not a separate data type** — a bitfield is an
ordinary [string](STRING_NOTES.md) treated as an array of **small integers of
arbitrary bit width**, packed end to end.

Where a bitmap gives you one bit per slot, a bitfield gives you an *n*-bit signed
or unsigned integer per slot, with atomic get / set / increment on each one and
a configurable overflow policy.

The whole thing is one command: `BITFIELD`.

---

## Key facts

- Encodings: **`u<bits>`** unsigned, 1-63 bits. **`i<bits>`** signed, 1-64 bits.
  (Unsigned caps at 63, not 64 — Redis returns results as signed 64-bit
  integers, so a `u64` couldn't be represented.)
- Offsets are either a **raw bit offset** (`0`, `8`, `16`, …) or **`#n`**, which
  means "the *n*th field of this width" — so `u8 #2` is bit offset 16.
- A single `BITFIELD` call can chain **many** sub-operations, and the whole chain
  executes **atomically** as one command.
- The reply is an **array**, one entry per `GET`/`SET`/`INCRBY` in the chain
  (`OVERFLOW` produces no entry).
- Missing bits are treated as `0`, and the string grows automatically.

---

## Complexity

O(1) per sub-operation, so O(N) for a chain of N operations.

---

## The three sub-operations

```bash
BITFIELD key GET    u8 #0                # read
BITFIELD key SET    u8 #0 42             # write; returns the PREVIOUS value
BITFIELD key INCRBY u8 #0 5              # add; returns the NEW value
```

Note the asymmetry, and it is deliberate:

- **`SET` returns the old value** (like `SETBIT`).
- **`INCRBY` returns the new value** (like `INCR`).

Chaining them is the point:

```bash
BITFIELD player:1 SET u8 #0 7 SET u8 #1 3 SET u8 #2 250
# -> [0, 0, 0]   (three old values, all previously unset)

BITFIELD player:1 INCRBY u8 #1 -1 INCRBY u8 #2 5 GET u8 #0
# -> [2, 255, 7] (new lives, new coins, current level) — all atomic
```

That last call is a read-modify-write across three counters with **no race
window**, which you could not achieve with three separate commands.

---

## Overflow policies

This is the feature that makes bitfields more than a packing trick. When an
`INCRBY` would exceed the encoding's range:

| Policy | Behaviour |
|---|---|
| `WRAP` | Wrap around modulo the range. **The default.** |
| `SAT` | Saturate — clamp at the max (or min) instead of wrapping. |
| `FAIL` | Do nothing and return `nil` for that sub-operation. |

```bash
BITFIELD key SET u8 #0 255 INCRBY u8 #0 10
# WRAP (default) -> 9

BITFIELD key SET u8 #0 255 OVERFLOW SAT INCRBY u8 #0 10
# -> 255

BITFIELD key SET u8 #0 255 OVERFLOW FAIL INCRBY u8 #0 10
# -> nil
```

**`OVERFLOW` applies only to the sub-operations that come AFTER it** in the
chain, and it can be changed mid-chain:

```bash
BITFIELD key OVERFLOW WRAP INCRBY u8 #0 10 OVERFLOW SAT INCRBY u8 #0 300 OVERFLOW FAIL INCRBY u8 #0 1
```

In redis-py the equivalent is `client.bitfield(key, default_overflow="SAT")` to
set it for the whole chain, or `.incrby(..., overflow="FAIL")` per operation.

---

## The read-only variant

```bash
BITFIELD_RO key GET u8 #0 GET u8 #1
```

`GET` operations only. Because it can't write, it's flagged read-only and is
safe to route to a **replica**. Plain `BITFIELD` is always treated as a write
command even if the chain contains only `GET`s.

---

## redis-py specifics

`BITFIELD` is a builder, not a plain method:

```python
client.bitfield(key, default_overflow="SAT") \
      .set("u8", "#0", 7)   \
      .incrby("u8", "#1", -1) \
      .get("u8", "#0")      \
      .execute()
```

- `.overflow("SAT")` changes the policy mid-chain.
- `.reset()` clears the accumulated chain so the builder object can be reused.
- `.execute()` is what actually sends the command — forgetting it is the classic
  bug, and it fails silently by simply doing nothing.
- `client.bitfield_ro(key, encoding, offset, items=[...])` is a normal method,
  not a builder.

---

## When to reach for a bitfield

The trade is **memory density against readability**. Eight counters as eight
Redis keys cost eight key objects, eight expiry slots, eight dictionary entries —
easily a few hundred bytes. As eight `u8` fields in one bitfield: **8 bytes**
plus one key.

That only pays off when you have a *lot* of these records and the counters are
genuinely small and bounded. If the counters can grow arbitrarily, or you need
to name them, a [Hash](HASH_NOTES.md) with `HINCRBY` is far more maintainable.

| Want | Use |
|---|---|
| A few named counters per record | [Hash](HASH_NOTES.md) + `HINCRBY` |
| Many tiny bounded counters, memory-critical | **Bitfield** |
| One bit per entity | [Bitmap](BITMAP_NOTES.md) |
| One unbounded counter | [String](STRING_NOTES.md) + `INCR` |

---

## Gotchas worth remembering

- **`SET` returns the old value, `INCRBY` returns the new one.** Easy to mix up.
- **`OVERFLOW` is positional** — it affects only subsequent operations in the
  chain, not the whole command.
- **`WRAP` is the default**, so an unnoticed overflow silently wraps rather than
  erroring. If correctness matters, be explicit with `SAT` or `FAIL`.
- **`u64` is not valid** — unsigned tops out at `u63`.
- **`#n` is width-relative.** `u8 #2` and `u16 #2` are different bit offsets
  (16 and 32). The `#` notation only makes sense if you use a consistent width.
- **In redis-py, forgetting `.execute()`** produces no error and no effect.
- The key is a string, so `TYPE` returns `string` and `STRLEN` shows the packed
  size in bytes.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `BITFIELD key GET <type> <offset>` | Read one field |
| `BITFIELD key SET <type> <offset> <value>` | Write one field; returns the **old** value |
| `BITFIELD key INCRBY <type> <offset> <delta>` | Add to a field; returns the **new** value |
| `BITFIELD key OVERFLOW WRAP\|SAT\|FAIL ...` | Set the policy for the operations that follow |
| `BITFIELD_RO key GET <type> <offset> [...]` | Read-only variant, replica-safe |

**Type syntax:** `u1`-`u63` (unsigned), `i1`-`i64` (signed).
**Offset syntax:** a raw bit offset, or `#n` for the *n*th field of that width.
