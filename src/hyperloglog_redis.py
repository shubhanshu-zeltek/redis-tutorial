"""Redis HyperLogLog — https://redis.io/docs/latest/develop/data-types/probabilistic/hyperloglogs

Counts DISTINCT items using a fixed 12 KB, no matter whether you feed it a
hundred items or a billion. Standard error is ~0.81%.

The trade-off: you can ask "how many unique?" but never "is X in there?" or
"list them". If you need membership, use a Set or a Bloom filter instead.

HLLs are plain strings under the hood, so no module is required.
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def add_items(key, *items):
    """PFADD — returns 1 if the internal registers changed, 0 if nothing new."""
    global redis_client
    return redis_client.pfadd(key, *items)

def count_unique(*keys):
    """PFCOUNT — approximate cardinality. Several keys = union, computed on the fly."""
    global redis_client
    return redis_client.pfcount(*keys)

def merge(destination, *sources):
    """PFMERGE — union several HLLs into one, still 12 KB."""
    global redis_client
    return redis_client.pfmerge(destination, *sources)

def byte_size(key):
    global redis_client
    return redis_client.strlen(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    mon, tue, week = "uv:2026-09-07", "uv:2026-09-08", "uv:week-37"
    delete_keys(mon, tue, week, "uv:exact", "uv:big")

    print("(*) PFADD — unique visitors on Monday.")
    print(add_items(mon, "user:1", "user:2", "user:3"))

    print("(*) PFADD returns 0 when nothing new is observed.")
    print(add_items(mon, "user:1", "user:2"))

    print("(*) ...and 1 again as soon as a genuinely new item shows up.")
    print(add_items(mon, "user:4"))

    print("(*) PFCOUNT — unique visitors so far.")
    print(count_unique(mon))

    print("(*) Tuesday, overlapping with Monday.")
    print(add_items(tue, "user:3", "user:4", "user:5", "user:6"))
    print(count_unique(tue))

    print("(*) PFCOUNT over MULTIPLE keys computes the union without storing it.")
    print("    Monday ∪ Tuesday =", count_unique(mon, tue), "(6 distinct users)")

    print("(*) PFMERGE — materialise that union into a weekly rollup key.")
    print(merge(week, mon, tue))
    print(count_unique(week))

    print("(*) Merging is idempotent — re-merging the same days changes nothing.")
    print(merge(week, mon, tue))
    print(count_unique(week))

    print("(*) A fresh day merged in only adds the genuinely new users.")
    add_items("uv:2026-09-09", "user:6", "user:7")
    merge(week, "uv:2026-09-09")
    print(count_unique(week))

    print("(*) Accuracy check: feed 100,000 distinct items and compare.")
    pipe = redis_client.pipeline()
    for i in range(100_000):
        pipe.pfadd("uv:big", f"visitor:{i}")
        if i % 10_000 == 0:
            pipe.execute()
            pipe = redis_client.pipeline()
    pipe.execute()
    estimate = count_unique("uv:big")
    error = abs(estimate - 100_000) / 100_000 * 100
    print(f"    exact: 100000  estimate: {estimate}  error: {error:.3f}%")

    print("(*) The whole point: memory is constant regardless of cardinality.")
    print(f"    4 items  -> {byte_size(mon)} bytes")
    print(f"    100k items -> {byte_size('uv:big')} bytes")
    print("    (An exact Set of 100k user ids would cost several megabytes.)")

    print("(*) For comparison, the same 4 users in a real Set — exact, but listable")
    print("    and unbounded in memory.")
    redis_client.sadd("uv:exact", "user:1", "user:2", "user:3", "user:4")
    print("SCARD:", redis_client.scard("uv:exact"), " members:", redis_client.smembers("uv:exact"))
    print("An HLL cannot do that — there is no PFMEMBERS.")

    print("(*) Cleaning up.")
    print(delete_keys(mon, tue, week, "uv:2026-09-09", "uv:exact", "uv:big"))
