"""Redis Time series — https://redis.io/docs/latest/develop/data-types/timeseries

Purpose-built storage for (timestamp, value) samples: compressed chunks,
automatic retention, label-based querying across many series at once, and
server-side downsampling via compaction rules.

You could fake this with a sorted set, but you'd lose the compression, the
aggregation, and the "query every series labelled sensor_type=temp" part.

Timestamps are milliseconds since the epoch, or '*' for "now".

Requires the timeseries module — start Redis Stack:
    docker compose -f docker-compose-stack.yaml.yaml up -d
"""

import time

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


# --- Creating and configuring series ---

def create(key, **kwargs):
    """TS.CREATE. kwargs: retention_msecs, labels, chunk_size, duplicate_policy,
    uncompressed."""
    global redis_client
    return redis_client.ts().create(key, **kwargs)

def alter(key, **kwargs):
    """TS.ALTER — change retention or labels on an existing series."""
    global redis_client
    return redis_client.ts().alter(key, **kwargs)

def info(key):
    """TS.INFO. redis-py wraps the reply in a TSInfo object; vars() makes it printable."""
    global redis_client
    raw = redis_client.ts().info(key)
    return vars(raw) if hasattr(raw, "__dict__") else raw


# --- Writing samples ---

def add(key, timestamp, value, **kwargs):
    """TS.ADD — creates the series implicitly if it doesn't exist."""
    global redis_client
    return redis_client.ts().add(key, timestamp, value, **kwargs)

def add_many(ktv_tuples):
    """TS.MADD — [(key, timestamp, value), ...] in one round trip."""
    global redis_client
    return redis_client.ts().madd(ktv_tuples)

def increment(key, value, **kwargs):
    """TS.INCRBY — treat the series as a counter sampled over time."""
    global redis_client
    return redis_client.ts().incrby(key, value, **kwargs)

def decrement(key, value, **kwargs):
    global redis_client
    return redis_client.ts().decrby(key, value, **kwargs)

def delete_range(key, from_time, to_time):
    """TS.DEL — remove samples in a closed time range."""
    global redis_client
    return redis_client.ts().delete(key, from_time, to_time)


# --- Reading ---

def latest(key, use_latest=False):
    """TS.GET — the most recent sample."""
    global redis_client
    return redis_client.ts().get(key, latest=use_latest)

def get_range(key, from_time, to_time, **kwargs):
    """TS.RANGE. kwargs: count, aggregation_type, bucket_size_msec, align,
    filter_by_ts, filter_by_min_value, filter_by_max_value, empty, latest."""
    global redis_client
    return redis_client.ts().range(key, from_time, to_time, **kwargs)

def get_range_reverse(key, from_time, to_time, **kwargs):
    global redis_client
    return redis_client.ts().revrange(key, from_time, to_time, **kwargs)


# --- Multi-series, by label ---

def latest_many(filters, **kwargs):
    """TS.MGET — last sample of every series matching the label filters."""
    global redis_client
    return redis_client.ts().mget(filters, **kwargs)

def range_many(from_time, to_time, filters, **kwargs):
    """TS.MRANGE. kwargs adds with_labels, groupby + reduce on top of TS.RANGE's."""
    global redis_client
    return redis_client.ts().mrange(from_time, to_time, filters, **kwargs)

def range_many_reverse(from_time, to_time, filters, **kwargs):
    global redis_client
    return redis_client.ts().mrevrange(from_time, to_time, filters, **kwargs)

def find_series(filters):
    """TS.QUERYINDEX — which series match these label filters?"""
    global redis_client
    return redis_client.ts().queryindex(filters)


# --- Downsampling ---

def create_rule(source, destination, aggregation_type, bucket_size_msec, align_timestamp=None):
    """TS.CREATERULE — automatically roll raw samples into a coarser series."""
    global redis_client
    return redis_client.ts().createrule(source, destination, aggregation_type,
                                        bucket_size_msec, align_timestamp)

def delete_rule(source, destination):
    global redis_client
    return redis_client.ts().deleterule(source, destination)


