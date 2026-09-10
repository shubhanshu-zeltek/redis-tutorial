# Redis Lists — Notes

Notes from exploring the `List` data type, plus everything else worth knowing that wasn't covered yet.

---

## What I Know

- Redis lists are linked lists of string values. They are frequently used to:
  - Implement stacks and queues.
  - Build queue management for background worker systems.
- `LPUSH` (and `RPUSH`) return the size of the list *after* adding the new element.
- The max length of a Redis list is `(2^32) - 1` elements.
- Redis list's time complexity is similar to a linked-list data structure — cheap at the ends (`LPUSH`/`RPUSH`/`LPOP`/`RPOP` are O(1)), more expensive the deeper you index into the middle (`LINDEX`, `LINSERT`, `LREM` are O(N)).

---

## Python Client — Stack vs Queue

```python
import redis


redis_client: redis.Redis = None
def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def add_to_stack(key, value):
    global redis_client
    return redis_client.lpush(key, value)

def add_to_queue(key, value):
    global redis_client
    return redis_client.lpush(key, value)

def remove_from_stack(key):
    global redis_client
    return redis_client.lpop(key)

def remove_from_queue(key):
    global redis_client
    return redis_client.rpop(key)


if __name__ == "__main__":
    init_client()

    print("(*) Adding elements to Stack.")
    key = "counter:stack"
    for i in range(1, 6):
        resp = add_to_stack(key=key, value=i)
        print(resp)

    print("(*) Removing elements from Stack.")
    for i in range(1, 3):
        resp = remove_from_stack(key=key)
        print(resp)

    print("(*) Adding elements to Queue.")
    key = "counter:queue"
    for i in range(1, 6):
        resp = add_to_queue(key=key, value=i)
        print(resp)

    print("(*) Removing elements from Queue.")
    for i in range(1, 3):
        resp = remove_from_queue(key=key)
        print(resp)

    key = "counter:index"
    print("(*) Adding some elements into the List.")
    for i in range(1, 5):
        resp = redis_client.lpush(key, i)
        print(resp)

    resp = redis_client.lrange(key, 0, -1)
    print(resp)
```

**Why this works, even though `add_to_stack` and `add_to_queue` are identical:**

The push side doesn't need to differ — what makes something a stack vs a queue is *which end you pop from, relative to the end you pushed to*:

- **Stack (LIFO)** = push and pop from the **same** end → `LPUSH` + `LPOP`. The last thing in is the first thing out.
- **Queue (FIFO)** = push and pop from **opposite** ends → `LPUSH` + `RPOP` (or `RPUSH` + `LPOP`). The first thing in is the first thing out.

---

## CLI Session — What I Tried

```
127.0.0.1:6379> lpush messages hello
(integer) 1
127.0.0.1:6379> lpush messages world
(integer) 2
127.0.0.1:6379> rpush messages bye!
(integer) 3
127.0.0.1:6379> lpop messages
"world"
127.0.0.1:6379> rpop messages
"bye!"
127.0.0.1:6379> rpop messages
"hello"
127.0.0.1:6379> rpop messages
(nil)
127.0.0.1:6379> llen messages
(integer) 0
127.0.0.1:6379> lpush indices 1
(integer) 1
127.0.0.1:6379> lpush indices 2
(integer) 2
127.0.0.1:6379> lpush indices 3
(integer) 3
127.0.0.1:6379> lpush indices 4
(integer) 4
127.0.0.1:6379> lpush indices 5
(integer) 5
127.0.0.1:6379> bllpop indices 10
(error) ERR unknown command 'bllpop', with args beginning with: 'indices' '10'
127.0.0.1:6379> blpop indices 10
1) "indices"
2) "5"
127.0.0.1:6379> blpop indices 10
1) "indices"
2) "4"
127.0.0.1:6379> blpop indices 10
1) "indices"
2) "3"
127.0.0.1:6379> blpop indices 10
1) "indices"
2) "2"
127.0.0.1:6379> blpop indices 10
1) "indices"
2) "1"
127.0.0.1:6379> blpop indices 10
(nil)
(10.05s)
127.0.0.1:6379> blpop indices 20
1) "indices"
2) "3"
(6.98s)
127.0.0.1:6379> lrange index 0 -1'
Invalid argument(s)
127.0.0.1:6379> lrange index 0 -1
(empty array)
127.0.0.1:6379> lrange counter:index 0 -1
1) "2"
2) "1"
127.0.0.1:6379> lrange counter:index -1 0
(empty array)
127.0.0.1:6379> del counter:index
(integer) 1
```

