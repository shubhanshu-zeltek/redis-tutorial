# Redis Lists — Notes

Notes from exploring the `List` data type, plus everything else worth knowing that wasn't covered yet.

---

## What I Know

- Redis lists are linked lists of string values. They are frequently used to:
    - Implement stacks and queues.
    - Build queue management for background worker systems.
- `LPUSH` returns the size of the list after adding the new element (so does `RPUSH`).
- The max length of a Redis list is (2^32) - 1 elements.
- Redis list's time complexity is similar to List DS — cheap at the ends (push/pop), expensive in the middle (random access, insert, search).

---

## Python Walkthrough — Stack & Queue Using Lists

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

**Why this works — the core trick with lists is which end you push/pop from:**

- **Stack (LIFO)**: `add_to_stack` pushes with `LPUSH` (head), `remove_from_stack` pops with `LPOP` (also head). Whatever went in last comes out first — classic stack behavior.
- **Queue (FIFO)**: `add_to_queue` also pushes with `LPUSH` (head), but `remove_from_queue` pops with `RPOP` (tail — the opposite end). Since new items always enter at the head and leave from the tail, the *oldest* item leaves first — classic FIFO queue. (You'd get the same FIFO result the other way round too: `RPUSH` + `LPOP`. What matters is that push and pop happen on *opposite* ends.)
- `LRANGE key 0 -1` at the end reads the whole list, head to tail — `0` is the first index, `-1` means "the last element," so `0 -1` = everything.

---

## Filling the Gaps — What Wasn't Covered Yet

### 1. Adding elements

```bash
LPUSH key v1 v2 v3     # Push one or more values onto the head (left)
RPUSH key v1 v2 v3     # Push one or more values onto the tail (right)
LPUSHX key value       # Push onto the head, but ONLY if the key already exists
RPUSHX key value       # Push onto the tail, but ONLY if the key already exists
```

### 2. Removing elements

```bash
LPOP key           # Remove and return the head element
RPOP key           # Remove and return the tail element
LPOP key 3         # Remove and return the first 3 elements from the head
RPOP key 3         # Remove and return the last 3 elements from the tail
LREM key 2 "hey"    # Remove up to 2 occurrences of "hey", searching from the head
LREM key -2 "hey"   # Same, but searching from the tail (negative count)
LREM key 0 "hey"    # Remove ALL occurrences of "hey"
```

### 3. Reading elements (without removing them)

```bash
LRANGE key 0 -1     # Read the entire list, head to tail
LRANGE key 0 2       # Read the first 3 elements (indexes 0, 1, 2)
LINDEX key 0        # Read a single element at a given index (0 = head, -1 = tail)
LLEN key            # How many elements are in the list
```

### 4. Modifying elements in place

```bash
LSET key 0 "newvalue"                  # Overwrite the element at a given index
LINSERT key BEFORE "pivot" "newval"    # Insert newval right before the first occurrence of "pivot"
LINSERT key AFTER "pivot" "newval"     # Insert newval right after the first occurrence of "pivot"
LTRIM key 0 4                          # Keep only indexes 0-4, discard everything else
```

`LTRIM` is what you'd use to cap a list at, say, the last 100 log lines — push new entries, then `LTRIM key 0 99` after every push to keep it bounded.

### 5. Moving elements between two lists, atomically

```bash
LMOVE source destination LEFT RIGHT    # Pop from source's head, push onto destination's tail — atomic
RPOPLPUSH source destination           # Older, single-purpose command — same as LMOVE source destination RIGHT LEFT (deprecated in favor of LMOVE)
```

This is the building block for a **reliable queue**: pop a job from `queue:pending` and push it onto `queue:processing` in one atomic step, so a job is never silently lost between the two operations.

### 6. Blocking pop — wait for something to arrive

```bash
BLPOP key1 key2 5    # Block for up to 5 seconds waiting for ANY element to appear on key1 or key2, then pop it
BRPOP key1 key2 0    # Same, but from the tail; timeout 0 = block forever
BLMOVE source destination LEFT RIGHT 5   # Blocking version of LMOVE
BRPOPLPUSH source destination 5          # Older, single-purpose blocking move (deprecated in favor of BLMOVE)
```

This is exactly how a **background worker** waits on a job queue instead of polling in a loop: `BLPOP jobs:queue 0` sleeps until a job shows up, then wakes up and processes it immediately.

### 7. Popping from whichever of several lists has something (Redis 7.0+)

```bash
LMPOP 2 queue:a queue:b LEFT COUNT 2     # Pop up to 2 elements from the first of queue:a/queue:b that isn't empty
BLMPOP 5 2 queue:a queue:b LEFT COUNT 2  # Same, but blocks up to 5 seconds if both are empty
```

Useful when a worker should drain whichever of several queues has work first, instead of checking each one manually.

### 8. Finding an element's position (Redis 6.2+)

```bash
LPOS key "value"                 # Index of the first matching element (or nil if not found)
LPOS key "value" RANK -1         # Search from the tail instead of the head
LPOS key "value" COUNT 0         # Return the indexes of ALL matches
```

### 9. Generic key commands you'll use alongside lists

```bash
EXISTS key      # 1 if the key exists, 0 if not
TYPE key        # -> list
DEL key         # Delete the whole list
EXPIRE key 60   # TTL applies to the whole list, not individual elements
```

### 10. Bonus: multi-element move (Redis 8.10+, very new)

```bash
LMOVEM source destination LEFT LEFT COUNT 2 BULK   # Move up to 2 elements at once, atomically
```

`LMOVEM` extends `LMOVE` to move several elements in a single atomic step instead of one at a time. This landed in Redis 8.10 (mid-2026) — recent enough that it's worth knowing exists, but not something you'll see in most tutorials yet.

---

## Complete List Command Cheat Sheet

| Command | What it does | redis-py method |
|---|---|---|
| `LPUSH key v1 v2 ...` | Push one or more values onto the head | `lpush(key, *values)` |
| `RPUSH key v1 v2 ...` | Push one or more values onto the tail | `rpush(key, *values)` |
| `LPUSHX key value` | Push onto the head, only if the key exists | `lpushx(key, value)` |
| `RPUSHX key value` | Push onto the tail, only if the key exists | `rpushx(key, value)` |
| `LPOP key [count]` | Remove & return from the head | `lpop(key, count=None)` |
| `RPOP key [count]` | Remove & return from the tail | `rpop(key, count=None)` |
| `LLEN key` | Number of elements in the list | `llen(key)` |
| `LRANGE key start stop` | Read a range of elements | `lrange(key, start, stop)` |
| `LINDEX key index` | Read a single element by index | `lindex(key, index)` |
| `LSET key index value` | Overwrite the element at an index | `lset(key, index, value)` |
| `LINSERT key BEFORE\|AFTER pivot value` | Insert relative to an existing element | `linsert(key, where, refvalue, value)` |
| `LREM key count value` | Remove occurrences of a value | `lrem(key, count, value)` |
| `LTRIM key start stop` | Shrink the list down to a range | `ltrim(key, start, stop)` |
| `LMOVE source destination LEFT\|RIGHT LEFT\|RIGHT` | Atomically move one element between lists | `lmove(src, dst, src_side, dst_side)` |
| `RPOPLPUSH source destination` | (Deprecated) same as `LMOVE ... RIGHT LEFT` | `rpoplpush(src, dst)` |
| `BLPOP key1 key2 ... timeout` | Blocking pop from the head of the first non-empty key | `blpop(keys, timeout)` |
| `BRPOP key1 key2 ... timeout` | Blocking pop from the tail | `brpop(keys, timeout)` |
| `BLMOVE source destination LEFT\|RIGHT LEFT\|RIGHT timeout` | Blocking version of `LMOVE` | `blmove(src, dst, timeout, src_side, dst_side)` |
| `BRPOPLPUSH source destination timeout` | (Deprecated) blocking version of `RPOPLPUSH` | `brpoplpush(src, dst, timeout)` |
| `LMPOP numkeys key1 key2 ... LEFT\|RIGHT [COUNT n]` | Pop from the first non-empty of several lists | `lmpop(keys, direction, count=None)` |
| `BLMPOP timeout numkeys key1 key2 ... LEFT\|RIGHT [COUNT n]` | Blocking version of `LMPOP` | `blmpop(timeout, keys, direction, count=None)` |
| `LPOS key value [RANK r] [COUNT c]` | Find the index/indexes of a value | `lpos(key, value, rank=None, count=None)` |
| `LMOVEM source destination side side [COUNT\|EXACTLY n MODE]` | Atomically move several elements at once (Redis 8.10+) | Check your client version's support |
| `EXISTS key` | 1 if the key exists, 0 if not | `exists(key)` |
| `TYPE key` | What data type this key holds | `type(key)` |
| `DEL key` | Delete the key entirely | `delete(key)` |