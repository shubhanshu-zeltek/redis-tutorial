"""Redis Sets — https://redis.io/docs/latest/develop/data-types/sets

An unordered collection of unique strings. Add, remove and membership tests are
all O(1), and Redis gives you the algebra for free: union, intersection and
difference across any number of sets, server-side.
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


# --- Membership ---

def add_members(key, *members):
    global redis_client
    return redis_client.sadd(key, *members)

def remove_members(key, *members):
    global redis_client
    return redis_client.srem(key, *members)

def get_all_members(key):
    """SMEMBERS — pulls everything; on big sets prefer SSCAN."""
    global redis_client
    return redis_client.smembers(key)

def count_members(key):
    global redis_client
    return redis_client.scard(key)

def is_member(key, value):
    global redis_client
    return redis_client.sismember(key, value)

def are_members(key, *values):
    """SMISMEMBER — check many members in one round trip (Redis 6.2+)."""
    global redis_client
    return redis_client.smismember(key, list(values))

def scan_members(key, match=None, count=None):
    """SSCAN — non-blocking cursor iteration over a large set."""
    global redis_client
    cursor = 0
    found = []
    while True:
        cursor, data = redis_client.sscan(key, cursor=cursor, match=match, count=count)
        found.extend(data)
        if cursor == 0:
            return found


# --- Random access / moving ---

def pop_random(key, count=None):
    """SPOP — remove and return random member(s)."""
    global redis_client
    return redis_client.spop(key, count)

def peek_random(key, count=None):
    """SRANDMEMBER — like SPOP but leaves the set alone. Negative count allows repeats."""
    global redis_client
    return redis_client.srandmember(key, count)

def move_member(source, destination, member):
    """SMOVE — atomically move one member between sets."""
    global redis_client
    return redis_client.smove(source, destination, member)


# --- Set algebra ---

def intersection(*keys):
    global redis_client
    return redis_client.sinter(*keys)

def union(*keys):
    global redis_client
    return redis_client.sunion(*keys)

def difference(*keys):
    """SDIFF — members of the first key that are in none of the others."""
    global redis_client
    return redis_client.sdiff(*keys)

def intersection_store(destination, *keys):
    global redis_client
    return redis_client.sinterstore(destination, *keys)

def union_store(destination, *keys):
    global redis_client
    return redis_client.sunionstore(destination, *keys)

def difference_store(destination, *keys):
    global redis_client
    return redis_client.sdiffstore(destination, *keys)

def intersection_count(*keys, limit=0):
    """SINTERCARD — size of the intersection without materialising it (Redis 7.0+).
    limit>0 stops counting early, which keeps worst-case cost bounded."""
    global redis_client
    return redis_client.sintercard(len(keys), list(keys), limit=limit)


def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    a, b, c = "article:1:tags", "article:2:tags", "article:3:tags"
    delete_keys(a, b, c, "tags:shared", "tags:all", "tags:only:1", "raffle")

    print("(*) SADD — tagging three articles.")
    print(add_members(a, "python", "redis", "backend", "caching"))
    print(add_members(b, "redis", "database", "nosql", "caching"))
    print(add_members(c, "python", "redis", "ml"))

    print("(*) SADD is idempotent — re-adding an existing member returns 0.")
    print(add_members(a, "python"))

    print("(*) SMEMBERS and SCARD.")
    print(get_all_members(a))
    print(count_members(a))

    print("(*) SISMEMBER — one check.")
    print(is_member(a, "python"), is_member(a, "java"))

    print("(*) SMISMEMBER — many checks in one round trip (Redis 6.2+).")
    print(are_members(a, "python", "java", "redis"))

    print("(*) SINTER — tags shared by all three articles.")
    print(intersection(a, b, c))

    print("(*) SUNION — every distinct tag across the three.")
    print(union(a, b, c))

    print("(*) SDIFF — tags unique to article 1.")
    print(difference(a, b, c))

    print("(*) SINTERCARD — the SIZE of the intersection, without building it.")
    print(intersection_count(a, b, c))

    print("(*) SINTERCARD with LIMIT=1 — stop as soon as 1 match is found.")
    print(intersection_count(a, b, c, limit=1))

    print("(*) The *STORE variants persist the result into a new set.")
    print(intersection_store("tags:shared", a, b))
    print(get_all_members("tags:shared"))
    print(union_store("tags:all", a, b, c))
    print(count_members("tags:all"))
    print(difference_store("tags:only:1", a, b))
    print(get_all_members("tags:only:1"))

    print("(*) SREM — untag 'backend' from article 1.")
    print(remove_members(a, "backend"))
    print(get_all_members(a))

    print("(*) SREM on a member that isn't there returns 0.")
    print(remove_members(a, "rust"))

    print("(*) SMOVE — hand 'python' over from article 1 to article 2.")
    print(move_member(a, b, "python"))
    print("article1:", get_all_members(a))
    print("article2:", get_all_members(b))

    print("(*) SRANDMEMBER — peek without removing.")
    print(peek_random(b))
    print(peek_random(b, 2))

    print("(*) SRANDMEMBER with a NEGATIVE count can repeat members.")
    print(peek_random(b, -6))

    print("(*) SPOP — a raffle draw: remove and return random winners.")
    add_members("raffle", *[f"ticket:{i}" for i in range(1, 11)])
    print("winner:", pop_random("raffle"))
    print("two more:", pop_random("raffle", 2))
    print("tickets left:", count_members("raffle"))

    print("(*) SSCAN — iterate a set without blocking the server.")
    print(sorted(scan_members("raffle")))

    print("(*) SSCAN with MATCH — only tickets ending in a single digit 1-3.")
    print(sorted(scan_members("raffle", match="ticket:[1-3]")))

    print("(*) Cleaning up.")
    print(delete_keys(a, b, c, "tags:shared", "tags:all", "tags:only:1", "raffle"))
