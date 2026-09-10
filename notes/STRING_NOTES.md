# Redis Strings — Notes

Practice script: [`src/string_redis.py`](../src/string_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/strings

---

## What it is

The most basic Redis type: a key mapped to **a sequence of bytes**. Not "text" —
binary-safe, so it can hold a serialized object, a protobuf payload, a small
image, a JPEG thumbnail, anything. Redis never inspects the contents.

It also doubles as Redis' **integer and float counter**, because `INCR` and
friends parse the string as a number, mutate it, and write it back — atomically.

---

## Key facts

- Max size of a single string value: **512 MB**.
- Binary-safe: no encoding assumptions, no null-byte problems.
- All the numeric commands (`INCR`, `INCRBY`, `INCRBYFLOAT`) are **atomic** — safe
  for counters hit by many clients at once, no read-modify-write race.
- `INCR` on a **missing** key treats it as `0` and creates it. You never need to
  initialize a counter.
- `INCR` on a key holding a non-numeric string is an **error**, not a silent 0.
- Key naming convention in production: `<entity>:<id>` or `<entity>:<id>:<field>`,
  e.g. `user:1001:email`. Colons are just a convention, not a Redis feature.

---

## Complexity

| Operation | Cost |
|---|---|
| `SET`, `GET`, `INCR`, `STRLEN`, `GETDEL` | O(1) |
| `MSET`, `MGET` | O(N) in the number of keys |
| `APPEND`, `SETRANGE` | O(1) amortized |
| `GETRANGE` | O(N) in the length of the returned range |
| `LCS` | O(N*M) — expensive, two long strings will hurt |

---

## Setting values — the conditional flags

`SET` is not one command, it's a family. The flags are what make it useful:

```bash
SET key value           # unconditional overwrite
SET key value NX        # only if the key does NOT exist  -> nil if it does
SET key value XX        # only if the key ALREADY exists  -> nil if it doesn't
SET key value GET       # write the new value, return the OLD one
SET key value KEEPTTL   # overwrite the value but keep the existing TTL
SET key value EX 60     # with a 60-second TTL
SET key value PX 60000  # same, in milliseconds
SET key value EXAT <unix-seconds>   # absolute expiry
SET key value PXAT <unix-millis>    # absolute expiry, ms
```

**`NX` is the lock primitive.** `SET lock:resource <token> NX EX 30` is the
canonical "acquire a lock, but never hold it forever" pattern — the whole thing
in one atomic command.

Dedicated older equivalents, all still valid:

```bash
SETNX key value          # == SET key value NX
SETEX key 60 value       # == SET key value EX 60
PSETEX key 60000 value   # == SET key value PX 60000
```

---

## Multi-key operations

```bash
MSET k1 v1 k2 v2 k3 v3   # atomic across all keys — no client sees a half-applied MSET
MGET k1 k2 k3            # one round trip; missing keys come back as nil
MSETNX k1 v1 k2 v2       # all-or-nothing: writes ONLY if EVERY key is missing
```

`MSETNX` is genuinely all-or-nothing — one existing key aborts the entire write.

---

## Read-and-modify in one step

These exist so you don't have to do GET-then-DEL / GET-then-EXPIRE as two
commands with a race window in between:

```bash
GETDEL key         # return the value AND delete the key, atomically
GETEX key EX 60    # return the value AND set/refresh its TTL
GETEX key PERSIST  # return the value AND strip its TTL
GETSET key value   # (deprecated) set new, return old — use SET ... GET instead
```

`GETDEL` is the right tool for one-time tokens: read it and burn it, with no
window where another client could read the same token.

---

## Treating the string as text

```bash
APPEND key " more"        # append; creates the key if missing. Returns new length.
STRLEN key                # length in BYTES (not characters — beware multi-byte UTF-8)
GETRANGE key 0 4          # substring by byte offset, INCLUSIVE on both ends
GETRANGE key -5 -1        # negative offsets count from the end
SETRANGE key 6 "patch"    # overwrite bytes starting at an offset, zero-padding if needed
SUBSTR key 0 4            # deprecated alias for GETRANGE
```

**Gotcha:** `GETRANGE key 0 4` returns **5** bytes, not 4. Both ends are
inclusive, unlike Python slicing.

**Gotcha:** `SETRANGE` past the end of the string **zero-pads the gap** with null
bytes rather than erroring.

---

## Treating the string as a number

```bash
INCR key            # +1
DECR key            # -1
INCRBY key 100      # +100
DECRBY key 100      # -100
INCRBYFLOAT key 1.5 # +1.5
```

There is **no `DECRBYFLOAT`** — pass a negative number to `INCRBYFLOAT`.

Integer commands work on 64-bit signed integers; overflowing that range is an
error. `INCRBYFLOAT` uses long double precision.

---

## Comparing two strings

```bash
LCS key1 key2                         # the longest common subsequence itself
LCS key1 key2 LEN                     # just its length
LCS key1 key2 IDX                     # the match positions
LCS key1 key2 IDX MINMATCHLEN 4 WITHMATCHLEN   # positions + lengths, filtered
```

Added in Redis 7.0. Both keys must hold strings. Note this is the longest common
*subsequence*, not *substring* — the characters need not be contiguous.

---

## Key lifecycle (not string-specific, but used constantly with strings)

```bash
EXISTS key [key ...]   # count of how many of the given keys exist
TYPE key               # -> string
DEL key                # delete
UNLINK key             # delete asynchronously — better for very large values
TTL key                # seconds left; -1 = no TTL, -2 = key doesn't exist
PTTL key               # same, in milliseconds
EXPIRETIME key         # the absolute unix SECOND the key dies at (Redis 7.0+)
PEXPIRETIME key        # same, in milliseconds
EXPIRE key 60          # set a TTL
PERSIST key            # remove the TTL
COPY src dst [REPLACE] # duplicate a key
RENAME key newkey      # rename, OVERWRITING the destination if it exists
RENAMENX key newkey    # rename, but fail if the destination exists
```

**Remember the TTL sentinel values:** `-1` means the key exists with no
expiration; `-2` means the key is gone. They are easy to confuse.

---

## Internal encoding

```bash
OBJECT ENCODING key
```

Redis picks the cheapest representation automatically:

| Encoding | When |
|---|---|
| `int` | The value is an integer that fits in a `long` — stored as a number, not text |
| `embstr` | Short strings (≤ 44 bytes) — value allocated together with the object header, one allocation |
| `raw` | Anything longer, or any string that has been modified with `APPEND`/`SETRANGE` |

Purely an internal optimization — it never changes command behaviour. Worth
knowing only because `APPEND` on an `embstr` permanently converts it to `raw`.

---

## Gotchas worth remembering

- **Quoting in `redis-cli`.** `SET msg how are you NX` fails with a syntax error
  because the CLI splits on spaces and `SET` sees too many arguments. Quote
  multi-word values: `SET msg "how are you" NX`.
- **`STRLEN` counts bytes, not characters.** A string of 5 emoji has a `STRLEN`
  far greater than 5.
- **`GETRANGE` is inclusive at both ends** — off-by-one waiting to happen.
- **`APPEND` creates the key if missing**, so a typo in the key name silently
  creates a new key instead of erroring.
- **A string used as a counter is still a string.** `TYPE` returns `string`, and
  `OBJECT ENCODING` returns `int` — those are different questions.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `SET key value` | Set a value (overwrites) |
| `SET key value NX` | Set only if the key does NOT exist |
| `SET key value XX` | Set only if the key ALREADY exists |
| `SET key value GET` | Set a new value, return the old one |
| `SET key value EX/PX/EXAT/PXAT n` | Set with an expiration |
| `SET key value KEEPTTL` | Set a new value, keep the existing TTL |
| `SETNX key value` | Set only if missing (older form of `SET ... NX`) |
| `SETEX key sec value` / `PSETEX key ms value` | Set with a TTL in one call |
| `GET key` | Get the value |
| `MGET key [key ...]` | Get several values in one round trip |
| `MSET key val [key val ...]` | Set several values atomically |
| `MSETNX key val [key val ...]` | Set several values only if none exist |
| `GETSET key value` | (Deprecated) set new, return old |
| `GETDEL key` | Get the value and delete the key, atomically |
| `GETEX key [EX n \| PERSIST]` | Get the value and set/clear its TTL |
| `APPEND key value` | Append to the value; returns the new length |
| `STRLEN key` | Length of the value, in bytes |
| `GETRANGE key start end` | Substring by byte offset (both ends inclusive) |
| `SETRANGE key offset value` | Overwrite bytes at an offset |
| `INCR key` / `DECR key` | Atomically ±1 |
| `INCRBY key n` / `DECRBY key n` | Atomically ±n |
| `INCRBYFLOAT key n` | Atomically add a float (negative to subtract) |
| `LCS key1 key2 [LEN\|IDX\|MINMATCHLEN n\|WITHMATCHLEN]` | Longest common subsequence |
| `EXISTS key [key ...]` | How many of these keys exist |
| `TYPE key` | The key's data type |
| `DEL key` / `UNLINK key` | Delete (sync / async) |
| `TTL key` / `PTTL key` | Time left (`-1` no TTL, `-2` no key) |
| `EXPIRETIME key` / `PEXPIRETIME key` | Absolute expiry timestamp (Redis 7.0+) |
| `EXPIRE key n` / `PERSIST key` | Set / remove a TTL |
| `COPY src dst [REPLACE]` | Duplicate a key |
| `RENAME key newkey` / `RENAMENX` | Rename (with / without overwrite protection) |
| `OBJECT ENCODING key` | Internal format (`int` / `embstr` / `raw`) |

---

## Related types

Strings are the substrate for two other "types" that are really just different
ways of addressing the same bytes:

- **[Bitmaps](BITMAP_NOTES.md)** — address the string one bit at a time.
- **[Bitfields](BITFIELD_NOTES.md)** — pack many small integers into one string.

[HyperLogLog](HYPERLOGLOG_NOTES.md) is also stored as a string internally, which
is why `STRLEN` works on an HLL key.
