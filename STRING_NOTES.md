# Redis Strings — Notes

Notes from exploring the `String` data type, plus everything else worth knowing that wasn't covered yet.

---

## What I Know

- To set a String value: `SET name Shubhanshu`
- To get a String value: `GET name`
- In PROD, follow the key naming convention `<entity>:<entity_id>`, rather than just `<entity>`
- By default, a single Redis string can be a max. of **512MB**

---

## CLI Session — What I Tried

```
PS C:\Users\ShubhanshuJha> docker exec -it 6ebd3c3460e5 bash
root@6ebd3c3460e5:/# redis-cli ping
PONG
root@6ebd3c3460e5:/# redis-cli
127.0.0.1:6379> ping
PONG
127.0.0.1:6379> SET name shubhanshu
OK
127.0.0.1:6379> SET name Shubhanshu
OK
127.0.0.1:6379> GET name
"Shubhanshu"
127.0.0.1:6379> GET name
"Shubhanshu Jha"
127.0.0.1:6379> set user:1 shubhanshu
OK
127.0.0.1:6379> set user:2 john
OK
127.0.0.1:6379> set user:3 jane
OK
127.0.0.1:6379> set msg:1 hey
OK
127.0.0.1:6379> set msg:2 hola
OK
127.0.0.1:6379> set msg:3 how are you nx
(error) ERR syntax error
127.0.0.1:6379> set msg:3 "how are you" nx
OK
127.0.0.1:6379> set msg:3 "something else" nx
(nil)
127.0.0.1:6379> set msg:3 "something else"
OK
127.0.0.1:6379> mget user:1 msg:1 msg:2
1) "shubhanshu"
2) "hey"
3) "hola"
127.0.0.1:6379> set msg:4 "buenos dias" xx
(nil)
127.0.0.1:6379> set msg:4 "hola"
OK
127.0.0.1:6379> set msg:4 "buenos dias" xx
OK
127.0.0.1:6379> mset user:4 rambo msg:5 Bien user:5 ketty
OK
127.0.0.1:6379> set total_crashes 0
OK
127.0.0.1:6379> incr total_crashes
(integer) 1
127.0.0.1:6379> incr total_crashes
(integer) 2
127.0.0.1:6379> incrby total_crashes 10
(integer) 12
127.0.0.1:6379> decr total_crashes
(integer) 11
127.0.0.1:6379> decrby total_crashes 5
(integer) 6
```

**What actually happened here, worth remembering:**

- `SET msg:3 how are you nx` errored because the value wasn't quoted — `redis-cli` split it into separate tokens (`how`, `are`, `you`, `nx`), and `SET` doesn't know what to do with that many arguments. Quoting multi-word values (`"how are you"`) fixes it.
- `NX` = **only set if the key does NOT already exist.** First `SET msg:3 ... nx` succeeded (key was new) → `OK`. The second one returned `(nil)` because `msg:3` already existed by then — the value was *not* overwritten.
- `XX` = the opposite: **only set if the key already exists.** `SET msg:4 ... xx` returned `(nil)` while `msg:4` didn't exist yet; once it was created with a plain `SET`, the same `xx` command succeeded.
- `MGET`/`MSET` fetch/set several keys in a single round trip — and `MSET` is atomic across all the keys it touches (no other client can see a half-applied `MSET`).
- `INCR`/`DECR`/`INCRBY`/`DECRBY` treat the string as an integer, and are **atomic** — safe for counters like `total_crashes` even with many clients hitting it at once, no race condition.

---

## Filling the Gaps — What Wasn't Covered Yet

### 1. Checking things about a key (not string-specific, but used constantly with strings)

```bash
EXISTS name        # 1 if it exists, 0 if not
TYPE name          # -> string
STRLEN name        # length of the stored string, in bytes
DEL name           # delete the key
```

### 2. Modifying a string in place

```bash
APPEND name " Jha"          # Appends to the existing value (creates the key if it doesn't exist)
GETRANGE name 0 4           # Substring by byte offsets (like Python's name[0:5])
SETRANGE name 0 "SHU"       # Overwrite part of a string starting at an offset
```

### 3. Atomic "get the old value while setting a new one"

```bash
GETSET name "NewValue"      # Old-school way: sets a new value, returns the previous one (deprecated — prefer SET ... GET below)
SET name "NewValue" GET     # Modern equivalent of GETSET, using the GET option on SET itself
GETDEL name                 # Returns the value AND deletes the key, atomically — great for one-time tokens
GETEX name EX 60            # Returns the value AND lets you set/refresh a TTL in the same call
```

