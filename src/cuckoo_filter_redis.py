"""Redis Cuckoo filter — https://redis.io/docs/latest/develop/data-types/probabilistic/cuckoo-filter

Same job as a Bloom filter — "have I seen this?" in tiny memory — with two
differences that usually decide which one you pick:

  * Cuckoo filters SUPPORT DELETION (CF.DEL) and counting (CF.COUNT).
  * Cuckoo filters can FAIL TO INSERT once buckets get too full.

Delete only items you actually added; deleting something that was never
inserted can silently evict a real item's fingerprint.

Requires the Bloom module — start Redis Stack:
    docker compose -f docker-compose-stack.yaml.yaml up -d
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def reserve(key, capacity, expansion=None, bucket_size=None, max_iterations=None):
    """CF.RESERVE — bucket_size trades memory for a lower failure rate;
    max_iterations caps how long insertion tries to rearrange buckets."""
    global redis_client
    return redis_client.cf().create(key, capacity, expansion=expansion,
                                    bucket_size=bucket_size, max_iterations=max_iterations)

def add_item(key, item):
    """CF.ADD — always adds, even if a copy is already present."""
    global redis_client
    return redis_client.cf().add(key, item)

def add_item_if_absent(key, item):
    """CF.ADDNX — add only if the item probably isn't there yet."""
    global redis_client
    return redis_client.cf().addnx(key, item)

def insert(key, items, capacity=None, no_create=None):
    global redis_client
    return redis_client.cf().insert(key, items, capacity=capacity, nocreate=no_create)

def insert_if_absent(key, items, capacity=None, no_create=None):
    global redis_client
    return redis_client.cf().insertnx(key, items, capacity=capacity, nocreate=no_create)

def exists(key, item):
    global redis_client
    return redis_client.cf().exists(key, item)

def exist_many(key, *items):
    global redis_client
    return redis_client.cf().mexists(key, *items)

def count(key, item):
    """CF.COUNT — how many copies of this item were added."""
    global redis_client
    return redis_client.cf().count(key, item)

def delete_item(key, item):
    """CF.DEL — removes ONE copy. The thing Bloom filters can't do."""
    global redis_client
    return redis_client.cf().delete(key, item)

def info(key):
    """CF.INFO. redis-py wraps the reply in a CFInfo object; vars() makes it printable."""
    global redis_client
    raw = redis_client.cf().info(key)
    return vars(raw) if hasattr(raw, "__dict__") else raw

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "urls:crawled"
    delete_keys(key, "cf:auto", "cf:tiny", "cf:dupes")

    try:
        print("(*) CF.RESERVE — sized for 10,000 URLs.")
        print(reserve(key, 10_000))
    except redis.exceptions.ModuleError:
        raise SystemExit(
            "This script needs the Bloom module. Start Redis Stack instead of plain Redis:\n"
            "    docker compose -f docker-compose-stack.yaml.yaml up -d"
        )

    print("(*) CF.ADD.")
    print(add_item(key, "https://redis.io/"))
    print(add_item(key, "https://redis.io/docs/"))

    print("(*) CF.ADD again on the same URL succeeds — it adds a SECOND copy.")
    print(add_item(key, "https://redis.io/"))

    print("(*) CF.COUNT confirms two copies are tracked.")
    print(count(key, "https://redis.io/"))

    print("(*) CF.ADDNX is the deduplicating version — 0 means 'already there'.")
    print(add_item_if_absent(key, "https://redis.io/"))
    print(add_item_if_absent(key, "https://redis.io/commands/"))

    print("(*) CF.EXISTS / CF.MEXISTS.")
    print(exists(key, "https://redis.io/docs/"), exists(key, "https://example.com/"))
    print(exist_many(key, "https://redis.io/", "https://example.com/", "https://redis.io/commands/"))

    print("(*) CF.DEL — remove one copy. Bloom filters have no equivalent.")
    print(delete_item(key, "https://redis.io/"))
    print("copies left:", count(key, "https://redis.io/"), " still present:", exists(key, "https://redis.io/"))

    print("(*) Delete the last copy and the item genuinely disappears.")
    print(delete_item(key, "https://redis.io/"))
    print("copies left:", count(key, "https://redis.io/"), " still present:", exists(key, "https://redis.io/"))

    print("(*) CF.DEL on something that was never added returns 0.")
    print(delete_item(key, "https://never-seen.example/"))

    print("(*) CF.INSERT — bulk add, creating the filter on the fly.")
    print(insert("cf:auto", ["a", "b", "c", "a"], capacity=1000))
    print("count of 'a':", count("cf:auto", "a"))

    print("(*) CF.INSERTNX — bulk add, skipping duplicates. 0 = already present.")
    print(insert_if_absent("cf:auto", ["a", "b", "d", "e"]))

    print("(*) CF.INSERT with NOCREATE on a missing key errors instead of creating.")
    try:
        print(insert("cf:never-made", ["x"], no_create=True))
    except redis.exceptions.ResponseError as exc:
        print("    refused, as expected:", exc)

    print("(*) CF.INFO — size, bucket layout, insert/delete counters.")
    print(info(key))

    print("(*) The cuckoo trade-off: insertion can FAIL when buckets are crowded.")
    print("    A deliberately tiny filter with max_iterations=1 to force it.")
    print(reserve("cf:tiny", 8, bucket_size=1, max_iterations=1, expansion=0))
    failures = 0
    for i in range(200):
        try:
            if add_item("cf:tiny", f"item:{i}") == 0:
                failures += 1
        except redis.exceptions.ResponseError:
            failures += 1
            break
    print(f"    insertions rejected after filling up: {failures > 0}")
    print("   ", info("cf:tiny"))

    print("(*) Counting duplicates is a genuine cuckoo feature.")
    for _ in range(5):
        add_item("cf:dupes", "hot-key")
    print("copies:", count("cf:dupes", "hot-key"))
    delete_item("cf:dupes", "hot-key")
    print("after one delete:", count("cf:dupes", "hot-key"))

    print("(*) Like Bloom, 'no' is always trustworthy and 'yes' can be a false")
    print("    positive — but unlike Bloom, deleting an item you never inserted")
    print("    can corrupt the filter, so only delete what you added.")

    print("(*) Cleaning up.")
    print(delete_keys(key, "cf:auto", "cf:tiny", "cf:dupes"))
