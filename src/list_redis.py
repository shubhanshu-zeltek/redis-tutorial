"""Redis Lists — https://redis.io/docs/latest/develop/data-types/lists

A list is a linked list of strings kept in insertion order. Pushing and popping
at either end is O(1), which is why lists are the natural fit for stacks,
queues, and capped activity feeds.

Mental model: LPUSH adds to the head (left), RPUSH to the tail (right).
  Stack  = LPUSH + LPOP  (same end)
  Queue  = LPUSH + RPOP  (opposite ends)
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


# --- Pushing ---

def push_left(key, *values):
    global redis_client
    return redis_client.lpush(key, *values)

def push_right(key, *values):
    global redis_client
    return redis_client.rpush(key, *values)

def push_left_if_exists(key, *values):
    """LPUSHX — no-op when the list doesn't exist yet."""
    global redis_client
    return redis_client.lpushx(key, *values)

def push_right_if_exists(key, *values):
    global redis_client
    return redis_client.rpushx(key, *values)


# --- Popping ---

def pop_left(key, count=None):
    global redis_client
    return redis_client.lpop(key, count)

def pop_right(key, count=None):
    global redis_client
    return redis_client.rpop(key, count)

def blocking_pop_left(keys, timeout=0):
    """BLPOP — block until an element arrives on any of the keys."""
    global redis_client
    return redis_client.blpop(keys, timeout)

def blocking_pop_right(keys, timeout=0):
    global redis_client
    return redis_client.brpop(keys, timeout)

def pop_many(direction, *keys, count=1):
    """LMPOP — pop from the first non-empty list among several (Redis 7.0+)."""
    global redis_client
    return redis_client.lmpop(len(keys), *keys, direction=direction, count=count)

def blocking_pop_many(timeout, direction, *keys, count=1):
    """BLMPOP — the blocking flavour of LMPOP."""
    global redis_client
    return redis_client.blmpop(timeout, len(keys), *keys, direction=direction, count=count)


# --- Reading ---

def get_range(key, start=0, end=-1):
    global redis_client
    return redis_client.lrange(key, start, end)

def length(key):
    global redis_client
    return redis_client.llen(key)

def get_at(key, index):
    """LINDEX — O(N); fine near either end, avoid in the middle of a huge list."""
    global redis_client
    return redis_client.lindex(key, index)

def find_position(key, value, rank=None, count=None, maxlen=None):
    """LPOS — index of a matching element. rank=-1 searches from the tail."""
    global redis_client
    return redis_client.lpos(key, value, rank=rank, count=count, maxlen=maxlen)


# --- Modifying in place ---

def set_at(key, index, value):
    global redis_client
    return redis_client.lset(key, index, value)

def insert_relative(key, where, refvalue, value):
    """LINSERT — put a value BEFORE or AFTER the first match of refvalue."""
    global redis_client
    return redis_client.linsert(key, where, refvalue, value)

def remove_value(key, count, value):
    """LREM — count>0 removes from head, count<0 from tail, 0 removes all."""
    global redis_client
    return redis_client.lrem(key, count, value)

def trim(key, start, end):
    """LTRIM — keep only [start, end]. Pair with LPUSH for a capped feed."""
    global redis_client
    return redis_client.ltrim(key, start, end)


# --- Moving between lists ---

def move(source, destination, src_side="LEFT", dest_side="RIGHT"):
    """LMOVE — atomically pop from one list and push onto another."""
    global redis_client
    return redis_client.lmove(source, destination, src_side, dest_side)

def blocking_move(source, destination, timeout=0, src_side="LEFT", dest_side="RIGHT"):
    global redis_client
    return redis_client.blmove(source, destination, timeout, src_side, dest_side)

def rotate(source, destination):
    """RPOPLPUSH — the older, still handy tail->head move."""
    global redis_client
    return redis_client.rpoplpush(source, destination)