### 4. `MSETNX` — the `NX` you already know, but for multiple keys at once

```bash
MSETNX a 1 b 2 c 3    # Sets a, b, AND c — but ONLY if none of them already exist. All-or-nothing.
```

### 5. The float sibling of `INCR`/`DECR`

```bash
INCRBYFLOAT price 2.5   # Like INCRBY, but for decimals. There's no DECRBYFLOAT — just use a negative number.
```

### 6. Expiration — strings and TTLs go hand in hand

You already used `NX`/`XX`; `SET` also takes expiration options directly:

```bash
SET session:abc "data" EX 3600      # Expires in 3600 seconds
SET session:abc "data" PX 3600000   # Same, but in milliseconds
SET session:abc "data" KEEPTTL      # Update the value but keep whatever TTL it already had
SETEX session:abc 3600 "data"       # Older, dedicated command — same effect as SET ... EX
TTL session:abc                     # How many seconds are left before it expires
PERSIST session:abc                 # Remove the TTL, make it permanent again
```

### 7. Copying and renaming keys

```bash
COPY user:1 user:1:backup     # Duplicate a key's value under a new name
RENAME msg:1 message:1        # Rename a key (overwrites the destination if it exists!)
RENAMENX msg:1 message:1      # Same, but fails instead of overwriting if the destination exists
```

### 8. Comparing two strings

```bash
LCS user:1 user:2   # Longest Common Subsequence between two string values — added in Redis 7.0
```

### 9. Strings are binary-safe

A Redis string isn't limited to text — it can hold any bytes: a serialized object, a small image, a protobuf payload, etc. Nothing about `SET`/`GET` cares what's inside, up to that 512MB ceiling you already noted.

### 10. How Redis stores a string internally (good to know, not something you'll use daily)

```bash
OBJECT ENCODING total_crashes   # -> "int" (small integers are stored specially, cheaper than a raw string)
OBJECT ENCODING name            # -> "embstr" or "raw" depending on length
```

Redis picks the cheapest internal representation it can: `int` for numbers that fit in a long, `embstr` for short strings (≤44 bytes), and `raw` for anything longer. This is purely an internal optimization — it doesn't change how you use the key.

---

## Complete String Command Cheat Sheet

| Command | What it does |
|---|---|
| `SET key value` | Set a string value (overwrites if it exists) |
| `SET key value NX` | Set only if the key does NOT exist |
| `SET key value XX` | Set only if the key already exists |
| `SET key value GET` | Set a new value, return the old one |
| `SET key value EX/PX/EXAT/PXAT seconds` | Set with an expiration |
| `SET key value KEEPTTL` | Set a new value, keep the existing TTL |
| `GET key` | Get a string value |
| `MGET key1 key2 ...` | Get multiple values in one round trip |
| `MSET key1 val1 key2 val2 ...` | Set multiple values atomically |
| `MSETNX key1 val1 ...` | Set multiple values, only if none already exist |
| `GETSET key value` | (Deprecated) Set a new value, return the old one — use `SET ... GET` instead |
| `GETDEL key` | Get a value and delete the key, atomically |
| `GETEX key [EX seconds]` | Get a value and optionally set/clear its TTL |
| `SETEX key seconds value` | Set a value with a TTL in one call |
| `STRLEN key` | Length of the stored string, in bytes |
| `APPEND key value` | Append to an existing string (creates it if missing) |
| `GETRANGE key start end` | Read a substring by byte offset |
| `SETRANGE key offset value` | Overwrite part of a string at a given offset |
| `INCR key` / `DECR key` | Atomically increment/decrement an integer string by 1 |
| `INCRBY key n` / `DECRBY key n` | Atomically increment/decrement by `n` |
| `INCRBYFLOAT key n` | Atomically increment by a float |
| `LCS key1 key2` | Longest common subsequence between two string values |
| `COPY key newkey` | Duplicate a key under a new name |
| `RENAME key newkey` / `RENAMENX` | Rename a key (with or without overwrite protection) |
| `EXISTS key` | 1 if the key exists, 0 if not |
| `TYPE key` | What data type this key holds |
| `DEL key` | Delete a key |
| `TTL key` | Seconds remaining before expiry (`-1` = no TTL, `-2` = doesn't exist) |
| `PERSIST key` | Remove a key's TTL, make it permanent |
| `OBJECT ENCODING key` | Internal storage format (`int` / `embstr` / `raw`) |
