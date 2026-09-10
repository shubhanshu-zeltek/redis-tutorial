"""Redis Top-K — https://redis.io/docs/latest/develop/data-types/probabilistic/top-k

Keeps a running list of the K most frequent items in a stream, in fixed memory.

A Count-min sketch can tell you how often "/docs" was hit, but only if you
already know to ask about "/docs". Top-K maintains the ranking itself — it
tells you WHICH items are hot without you naming them in advance.

It uses the HeavyKeeper algorithm: incoming items probabilistically decay the
counters of items already in the list, so genuinely hot keys survive and
one-off keys get squeezed out.

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


def reserve(key, k, width=8, depth=7, decay=0.9):
    """TOPK.RESERVE — k is how many leaders to track; width/depth size the
    internal sketch; decay controls how aggressively cold items are evicted."""
    global redis_client
    return redis_client.topk().reserve(key, k, width, depth, decay)

def add_items(key, *items):
    """TOPK.ADD — returns, per item, the element it EVICTED from the list
    (or None if nothing was pushed out)."""
    global redis_client
    return redis_client.topk().add(key, *items)

def increment(key, items, increments):
    """TOPK.INCRBY — bump items by arbitrary weights."""
    global redis_client
    return redis_client.topk().incrby(key, items, increments)

def query(key, *items):
    """TOPK.QUERY — is this item currently in the top-K list? (1/0)"""
    global redis_client
    return redis_client.topk().query(key, *items)

def count(key, *items):
    """TOPK.COUNT — estimated frequency. Deprecated upstream and can undercount;
    reach for a Count-min sketch when the number itself matters."""
    global redis_client
    return redis_client.topk().count(key, *items)

def leaders(key, with_count=False):
    """TOPK.LIST — the ranking, highest first."""
    global redis_client
    return redis_client.topk().list(key, withcount=with_count)

def info(key):
    """TOPK.INFO. redis-py wraps the reply in a TopKInfo object; vars() makes it printable."""
    global redis_client
    raw = redis_client.topk().info(key)
    return vars(raw) if hasattr(raw, "__dict__") else raw

def memory_bytes(key):
    global redis_client
    return redis_client.memory_usage(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "trending:searches"
    delete_keys(key, "topk:stream", "topk:exact")

    try:
        print("(*) TOPK.RESERVE — track the 5 hottest search terms.")
        print(reserve(key, 5, width=200, depth=7, decay=0.9))
    except redis.exceptions.ModuleError:
        raise SystemExit(
            "This script needs the Bloom module. Start Redis Stack instead of plain Redis:\n"
            "    docker compose -f docker-compose-stack.yaml.yaml up -d"
        )

    print("(*) TOPK.ADD — each reply slot is the item that got EVICTED, if any.")
    print(add_items(key, "redis", "python", "docker", "redis", "kubernetes"))

    print("(*) Adding a 6th distinct term into a K=5 list starts pushing items out.")
    print(add_items(key, "terraform", "golang", "redis", "redis"))

    print("(*) TOPK.LIST — the current ranking, hottest first.")
    print(leaders(key))

    print("(*) TOPK.LIST with counts.")
    print(leaders(key, with_count=True))

    print("(*) TOPK.QUERY — is a term currently trending?")
    print(query(key, "redis", "python", "brainfuck"))

    print("(*) TOPK.COUNT — estimated frequency per term.")
    print(count(key, "redis", "python", "brainfuck"))

    print("(*) TOPK.INCRBY — weighted bumps, e.g. replaying a batch of logs.")
    print(increment(key, ["golang", "rust"], [50, 120]))
    print(leaders(key, with_count=True))

    print("(*) TOPK.INFO — k, width, depth, decay.")
    print(info(key))

    print("(*) A realistic run: 100,000 skewed search events, K=10.")
    reserve("topk:stream", 10, width=500, depth=8, decay=0.9)
    random.seed(7)

    terms = [f"term:{i}" for i in range(2000)]
    # A handful of genuinely hot terms, everything else long-tail noise.
    hot = {"term:0": 20000, "term:1": 15000, "term:2": 11000,
           "term:3": 8000, "term:4": 5000}
    exact = dict(hot)
    stream = []
    for term, n in hot.items():
        stream.extend([term] * n)
    while len(stream) < 100_000:
        t = random.choice(terms[5:])
        exact[t] = exact.get(t, 0) + 1
        stream.append(t)
    random.shuffle(stream)

    for start in range(0, len(stream), 1000):
        add_items("topk:stream", *stream[start:start + 1000])

    print("    Top-K's answer:")
    # TOPK.LIST WITHCOUNT comes back flat: [item, count, item, count, ...]
    flat = leaders("topk:stream", with_count=True)
    for term, est in zip(flat[::2], flat[1::2]):
        print(f"      {term:<12} est={est}")

    print("    The true top 10, for comparison:")
    for term, real in sorted(exact.items(), key=lambda kv: -kv[1])[:10]:
        print(f"      {term:<12} exact={real}")

    print("(*) Note Top-K optimises for getting the SET of leaders right; the")
    print("    counts it reports are approximate and tend to undercount.")

    print("(*) Memory: fixed, versus an exact tally of every distinct term.")
    redis_client.hset("topk:exact", mapping={k: v for k, v in exact.items()})
    print(f"    top-k:      {memory_bytes('topk:stream')} bytes")
    print(f"    exact hash: {memory_bytes('topk:exact')} bytes for {len(exact)} terms")

    print("(*) Cleaning up.")
    print(delete_keys(key, "topk:stream", "topk:exact"))