def sort_list(key, **kwargs):
    """SORT — kwargs: start/num, by, get, desc, alpha, store."""
    global redis_client
    return redis_client.sort(key, **kwargs)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    delete_keys("tasks:pending", "tasks:processing", "feed:user:1", "letters",
                "numbers", "empty:list", "queue:a", "queue:b")

    print("(*) RPUSH — building a queue, oldest at the head.")
    print(push_right("tasks:pending", "email:1", "email:2", "email:3", "email:4"))

    print("(*) LRANGE 0 -1 — the whole list, head first.")
    print(get_range("tasks:pending"))

    print("(*) LLEN.")
    print(length("tasks:pending"))

    print("(*) LPOP — take the oldest task (FIFO).")
    print(pop_left("tasks:pending"))

    print("(*) LPOP with a count — take the next two at once.")
    print(pop_left("tasks:pending", 2))

    print("(*) LPUSH — a stack instead: newest at the head.")
    print(push_left("letters", "a", "b", "c"))
    print(get_range("letters"))

    print("(*) LPOP on that stack returns the most recent push (LIFO).")
    print(pop_left("letters"))

    print("(*) LPUSHX on a missing key does nothing and returns 0.")
    print(push_left_if_exists("empty:list", "ignored"))
    print(get_range("empty:list"))

    print("(*) RPUSHX on a list that DOES exist appends normally.")
    print(push_right_if_exists("letters", "z"))
    print(get_range("letters"))

    print("(*) LINDEX — first, last, and second element.")
    print(get_at("letters", 0), get_at("letters", -1), get_at("letters", 1))

    print("(*) LSET — overwrite by index.")
    print(set_at("letters", 0, "A"))
    print(get_range("letters"))

    print("(*) LINSERT — put 'b2' right after 'b'.")
    print(insert_relative("letters", "AFTER", "b", "b2"))
    print(get_range("letters"))

    print("(*) LINSERT BEFORE a value that isn't there returns -1.")
    print(insert_relative("letters", "BEFORE", "missing", "nope"))

    print("(*) LPOS — where is 'b2'?")
    print(find_position("letters", "b2"))

    print("(*) LPOS with duplicates: find the 1st, the 2nd (rank=2), the last (rank=-1),")
    print("    and every occurrence (count=0).")
    delete_keys("numbers")
    push_right("numbers", "1", "2", "3", "2", "5", "2")
    print(find_position("numbers", "2"))
    print(find_position("numbers", "2", rank=2))
    print(find_position("numbers", "2", rank=-1))
    print(find_position("numbers", "2", count=0))

    print("(*) LREM — remove the first two '2's from the head.")
    print(remove_value("numbers", 2, "2"))
    print(get_range("numbers"))

    print("(*) LREM with count=0 — remove every remaining '2'.")
    print(remove_value("numbers", 0, "2"))
    print(get_range("numbers"))

    print("(*) A capped activity feed: LPUSH the new event, LTRIM to the newest 5.")
    for i in range(1, 9):
        push_left("feed:user:1", f"event:{i}")
        trim("feed:user:1", 0, 4)
    print(get_range("feed:user:1"))

    print("(*) A reliable worker queue: LMOVE from pending into processing,")
    print("    so a crashed worker never loses the job.")
    delete_keys("tasks:pending", "tasks:processing")
    push_right("tasks:pending", "job:1", "job:2", "job:3")
    job = move("tasks:pending", "tasks:processing", "LEFT", "RIGHT")
    print("claimed:", job)
    print("pending:", get_range("tasks:pending"))
    print("processing:", get_range("tasks:processing"))

    print("(*) Job finished — LREM it out of the processing list.")
    print(remove_value("tasks:processing", 1, job))
    print("processing:", get_range("tasks:processing"))

    print("(*) RPOPLPUSH onto the same key rotates a round-robin list.")
    delete_keys("queue:a")
    push_right("queue:a", "w1", "w2", "w3")
    print(rotate("queue:a", "queue:a"))
    print(get_range("queue:a"))

    print("(*) LMPOP — pop from whichever of these lists is non-empty (Redis 7.0+).")
    delete_keys("queue:a", "queue:b")
    push_right("queue:b", "x", "y", "z")
    print(pop_many("LEFT", "queue:a", "queue:b", count=2))

    print("(*) BLPOP with a 1s timeout on an empty list — returns None, doesn't hang.")
    print(blocking_pop_left(["queue:a"], timeout=1))

    print("(*) BLPOP when data IS available returns immediately as (key, value).")
    push_right("queue:a", "ready")
    print(blocking_pop_left(["queue:a"], timeout=1))

    print("(*) BLMPOP — blocking multi-key pop, 1s timeout.")
    push_right("queue:a", "m1", "m2")
    print(blocking_pop_many(1, "RIGHT", "queue:a", "queue:b", count=2))

    print("(*) BLMOVE — blocking hand-off between two lists.")
    push_right("queue:a", "handoff")
    print(blocking_move("queue:a", "queue:b", timeout=1, src_side="LEFT", dest_side="RIGHT"))
    print(get_range("queue:b"))

    print("(*) SORT — numerically, then descending, then only the top 2.")
    delete_keys("numbers")
    push_right("numbers", 30, 4, 100, 25, 7)
    print(sort_list("numbers"))
    print(sort_list("numbers", desc=True))
    print(sort_list("numbers", start=0, num=2, desc=True))

    print("(*) SORT with alpha=True for non-numeric values.")
    print(sort_list("letters", alpha=True))

    print("(*) SORT ... STORE writes the sorted result into a new list.")
    print(sort_list("numbers", store="numbers:sorted"))
    print(get_range("numbers:sorted"))

    print("(*) Cleaning up.")
    print(delete_keys("tasks:pending", "tasks:processing", "feed:user:1", "letters",
                      "numbers", "numbers:sorted", "queue:a", "queue:b"))