**What actually happened here, worth remembering:**

- After `lpush messages hello` then `lpush messages world`, the list (left → right) is `[world, hello]`. `rpush messages bye!` appends at the tail: `[world, hello, bye!]`. `lpop` took `world` (leftmost); the two `rpop`s then took `bye!` then `hello` (rightmost each time) — draining the list from both ends until it's empty, hence `LLEN` → `0`.
- `bllpop` isn't a real command — it's a typo of `BLPOP` — hence `unknown command`.
- `BLPOP` (**b**locking **l**eft **pop**) pops from the head, same as `LPOP`, but if the list is empty it **waits** up to `timeout` seconds for something to arrive instead of returning `(nil)` immediately. Each call here returned the current head of `indices` and removed it, until the list was empty.
- The `blpop indices 10` that returned `(nil)` after `(10.05s)` means it waited out the *entire* 10-second timeout because `indices` was empty and nothing arrived — that's expected blocking behavior, not an error.
- The next call, `blpop indices 20`, unblocked after only `6.98s` and returned `"3"` — meaning some *other* client pushed `3` onto `indices` while this one was waiting. That's the actual point of `BLPOP`: multiple workers can block on the same list and whichever is waiting picks up the next item the instant it's pushed, instead of polling.
- `lrange index 0 -1'` — that trailing stray `'` is an unbalanced quote, so `redis-cli` couldn't parse the line at all → `Invalid argument(s)`. That's a client-side parsing error, not a Redis server error.
- `lrange index 0 -1` (now valid) returned `(empty array)` because `index` (singular) was never actually created — the real key from the Python script was `counter:index`.
- `lrange counter:index 0 -1` → `["2", "1"]`. Order matters: `LRANGE` always returns elements left-to-right regardless of which indices you pass.
- `lrange counter:index -1 0` → `(empty array)`. This is a common gotcha: `LRANGE` does **not** auto-reverse. If the *start* index resolves to a position after the *stop* index, you get nothing back — you can't pass `-1 0` expecting "last to first."

---

## Filling the Gaps — Every Other List Operation

### 1. Pushing — the variants you haven't used yet

```bash
LPUSH mylist a b c        # Push multiple elements at once (pushed one-by-one, so final order is c,b,a at the head)
RPUSH mylist x y z        # Same idea, at the tail
LPUSHX mylist "only-if-exists"   # Push to head, but ONLY if the key already exists — no-op (returns 0) otherwise
RPUSHX mylist "only-if-exists"   # Same, at the tail
```

### 2. Popping — with a count

```bash
LPOP mylist 3     # Pop up to 3 elements from the head at once (returns an array), instead of one at a time
RPOP mylist 3     # Same, from the tail
```

### 3. Reading without removing

```bash
LINDEX mylist 0     # Get the element at a specific index (0 = head, -1 = tail)
LLEN mylist         # Length of the list
LPOS mylist "c"     # Find the index of the first occurrence of a value (added in Redis 6.2)
LPOS mylist "c" COUNT 0   # Find the index of EVERY occurrence
```

### 4. Modifying in place

```bash
LSET mylist 0 "new-value"           # Overwrite the element at a given index
LINSERT mylist BEFORE "c" "b.5"     # Insert a new element right before (or AFTER) a pivot value
LREM mylist 1 "b"                   # Remove up to 1 occurrence of "b", searching head-to-tail
LREM mylist -1 "b"                  # Negative count searches tail-to-head instead
LREM mylist 0 "b"                   # Count of 0 removes ALL occurrences
LTRIM mylist 0 2                    # Keep only elements 0 through 2, discard everything else — shrinks the list in place
```

### 5. Moving elements between lists (atomically)

