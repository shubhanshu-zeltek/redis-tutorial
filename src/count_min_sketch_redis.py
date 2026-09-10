"""Redis Count-min sketch — https://redis.io/docs/latest/develop/data-types/probabilistic/count-min-sketch

Estimates HOW MANY TIMES each item appeared in a stream, in fixed memory.

Where a Bloom filter answers "seen it?", a CMS answers "seen it how often?".
The estimate is never an undercount — hash collisions can only inflate it — so
treat every answer as an upper bound. Heavy hitters stay accurate; rare items
are the ones that drift.

Sizing: INITBYDIM(width, depth) is explicit, INITBYPROB(error, probability) lets
Redis pick the dimensions from the accuracy you want.

Requires the Bloom module — start Redis Stack:
    docker compose -f docker-compose-stack.yaml.yaml up -d
"""

import random

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def init_by_dimensions(key, width, depth):
    """CMS.INITBYDIM — width = counters per row, depth = number of hash rows."""
    global redis_client
    return redis_client.cms().initbydim(key, width, depth)

def init_by_probability(key, error, probability):
    """CMS.INITBYPROB — error is relative to the total count; probability is the
    chance the error bound is exceeded."""
    global redis_client
    return redis_client.cms().initbyprob(key, error, probability)

def increment(key, items, increments):
    """CMS.INCRBY — items and increments are parallel lists."""
    global redis_client
    return redis_client.cms().incrby(key, items, increments)

def query(key, *items):
    """CMS.QUERY — estimated count per item."""
    global redis_client
    return redis_client.cms().query(key, *items)

def merge(destination, sources, weights=None):
    """CMS.MERGE — combine sketches of the SAME dimensions, optionally weighted."""
    global redis_client
    return redis_client.cms().merge(destination, len(sources), sources,
                                    weights=weights or [])

def info(key):
    """CMS.INFO. redis-py wraps the reply in a CMSInfo object; vars() makes it printable."""
    global redis_client
    raw = redis_client.cms().info(key)
    return vars(raw) if hasattr(raw, "__dict__") else raw

def memory_bytes(key):
    global redis_client
    return redis_client.memory_usage(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "page:hits"
    delete_keys(key, "cms:prob", "cms:day1", "cms:day2", "cms:total",
                "cms:weighted", "cms:accuracy", "cms:exact")

    try:
        print("(*) CMS.INITBYDIM — 2000 counters wide, 5 hash rows deep.")
        print(init_by_dimensions(key, 2000, 5))
    except redis.exceptions.ModuleError:
        raise SystemExit(
            "This script needs the Bloom module. Start Redis Stack instead of plain Redis:\n"
            "    docker compose -f docker-compose-stack.yaml.yaml up -d"
        )

    print("(*) CMS.INCRBY — record page hits.")
    print(increment(key, ["/home", "/pricing", "/docs"], [120, 45, 300]))

    print("(*) Incrementing again accumulates.")
    print(increment(key, ["/home", "/docs"], [30, 5]))

    print("(*) CMS.QUERY — estimated hits per page.")
    print(query(key, "/home", "/pricing", "/docs"))

    print("(*) Querying a page that was never recorded usually returns 0,")
    print("    but may return a small inflated number due to hash collisions.")
    print(query(key, "/never-visited"))

    print("(*) CMS.INFO — the dimensions and the total count ingested.")
    print(info(key))

    print("(*) CMS.INITBYPROB — size it from the accuracy you want instead:")
    print("    error <= 0.1% of the total, held with 99.9% probability.")
    print(init_by_probability("cms:prob", 0.001, 0.999))
    print(info("cms:prob"))

    print("(*) CMS.MERGE — roll two daily sketches into a total.")
    print("    Merging requires identical width and depth.")
    init_by_dimensions("cms:day1", 2000, 5)
    init_by_dimensions("cms:day2", 2000, 5)
    init_by_dimensions("cms:total", 2000, 5)
    increment("cms:day1", ["/home", "/docs"], [100, 200])
    increment("cms:day2", ["/home", "/blog"], [50, 75])
    print(merge("cms:total", ["cms:day1", "cms:day2"]))
    print(query("cms:total", "/home", "/docs", "/blog"))

    print("(*) Weighted merge — count day 2 three times over.")
    init_by_dimensions("cms:weighted", 2000, 5)
    print(merge("cms:weighted", ["cms:day1", "cms:day2"], weights=[1, 3]))
    print(query("cms:weighted", "/home", "/docs", "/blog"))

    print("(*) Accuracy check against exact counts.")
    print("    A skewed stream: 5 hot keys plus a 50,000-key long tail.")
    init_by_probability("cms:accuracy", 0.001, 0.999)
    random.seed(42)

    exact = {"/home": 60_000, "/docs": 35_000, "/pricing": 18_000,
             "/blog": 9_000, "/about": 4_000}
    for _ in range(120_000):
        item = f"key:{random.randrange(50_000)}"
        exact[item] = exact.get(item, 0) + 1

    # CMS.INCRBY takes parallel item/increment lists, so the whole stream goes
    # in as a handful of batched commands rather than 200,000 round trips.
    items = list(exact)
    for start in range(0, len(items), 500):
        chunk = items[start:start + 500]
        increment("cms:accuracy", chunk, [exact[i] for i in chunk])

    heaviest = sorted(exact.items(), key=lambda kv: -kv[1])[:5]
    print("    heavy hitters (exact vs estimate):")
    for item, real in heaviest:
        est = query("cms:accuracy", item)[0]
        print(f"      {item:<12} exact={real:<7} est={est:<7} over by {est - real}")

    rarest = [kv for kv in exact.items() if kv[1] == 1][:5]
    print("    rare items (exact vs estimate) — this is where CMS drifts:")
    for item, real in rarest:
        est = query("cms:accuracy", item)[0]
        print(f"      {item:<12} exact={real:<7} est={est:<7} over by {est - real}")

    print("(*) A CMS never undercounts — every estimate is >= the true count.")
    undercounts = sum(1 for item, real in list(exact.items())[:500]
                      if query("cms:accuracy", item)[0] < real)
    print(f"    undercounts among 500 sampled keys: {undercounts}")

    print("(*) Memory: the sketch is fixed-size, an exact hash grows with the")
    print("    number of distinct keys.")
    redis_client.hset("cms:exact", mapping=exact)
    print(f"    distinct keys: {len(exact)}")
    print(f"    sketch:        {memory_bytes('cms:accuracy')} bytes")
    print(f"    exact hash:    {memory_bytes('cms:exact')} bytes")

    print("(*) Note there is no 'list the top items' command here — a CMS can only")
    print("    answer for a key you name. Use top_k_redis.py for the ranking itself.")

    print("(*) Cleaning up.")
    print(delete_keys(key, "cms:prob", "cms:day1", "cms:day2", "cms:total",
                      "cms:weighted", "cms:accuracy", "cms:exact"))
