"""Redis t-digest — https://redis.io/docs/latest/develop/data-types/probabilistic/t-digest

Estimates PERCENTILES over a stream of numbers without keeping the numbers.

This is the structure behind "what's our p99 latency?". A t-digest is far more
accurate at the extremes (p1, p99, p999) than in the middle, which is exactly
the right trade-off for latency and SLA monitoring.

`compression` sets the accuracy/memory dial — higher means more centroids,
tighter estimates, more memory. The default of 100 is usually fine.

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


def create(key, compression=100):
    global redis_client
    return redis_client.tdigest().create(key, compression)

def add_values(key, values):
    """TDIGEST.ADD — values is a list of floats."""
    global redis_client
    return redis_client.tdigest().add(key, values)

def quantile(key, *quantiles):
    """TDIGEST.QUANTILE — value at each fraction (0.5 = median, 0.99 = p99)."""
    global redis_client
    return redis_client.tdigest().quantile(key, *quantiles)

def cdf(key, *values):
    """TDIGEST.CDF — the inverse: what fraction of observations are <= value."""
    global redis_client
    return redis_client.tdigest().cdf(key, *values)

def rank(key, *values):
    """TDIGEST.RANK — how many observations are <= value (-1 if below the min)."""
    global redis_client
    return redis_client.tdigest().rank(key, *values)

def reverse_rank(key, *values):
    global redis_client
    return redis_client.tdigest().revrank(key, *values)

def by_rank(key, *ranks):
    """TDIGEST.BYRANK — the value sitting at each rank."""
    global redis_client
    return redis_client.tdigest().byrank(key, *ranks)

def by_reverse_rank(key, *ranks):
    global redis_client
    return redis_client.tdigest().byrevrank(key, *ranks)

def minimum(key):
    global redis_client
    return redis_client.tdigest().min(key)

def maximum(key):
    global redis_client
    return redis_client.tdigest().max(key)

def trimmed_mean(key, low_quantile, high_quantile):
    """TDIGEST.TRIMMED_MEAN — mean with the tails discarded, so a few wild
    outliers can't drag the average around."""
    global redis_client
    return redis_client.tdigest().trimmed_mean(key, low_quantile, high_quantile)

def merge(destination, sources, compression=None, override=False):
    global redis_client
    return redis_client.tdigest().merge(destination, len(sources), *sources,
                                        compression=compression, override=override)

def reset(key):
    global redis_client
    return redis_client.tdigest().reset(key)

def info(key):
    """TDIGEST.INFO. redis-py wraps the reply in a TDigestInfo object; vars() makes it printable."""
    global redis_client
    raw = redis_client.tdigest().info(key)
    return vars(raw) if hasattr(raw, "__dict__") else raw

def memory_bytes(key):
    global redis_client
    return redis_client.memory_usage(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "latency:api"
    delete_keys(key, "latency:web", "latency:worker", "latency:all",
                "latency:precise", "latency:exact")

    try:
        print("(*) TDIGEST.CREATE with the default compression of 100.")
        print(create(key))
    except redis.exceptions.ModuleError:
        raise SystemExit(
            "This script needs the Bloom module. Start Redis Stack instead of plain Redis:\n"
            "    docker compose -f docker-compose-stack.yaml.yaml up -d"
        )

    print("(*) TDIGEST.ADD — a handful of response times in milliseconds.")
    print(add_values(key, [12.0, 15.5, 9.8, 22.1, 18.0, 45.2, 11.3, 13.7, 250.0, 14.2]))

    print("(*) TDIGEST.MIN / MAX.")
    print(minimum(key), maximum(key))

    print("(*) TDIGEST.QUANTILE — median, p90, p99.")
    print(quantile(key, 0.5, 0.9, 0.99))

    print("(*) TDIGEST.CDF — what fraction of requests came in under 15ms / 50ms?")
    print(cdf(key, 15.0, 50.0))

    print("(*) TDIGEST.RANK — how many observations are <= these values.")
    print(rank(key, 9.8, 15.0, 1000.0))

    print("(*) A value below the minimum ranks -1; above the max ranks as the total.")
    print(rank(key, 0.1))

    print("(*) TDIGEST.REVRANK — counted from the top instead.")
    print(reverse_rank(key, 250.0, 15.0))

    print("(*) TDIGEST.BYRANK — the value at rank 0 (smallest) and rank 9 (largest).")
    print(by_rank(key, 0, 5, 9))

    print("(*) TDIGEST.BYREVRANK — same, from the other end.")
    print(by_reverse_rank(key, 0, 1))

    print("(*) TDIGEST.TRIMMED_MEAN — the plain mean is dragged up by that 250ms")
    print("    outlier; trimming the top and bottom 10% shows the typical case.")
    values = [12.0, 15.5, 9.8, 22.1, 18.0, 45.2, 11.3, 13.7, 250.0, 14.2]
    print(f"    plain mean:            {sum(values) / len(values):.2f}")
    print(f"    trimmed mean (10-90%): {trimmed_mean(key, 0.1, 0.9):.2f}")

    print("(*) TDIGEST.INFO — compression, observations, memory usage.")
    print(info(key))

    print("(*) TDIGEST.MERGE — roll per-service digests into a fleet-wide one.")
    create("latency:web")
    create("latency:worker")
    add_values("latency:web", [5.0, 6.0, 7.0, 8.0, 9.0])
    add_values("latency:worker", [100.0, 120.0, 140.0, 160.0])
    create("latency:all")
    print(merge("latency:all", ["latency:web", "latency:worker"]))
    print("merged median:", quantile("latency:all", 0.5))
    print("merged p99:   ", quantile("latency:all", 0.99))

    print("(*) MERGE with override=True resets the destination first.")
    print(merge("latency:all", ["latency:web"], override=True))
    print("now only web:", minimum("latency:all"), maximum("latency:all"))

    print("(*) Accuracy: 100,000 log-normal latencies vs exact percentiles.")
    create("latency:precise", 500)
    random.seed(11)
    sample = [random.lognormvariate(3.0, 0.6) for _ in range(100_000)]
    for start in range(0, len(sample), 5_000):
        add_values("latency:precise", sample[start:start + 5_000])

    ordered = sorted(sample)
    print("    quantile |    exact |  t-digest |   error")
    for q in (0.5, 0.9, 0.95, 0.99, 0.999):
        exact_v = ordered[min(int(q * len(ordered)), len(ordered) - 1)]
        est_v = quantile("latency:precise", q)[0]
        err = abs(est_v - exact_v) / exact_v * 100
        print(f"    p{q * 100:<7.1f} | {exact_v:8.3f} | {est_v:9.3f} | {err:6.3f}%")

    print("(*) Memory: the digest is bounded by its compression, not by the")
    print("    100,000 observations that went through it.")
    print(f"    t-digest: {memory_bytes('latency:precise')} bytes")
    print(f"    (storing all 100,000 floats exactly would need ~{100_000 * 8 // 1024} KB)")

    print("(*) TDIGEST.RESET — empty the digest but keep the key and its settings.")
    print(reset(key))
    print(info(key))

    print("(*) Cleaning up.")
    print(delete_keys(key, "latency:web", "latency:worker", "latency:all", "latency:precise"))
