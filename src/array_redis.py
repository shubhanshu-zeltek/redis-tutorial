"""Redis Arrays — https://redis.io/docs/latest/develop/data-types/arrays

Sparse, index-addressable sequences of strings. Indexes run 0 .. 2^64-1 and you
can write index 1,000,000 without allocating the million slots before it.

How it differs from a list:
  * List  — addressed by POSITION, cheap push/pop at the ends, no gaps.
  * Array — addressed by INDEX, direct O(1) random access, gaps are free.

That makes arrays the right fit for timestamped event logs, ring buffers over
streaming measurements, and sliding-window analytics.

Requires Redis 8.8+. Neither docker-compose.yaml (redis:7-alpine) nor the
current redis/redis-stack image has the AR* command group, so run Redis 8:

    docker run -d --rm --name redis8 -p 6380:6379 redis:8-alpine
    python src/array_redis.py 6380

redis-py 8.1 (what this project pins) has no arset()/arget() helpers yet, so
every wrapper below goes through execute_command — which doubles as a
demonstration of how to reach any Redis command your client predates.

One syntax note worth knowing: only ARGREP accepts the special '-' and '+'
bounds meaning "first"/"last" index. ARGETRANGE, ARSCAN, AROP and ARDELRANGE
all want real integers.
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def _run(*args):
    global redis_client
    return redis_client.execute_command(*args)


# --- Writing ---

def set_values(key, index, *values):
    """ARSET key index value [value ...] — write CONTIGUOUS values from index."""
    return _run("ARSET", key, index, *values)

def set_sparse(key, mapping):
    """ARMSET key index value [index value ...] — arbitrary, non-contiguous slots."""
    pieces = []
    for index, value in mapping.items():
        pieces.extend([index, value])
    return _run("ARMSET", key, *pieces)


# --- Reading ---

def get_value(key, index):
    """ARGET — value at index, or None if that slot was never set."""
    return _run("ARGET", key, index)

def get_values(key, *indexes):
    """ARMGET — several indexes in one round trip."""
    return _run("ARMGET", key, *indexes)

def get_range(key, start, end):
    """ARGETRANGE — values across an index range, gaps included as None.
    Hard-capped at 1,000,000 elements per call."""
    return _run("ARGETRANGE", key, start, end)

def scan_range(key, start, end, limit=None):
    """ARSCAN — (index, value) pairs, skipping empty slots. The right tool for
    a sparse array, where ARGETRANGE would return mostly None."""
    if limit is None:
        return _run("ARSCAN", key, start, end)
    return _run("ARSCAN", key, start, end, "LIMIT", limit)

def logical_length(key):
    """ARLEN — highest set index + 1."""
    return _run("ARLEN", key)

def element_count(key):
    """ARCOUNT — how many slots are actually occupied."""
    return _run("ARCOUNT", key)

def last_items(key, count, reverse=False):
    """ARLASTITEMS — the most recently inserted elements. REV flips the order."""
    if reverse:
        return _run("ARLASTITEMS", key, count, "REV")
    return _run("ARLASTITEMS", key, count)


# --- Sequential insertion (the append cursor) ---

def insert(key, *values):
    """ARINSERT — append at the cursor, advancing it. No index needed."""
    return _run("ARINSERT", key, *values)

def next_index(key):
    """ARNEXT — the index ARINSERT would write to next."""
    return _run("ARNEXT", key)

def seek(key, index):
    """ARSEEK — move the ARINSERT / ARRING cursor."""
    return _run("ARSEEK", key, index)

def ring_push(key, size, *values):
    """ARRING — insert into a fixed-size ring buffer, wrapping and truncating."""
    return _run("ARRING", key, size, *values)


# --- Aggregation and search ---

def aggregate(key, start, end, operation, value=None):
    """AROP key start end SUM|MIN|MAX|AND|OR|XOR|USED|MATCH <value>

    SUM/MIN/MAX are numeric; AND/OR/XOR are bitwise; USED counts occupied
    slots in the range; MATCH counts elements equal to <value>."""
    if operation.upper() == "MATCH":
        return _run("AROP", key, start, end, "MATCH", value)
    return _run("AROP", key, start, end, operation)

def grep(key, start, end, predicates, combinator=None,
         nocase=False, withvalues=False, limit=None):
    """ARGREP key start end <predicate ...> [AND|OR] [LIMIT n] [WITHVALUES] [NOCASE]

    predicates is [(kind, pattern), ...] where kind is EXACT, MATCH (substring),
    GLOB or RE (regex). start/end may be '-' and '+' here, unlike the other
    range commands.
    """
    pieces = []
    for kind, pattern in predicates:
        pieces.extend([kind, pattern])
    if combinator:
        pieces.append(combinator)
    if limit is not None:
        pieces.extend(["LIMIT", limit])
    if withvalues:
        pieces.append("WITHVALUES")
    if nocase:
        pieces.append("NOCASE")
    return _run("ARGREP", key, start, end, *pieces)


# --- Deleting and introspection ---

def delete_indexes(key, *indexes):
    """ARDEL — delete specific indexes."""
    return _run("ARDEL", key, *indexes)

def delete_range(key, *ranges):
    """ARDELRANGE key start end [start end ...] — delete one or more ranges."""
    pieces = []
    for start, end in ranges:
        pieces.extend([start, end])
    return _run("ARDELRANGE", key, *pieces)

def info(key, full=False):
    """ARINFO — logical length, element count, next insert index, slice stats."""
    if full:
        return _run("ARINFO", key, "FULL")
    return _run("ARINFO", key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    import sys

    # Arrays need Redis 8.8+; pass a port on the command line if your Redis 8
    # server isn't on the default one, e.g.  python src/array_redis.py 6380
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6379
    init_client(port=port)

    try:
        _run("ARSET", "array:probe", 0, "x")
        delete_keys("array:probe")
    except redis.exceptions.ResponseError:
        version = redis_client.info("server").get("redis_version", "unknown")
        raise SystemExit(
            f"Redis arrays need Redis 8.8+, and the server on port {port} reports {version}.\n"
            "Start a Redis 8 server and point this script at it:\n"
            "    docker run -d --rm --name redis8 -p 6380:6379 redis:8-alpine\n"
            "    python src/array_redis.py 6380"
        )

    keys = ["events:1", "metrics", "sparse", "seq", "log", "readings", "scores",
            "syslog", "flags"]
    delete_keys(*keys)

    print("(*) ARSET — three contiguous values starting at index 0.")
    print(set_values("events:1", 0, "login", "click", "purchase"))

    print("(*) ARGET — read one index. An unset index is None, not an error.")
    print(get_value("events:1", 0))
    print(get_value("events:1", 999))

    print("(*) ARMSET — write scattered indexes: 0, 5 and 100.")
    print(set_sparse("metrics", {0: "10", 5: "20", 100: "30"}))

    print("(*) ARMGET — several indexes at once; gaps come back as None.")
    print(get_values("metrics", 0, 5, 100, 999))

    print("(*) The sparse property: set index 0 and index 1,000,000, and nothing")
    print("    in between gets allocated.")
    print(set_values("sparse", 0, "a"))
    print(set_values("sparse", 1_000_000, "b"))
    print("ARLEN   (highest index + 1):", logical_length("sparse"))
    print("ARCOUNT (occupied slots):   ", element_count("sparse"))
    print("memory:", redis_client.memory_usage("sparse"),
          "bytes for an array a million long")

    print("(*) ARGETRANGE — a contiguous window; missing slots read as None.")
    print(set_sparse("seq", {0: "a", 1: "b", 3: "d"}))
    print(get_range("seq", 0, 3))

    print("(*) ARSCAN — the same range as (index, value) pairs, gaps skipped.")
    print("    This is what you want on a sparse array.")
    print(scan_range("seq", 0, 3))

    print("(*) ARSCAN with LIMIT caps how many pairs come back.")
    print(scan_range("seq", 0, 3, limit=2))

    print("(*) ARINSERT — append at the cursor, no index bookkeeping needed.")
    print(insert("log", "event1"))
    print(insert("log", "event2"))

    print("(*) ARNEXT — where the next ARINSERT will land.")
    print(next_index("log"))

    print("(*) ARSEEK — jump the cursor to index 10, then insert there.")
    print(seek("log", 10))
    print(insert("log", "event3"))
    print(scan_range("log", 0, logical_length("log") - 1))
    print("next insert index is now:", next_index("log"))

    print("(*) ARRING — a fixed-size ring buffer. Size 3, four values pushed:")
    print("    the fourth wraps around and overwrites the first.")
    for i in range(4):
        print(f"    push v{i}:", ring_push("readings", 3, f"v{i}"))
    print("index 0 now holds:", get_value("readings", 0))
    print("whole ring:", scan_range("readings", 0, 2))

    print("(*) ARLASTITEMS — the most recently inserted elements, oldest first...")
    print(last_items("readings", 3))
    print("    ...and with REV, newest first.")
    print(last_items("readings", 3, reverse=True))

    print("(*) AROP — aggregate over an index range server-side, without")
    print("    shipping any of the values back.")
    print(set_sparse("scores", {0: "10", 1: "20", 2: "30"}))
    print("SUM: ", aggregate("scores", 0, 2, "SUM"))
    print("MIN: ", aggregate("scores", 0, 2, "MIN"))
    print("MAX: ", aggregate("scores", 0, 2, "MAX"))
    print("USED:", aggregate("scores", 0, 2, "USED"), "(occupied slots in range)")

    print("(*) AROP MATCH counts elements equal to a given value.")
    print(aggregate("scores", 0, 2, "MATCH", "10"))

    print("(*) AROP also does BITWISE folds across the range.")
    print(set_sparse("flags", {0: "12", 1: "10", 2: "6"}))
    print("AND:", aggregate("flags", 0, 2, "AND"))
    print("OR: ", aggregate("flags", 0, 2, "OR"))
    print("XOR:", aggregate("flags", 0, 2, "XOR"))

    print("(*) ARGREP — search a range with text predicates.")
    print(set_sparse("syslog", {
        0: "boot: ok",
        1: "warn: disk",
        2: "ERROR: cpu",
        3: "info: ready",
        4: "error: net",
    }))
    print("    MATCH (substring), case-insensitive:")
    print(grep("syslog", 0, 4, [("MATCH", "error")], nocase=True))

    print("    ARGREP is the one range command that accepts '-' and '+':")
    print(grep("syslog", "-", "+", [("MATCH", "error")], nocase=True))

    print("    Two GLOB predicates OR'd together, returning the values too:")
    print(grep("syslog", 0, 4,
               [("GLOB", "warn:*"), ("GLOB", "error:*")],
               combinator="OR", withvalues=True))

    print("    RE runs a real regex:")
    print(grep("syslog", 0, 4, [("RE", "^err")], nocase=True, withvalues=True))

    print("    EXACT matches the whole value:")
    print(grep("syslog", 0, 4, [("EXACT", "error: net")]))

    print("    LIMIT caps the number of hits:")
    print(grep("syslog", 0, 4, [("MATCH", "o")], limit=2))

    print("(*) Combine ring-buffer mode with ARGREP and you have a fixed-size,")
    print("    searchable tail of the last N log lines.")

    print("(*) ARINFO — logical length, element count, next insert index.")
    print(info("readings"))

    print("(*) ARINFO FULL adds per-slice fill rates and dense/sparse counts.")
    print(info("sparse", full=True))

    print("(*) ARDEL — delete one index.")
    print(delete_indexes("scores", 1))
    print(scan_range("scores", 0, 2))

    print("(*) ARDELRANGE takes MULTIPLE ranges in one call.")
    set_sparse("scores", {0: "10", 1: "20", 2: "30", 3: "40", 4: "50"})
    print(delete_range("scores", (0, 1), (3, 4)))
    print(scan_range("scores", 0, 4))

    print("(*) Deleting the last remaining element removes the key entirely.")
    print(delete_range("scores", (0, 4)))
    print("key still exists?", redis_client.exists("scores"))

    print("(*) Cleaning up.")
    print(delete_keys(*keys))
