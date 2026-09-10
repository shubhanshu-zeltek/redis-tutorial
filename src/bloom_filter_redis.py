"""Redis Bloom filter — https://redis.io/docs/latest/develop/data-types/probabilistic/bloom-filter

Answers "have I seen this before?" in a fraction of the memory a Set would need.

The guarantee is one-sided:
  * "no"  is always correct — a false negative is impossible.
  * "yes" may be wrong, at roughly the configured error rate.
And you can never remove an item (use a Cuckoo filter if you need deletes).

Requires the Bloom module — start Redis Stack:
    docker compose -f docker-compose-stack.yaml.yaml up -d
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def reserve(key, error_rate, capacity, expansion=None, non_scaling=None):
    """BF.RESERVE — size it up front. Once capacity is exceeded the filter either
    scales (default, at some accuracy cost) or errors out if non_scaling."""
    global redis_client
    return redis_client.bf().create(key, error_rate, capacity,
                                    expansion=expansion, noScale=non_scaling)

def add_item(key, item):
    """BF.ADD — 1 if newly added, 0 if it probably existed already."""
    global redis_client
    return redis_client.bf().add(key, item)

def add_items(key, *items):
    global redis_client
    return redis_client.bf().madd(key, *items)

def insert(key, items, capacity=None, error=None, no_create=None, expansion=None):
    """BF.INSERT — add many items and optionally create the filter in the same call."""
    global redis_client
    return redis_client.bf().insert(key, items, capacity=capacity, error=error,
                                    noCreate=no_create, expansion=expansion)

def exists(key, item):
    global redis_client
    return redis_client.bf().exists(key, item)

def exist_many(key, *items):
    global redis_client
    return redis_client.bf().mexists(key, *items)

def cardinality(key):
    """BF.CARD — number of items added."""
    global redis_client
    return redis_client.bf().card(key)

def info(key):
    """BF.INFO. redis-py wraps the reply in a BFInfo object; vars() makes it printable."""
    global redis_client
    raw = redis_client.bf().info(key)
    return vars(raw) if hasattr(raw, "__dict__") else raw

def memory_bytes(key):
    global redis_client
    return redis_client.memory_usage(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "seen:usernames"
    delete_keys(key, "bf:auto", "bf:strict", "bf:accuracy", "seen:exact")

    try:
        print("(*) BF.RESERVE — 0.1% error rate, sized for 10,000 usernames.")
        print(reserve(key, 0.001, 10_000))
    except redis.exceptions.ModuleError:
        raise SystemExit(
            "This script needs the Bloom module. Start Redis Stack instead of plain Redis:\n"
            "    docker compose -f docker-compose-stack.yaml.yaml up -d"
        )

    print("(*) BF.ADD — 1 means 'definitely new'.")
    print(add_item(key, "shubhanshu"))

    print("(*) BF.ADD again — 0 means 'probably already there'.")
    print(add_item(key, "shubhanshu"))

    print("(*) BF.MADD — several at once.")
    print(add_items(key, "riya", "arjun", "meera", "shubhanshu"))

    print("(*) BF.EXISTS — 1 = probably yes, 0 = definitely no.")
    print(exists(key, "riya"), exists(key, "someone-brand-new"))

    print("(*) BF.MEXISTS — batch membership check.")
    print(exist_many(key, "riya", "arjun", "nobody", "meera"))

    print("(*) BF.CARD — how many items have been added.")
    print(cardinality(key))

    print("(*) BF.INFO — capacity, size in bytes, filter count, expansion rate.")
    print(info(key))

    print("(*) BF.INSERT can create the filter and populate it in one command.")
    print(insert("bf:auto", ["a", "b", "c"], capacity=1000, error=0.01))
    print(info("bf:auto"))

    print("(*) BF.INSERT with NOCREATE on a missing key errors instead of creating.")
    try:
        print(insert("bf:never-made", ["x"], no_create=True))
    except redis.exceptions.ResponseError as exc:
        print("    refused, as expected:", exc)

    print("(*) A NONSCALING filter refuses writes past its capacity instead of")
    print("    silently degrading its error rate.")
    print(reserve("bf:strict", 0.01, 3, non_scaling=True))
    print(add_items("bf:strict", "one", "two", "three"))
    try:
        print(add_item("bf:strict", "four"))
    except redis.exceptions.ResponseError as exc:
        print("    full, as expected:", exc)

    print("(*) A SCALING filter (the default) grows by adding sub-filters.")
    print(reserve("bf:auto2", 0.01, 100, expansion=2))
    add_items("bf:auto2", *[f"item:{i}" for i in range(500)])
    print(info("bf:auto2"))

    print("(*) Measuring the actual false-positive rate.")
    print("    Insert 10,000 known items at a 1% target error rate, then probe")
    print("    10,000 items we never inserted and count the wrong 'yes' answers.")
    reserve("bf:accuracy", 0.01, 10_000, non_scaling=True)
    inserted = [f"known:{i}" for i in range(10_000)]
    for chunk_start in range(0, len(inserted), 1000):
        add_items("bf:accuracy", *inserted[chunk_start:chunk_start + 1000])
    probes = [f"unknown:{i}" for i in range(10_000)]
    false_positives = 0
    for chunk_start in range(0, len(probes), 1000):
        false_positives += sum(exist_many("bf:accuracy", *probes[chunk_start:chunk_start + 1000]))
    print(f"    false positives: {false_positives}/10000 = {false_positives / 100:.2f}%")

    print("(*) And ZERO false negatives — every inserted item is always found.")
    misses = 0
    for chunk_start in range(0, len(inserted), 1000):
        misses += sum(1 for r in exist_many("bf:accuracy", *inserted[chunk_start:chunk_start + 1000]) if r == 0)
    print(f"    missed known items: {misses}")

    print("(*) The payoff — memory vs. an exact Set holding the same 10,000 items.")
    redis_client.sadd("seen:exact", *inserted)
    print(f"    bloom filter: {memory_bytes('bf:accuracy')} bytes")
    print(f"    exact set:    {memory_bytes('seen:exact')} bytes")

    print("(*) There is no BF.DEL — Bloom filters cannot remove items.")
    print("    Use cuckoo_filter_redis.py when you need deletes.")

    print("(*) Cleaning up.")
    print(delete_keys(key, "bf:auto", "bf:auto2", "bf:strict", "bf:accuracy", "seen:exact"))