```bash
RPOPLPUSH source destination         # Pop from the tail of `source`, push to the head of `destination`, in one atomic step
LMOVE source destination LEFT RIGHT  # The general-purpose version (Redis 6.2+) — choose which end of each list to use
```

`RPOPLPUSH` with the same key for source and destination rotates a list — handy for round-robin processing. `LMOVE` does the same job but lets you pick `LEFT`/`RIGHT` on both ends instead of being locked to "tail → head."

### 6. Blocking variants — beyond the `BLPOP` you already tried

```bash
BRPOP key1 key2 timeout           # Same as BLPOP, but pops from the tail; can watch multiple keys, returns from whichever gets data first
BRPOPLPUSH source destination timeout   # Blocking version of RPOPLPUSH
BLMOVE source destination LEFT RIGHT timeout   # Blocking version of LMOVE (Redis 6.2+)
```

### 7. Popping across multiple lists at once (Redis 7.0+)

```bash
LMPOP 2 list1 list2 LEFT COUNT 5    # Pop up to 5 elements from the FIRST non-empty list among list1/list2
BLMPOP 10 2 list1 list2 LEFT COUNT 5   # Same, but blocks up to 10s if both lists are currently empty
```

Useful when a worker watches several queues and just wants "give me work from whichever queue has something," without checking each one manually.

### 8. Internal storage (good to know, not something you'll call directly)

```bash
OBJECT ENCODING mylist   # -> "listpack" for small lists, "quicklist" once it grows past Redis's size/length thresholds
```

Small lists are stored as a compact `listpack` (cheap on memory); Redis automatically switches to a `quicklist` (a linked list of listpacks) as the list grows. This is transparent — your commands behave identically either way.

---

## Complete List Command Cheat Sheet

| Command | What it does |
|---|---|
| `LPUSH key val [val ...]` | Push one or more elements to the head; returns new length |
| `RPUSH key val [val ...]` | Push one or more elements to the tail; returns new length |
| `LPUSHX key val` | Push to head, only if the key already exists |
| `RPUSHX key val` | Push to tail, only if the key already exists |
| `LPOP key [count]` | Remove and return element(s) from the head |
| `RPOP key [count]` | Remove and return element(s) from the tail |
| `LLEN key` | Number of elements in the list |
| `LRANGE key start stop` | Get a range of elements (left → right, inclusive) |
| `LINDEX key index` | Get the element at a specific index |
| `LSET key index val` | Overwrite the element at a specific index |
| `LINSERT key BEFORE\|AFTER pivot val` | Insert a new element next to an existing value |
| `LREM key count val` | Remove occurrences of a value (`count` > 0 = head→tail, < 0 = tail→head, 0 = all) |
| `LTRIM key start stop` | Shrink the list to only the given range |
| `LPOS key val [COUNT n]` | Find the index (or indices) of a value |
| `RPOPLPUSH source dest` | Atomically move the tail of one list to the head of another |
| `LMOVE source dest LEFT\|RIGHT LEFT\|RIGHT` | Generalized atomic move between two lists (Redis 6.2+) |
| `BLPOP key [key ...] timeout` | Blocking `LPOP` across one or more keys |
| `BRPOP key [key ...] timeout` | Blocking `RPOP` across one or more keys |
| `BRPOPLPUSH source dest timeout` | Blocking `RPOPLPUSH` |
| `BLMOVE source dest LEFT\|RIGHT LEFT\|RIGHT timeout` | Blocking `LMOVE` (Redis 6.2+) |
| `LMPOP numkeys key [key ...] LEFT\|RIGHT [COUNT n]` | Pop from the first non-empty list among several (Redis 7.0+) |
| `BLMPOP timeout numkeys key [key ...] LEFT\|RIGHT [COUNT n]` | Blocking `LMPOP` (Redis 7.0+) |
| `OBJECT ENCODING key` | Internal storage format (`listpack` / `quicklist`) |

**Quick reference — stack vs queue with lists:**

| Pattern | Push with | Pop with |
|---|---|---|
| Stack (LIFO) | `LPUSH` | `LPOP` |
| Queue (FIFO) | `LPUSH` | `RPOP` |