def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    keys = ["temp:room:1", "temp:room:2", "hum:room:1", "temp:room:1:avg1m",
            "requests:count", "temp:dupes"]
    delete_keys(*keys)

    try:
        print("(*) TS.CREATE with labels and a 1-hour retention.")
        print(create("temp:room:1", retention_msecs=3_600_000,
                     labels={"sensor": "temp", "room": "1", "floor": "2"}))
    except redis.exceptions.ModuleError:
        raise SystemExit(
            "This script needs the timeseries module. Start Redis Stack instead of plain Redis:\n"
            "    docker compose -f docker-compose-stack.yaml.yaml up -d"
        )

    create("temp:room:2", retention_msecs=3_600_000,
           labels={"sensor": "temp", "room": "2", "floor": "2"})
    create("hum:room:1", retention_msecs=3_600_000,
           labels={"sensor": "humidity", "room": "1", "floor": "2"})

    now_ms = int(time.time() * 1000)
    base = now_ms - 600_000            # start 10 minutes ago

    print("(*) TS.ADD — 60 temperature samples, 10 seconds apart.")
    for i in range(60):
        add("temp:room:1", base + i * 10_000, 20 + (i % 12) * 0.5)
    print("last sample:", latest("temp:room:1"))

    print("(*) TS.ADD with '*' uses the server's current time.")
    print(add("temp:room:1", "*", 26.5))

    print("(*) TS.MADD — write to several series in one round trip.")
    print(add_many([
        ("temp:room:2", base + 10_000, 18.0),
        ("temp:room:2", base + 20_000, 18.4),
        ("hum:room:1", base + 10_000, 55.0),
        ("hum:room:1", base + 20_000, 56.2),
    ]))

    print("(*) TS.GET — the latest sample as (timestamp, value).")
    print(latest("temp:room:1"))

    print("(*) TS.RANGE over the last 10 minutes, first 5 samples.")
    print(get_range("temp:room:1", base, now_ms, count=5))

    print("(*) TS.REVRANGE — newest first.")
    print(get_range_reverse("temp:room:1", base, now_ms, count=5))

    print("(*) TS.RANGE with '-' and '+' meaning 'the whole series'.")
    print(len(get_range("temp:room:1", "-", "+")), "samples total")

    print("(*) Downsampling on read: 1-minute AVG buckets.")
    print(get_range("temp:room:1", base, now_ms,
                    aggregation_type="avg", bucket_size_msec=60_000))

    print("(*) Other aggregators over the same window: min, max, count, sum.")
    for agg in ("min", "max", "count", "sum"):
        print(f"    {agg}:", get_range("temp:room:1", base, now_ms,
                                       aggregation_type=agg, bucket_size_msec=300_000))

    print("(*) Rate-style aggregators: range (max-min), std.p, twa.")
    for agg in ("range", "std.p", "twa"):
        print(f"    {agg}:", get_range("temp:room:1", base, now_ms,
                                       aggregation_type=agg, bucket_size_msec=300_000))

    print("(*) FILTER_BY_VALUE — only samples between 24 and 26 degrees.")
    print(get_range("temp:room:1", base, now_ms,
                    filter_by_min_value=24, filter_by_max_value=26, count=5))

    print("(*) FILTER_BY_TS — only these exact timestamps.")
    print(get_range("temp:room:1", base, now_ms,
                    filter_by_ts=[base, base + 10_000, base + 20_000]))

    print("(*) ALIGN — snap bucket boundaries to the start of the window.")
    print(get_range("temp:room:1", base, now_ms, aggregation_type="avg",
                    bucket_size_msec=120_000, align="start"))

    print("(*) EMPTY=True reports buckets with no samples instead of skipping them.")
    print(get_range("temp:room:2", base, now_ms, aggregation_type="avg",
                    bucket_size_msec=60_000, empty=True))

    print("(*) TS.QUERYINDEX — which series carry sensor=temp?")
    print(find_series(["sensor=temp"]))

    print("(*) Compound label filters: temp sensors on floor 2, excluding room 2.")
    print(find_series(["sensor=temp", "floor=2", "room!=2"]))

    print("(*) TS.MGET — the last reading from every temperature sensor.")
    print(latest_many(["sensor=temp"], with_labels=True))

    print("(*) TS.MRANGE — query many series at once by label.")
    print(range_many(base, now_ms, ["sensor=temp"], count=2, with_labels=True))

    print("(*) TS.MRANGE with GROUPBY + REDUCE — average across all temp sensors,")
    print("    grouped by floor.")
    print(range_many(base, now_ms, ["sensor=temp"],
                     aggregation_type="avg", bucket_size_msec=300_000,
                     groupby="floor", reduce="avg"))

    print("(*) TS.MREVRANGE — the same, newest first.")
    print(range_many_reverse(base, now_ms, ["sensor=temp"], count=1, with_labels=True))

    print("(*) TS.CREATERULE — automatic downsampling into a 1-minute AVG series.")
    create("temp:room:1:avg1m", labels={"sensor": "temp", "room": "1", "agg": "avg1m"})
    print(create_rule("temp:room:1", "temp:room:1:avg1m", "avg", 60_000))
    print("    Rules only apply to samples written AFTER the rule exists, so")
    print("    writing a few fresh samples to see it fill:")
    for i in range(1, 8):
        add("temp:room:1", now_ms + i * 20_000, 30 + i)
    print(get_range("temp:room:1:avg1m", "-", "+"))

    print("(*) TS.INFO — chunks, retention, labels, and the rules attached.")
    print(info("temp:room:1"))

    print("(*) TS.DELETERULE.")
    print(delete_rule("temp:room:1", "temp:room:1:avg1m"))

    print("(*) TS.INCRBY / TS.DECRBY — a counter recorded over time.")
    create("requests:count", labels={"kind": "counter"})
    for _ in range(5):
        increment("requests:count", 1, timestamp="*")
        time.sleep(0.01)
    print(latest("requests:count"))
    print(decrement("requests:count", 2, timestamp="*"))
    print(latest("requests:count"))

    print("(*) DUPLICATE_POLICY decides what happens on a repeated timestamp.")
    print("    LAST keeps the newest value:")
    create("temp:dupes", duplicate_policy="last")
    add("temp:dupes", 1000, 10.0)
    add("temp:dupes", 1000, 99.0)
    print(get_range("temp:dupes", "-", "+"))

    print("    BLOCK rejects it outright:")
    delete_keys("temp:dupes")
    create("temp:dupes", duplicate_policy="block")
    add("temp:dupes", 1000, 10.0)
    try:
        add("temp:dupes", 1000, 99.0)
    except redis.exceptions.ResponseError as exc:
        print("    rejected, as expected:", exc)

    print("    on_duplicate can override the policy for a single write:")
    print(add("temp:dupes", 1000, 42.0, on_duplicate="max"))
    print(get_range("temp:dupes", "-", "+"))

    print("(*) TS.ALTER — widen retention and retag the series.")
    print(alter("temp:room:2", retention_msecs=7_200_000,
                labels={"sensor": "temp", "room": "2", "floor": "3"}))
    print(find_series(["floor=3"]))

    print("(*) TS.DEL — drop a closed range of samples.")
    print(delete_range("temp:room:1", base, base + 100_000))
    print("samples left:", len(get_range("temp:room:1", "-", "+")))

    print("(*) Cleaning up.")
    print(delete_keys(*keys))
