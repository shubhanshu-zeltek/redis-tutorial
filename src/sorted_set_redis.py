"""Redis Sorted Sets — https://redis.io/docs/latest/develop/data-types/sorted-sets

A set where every member carries a float score, and Redis keeps the members
ordered by that score. That single property covers leaderboards, priority
queues, rate limiters, time-indexed data, and secondary indexes.

Members are unique; scores are not. Ties are broken lexicographically by member,
which is what makes the ZRANGEBYLEX family work.
"""

import time

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


# --- Writing ---

def add(key, mapping, **kwargs):
    """ZADD. kwargs: nx, xx, gt, lt, ch (count changed), incr (return new score)."""
    global redis_client
    return redis_client.zadd(key, mapping, **kwargs)

def increment_score(key, member, amount):
    global redis_client
    return redis_client.zincrby(key, amount, member)

def remove(key, *members):
    global redis_client
    return redis_client.zrem(key, *members)

def remove_by_rank(key, start, stop):
    global redis_client
    return redis_client.zremrangebyrank(key, start, stop)

def remove_by_score(key, min_score, max_score):
    global redis_client
    return redis_client.zremrangebyscore(key, min_score, max_score)

def remove_by_lex(key, min_lex, max_lex):
    global redis_client
    return redis_client.zremrangebylex(key, min_lex, max_lex)


# --- Reading ---

def score(key, member):
    global redis_client
    return redis_client.zscore(key, member)

def scores(key, *members):
    """ZMSCORE — many scores in one round trip (Redis 6.2+)."""
    global redis_client
    return redis_client.zmscore(key, list(members))

def count(key):
    global redis_client
    return redis_client.zcard(key)

def count_in_score_range(key, min_score, max_score):
    global redis_client
    return redis_client.zcount(key, min_score, max_score)

def count_in_lex_range(key, min_lex, max_lex):
    global redis_client
    return redis_client.zlexcount(key, min_lex, max_lex)

def rank(key, member, with_score=False):
    """ZRANK — 0-based position, lowest score first."""
    global redis_client
    return redis_client.zrank(key, member, withscore=with_score)

def reverse_rank(key, member, with_score=False):
    global redis_client
    return redis_client.zrevrank(key, member, withscore=with_score)

def range_by_rank(key, start=0, end=-1, **kwargs):
    """ZRANGE. kwargs: desc, withscores, byscore, bylex, offset, num."""
    global redis_client
    return redis_client.zrange(key, start, end, **kwargs)

def range_by_score(key, min_score, max_score, **kwargs):
    global redis_client
    return redis_client.zrangebyscore(key, min_score, max_score, **kwargs)

def reverse_range_by_score(key, max_score, min_score, **kwargs):
    global redis_client
    return redis_client.zrevrangebyscore(key, max_score, min_score, **kwargs)

def range_by_lex(key, min_lex, max_lex, **kwargs):
    """ZRANGEBYLEX — only meaningful when every member shares the same score."""
    global redis_client
    return redis_client.zrangebylex(key, min_lex, max_lex, **kwargs)

def range_store(destination, key, start, end, **kwargs):
    """ZRANGESTORE — persist a range into another sorted set (Redis 6.2+)."""
    global redis_client
    return redis_client.zrangestore(destination, key, start, end, **kwargs)

def random_member(key, count=None, with_scores=False):
    global redis_client
    return redis_client.zrandmember(key, count, withscores=with_scores)

def scan(key, match=None, count=None):
    global redis_client
    cursor = 0
    found = []
    while True:
        cursor, data = redis_client.zscan(key, cursor=cursor, match=match, count=count)
        found.extend(data)
        if cursor == 0:
            return found


# --- Popping (priority queue behaviour) ---

def pop_lowest(key, count=None):
    global redis_client
    return redis_client.zpopmin(key, count)

def pop_highest(key, count=None):
    global redis_client
    return redis_client.zpopmax(key, count)

def blocking_pop_lowest(keys, timeout=0):
    global redis_client
    return redis_client.bzpopmin(keys, timeout)

def blocking_pop_highest(keys, timeout=0):
    global redis_client
    return redis_client.bzpopmax(keys, timeout)

def pop_many(*keys, min=False, max=False, count=1):
    """ZMPOP — pop from the first non-empty sorted set (Redis 7.0+)."""
    global redis_client
    return redis_client.zmpop(len(keys), list(keys), min=min, max=max, count=count)


# --- Set algebra, score-aware ---

def difference(keys, with_scores=False):
    global redis_client
    return redis_client.zdiff(keys, withscores=with_scores)

def intersection(keys, aggregate=None, with_scores=False):
    """keys may be a dict {key: weight} to weight each input set."""
    global redis_client
    return redis_client.zinter(keys, aggregate=aggregate, withscores=with_scores)

def union(keys, aggregate=None, with_scores=False):
    global redis_client
    return redis_client.zunion(keys, aggregate=aggregate, withscores=with_scores)

def difference_store(destination, keys):
    global redis_client
    return redis_client.zdiffstore(destination, keys)

def intersection_store(destination, keys, aggregate=None):
    global redis_client
    return redis_client.zinterstore(destination, keys, aggregate=aggregate)

def union_store(destination, keys, aggregate=None):
    global redis_client
    return redis_client.zunionstore(destination, keys, aggregate=aggregate)

def intersection_count(keys, limit=0):
    global redis_client
    return redis_client.zintercard(len(keys), list(keys), limit=limit)


def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    board = "leaderboard:season1"
    delete_keys(board, "leaderboard:season2", "leaderboard:combined", "leaderboard:top3",
                "leaderboard:both", "leaderboard:new", "autocomplete", "jobs", "jobs:2",
                "requests:user:1")

    print("(*) ZADD — seed a leaderboard.")
    print(add(board, {"riya": 1500, "arjun": 2300, "meera": 1800, "kabir": 2300, "dev": 900}))

    print("(*) ZCARD and ZSCORE.")
    print(count(board), score(board, "arjun"))

    print("(*) ZMSCORE — several scores at once; missing members come back as None.")
    print(scores(board, "riya", "arjun", "ghost"))

    print("(*) ZRANGE 0 -1 — ascending by score. Ties (arjun/kabir at 2300) break")
    print("    lexicographically, so 'arjun' sorts before 'kabir'.")
    print(range_by_rank(board))

    print("(*) ZRANGE with scores.")
    print(range_by_rank(board, withscores=True))

    print("(*) ZRANGE desc — the actual leaderboard order.")
    print(range_by_rank(board, 0, -1, desc=True, withscores=True))

    print("(*) Top 3 only.")
    print(range_by_rank(board, 0, 2, desc=True, withscores=True))

    print("(*) ZRANK / ZREVRANK — 0-based position from the bottom / from the top.")
    print(rank(board, "meera"), reverse_rank(board, "meera"))

    print("(*) ZREVRANK with the score attached (Redis 7.2+).")
    print(reverse_rank(board, "meera", with_score=True))

    print("(*) ZINCRBY — meera scores 400 more points.")
    print(increment_score(board, "meera", 400))
    print(range_by_rank(board, 0, -1, desc=True, withscores=True))

    print("(*) ZADD GT — only raise a score, never lower it. 100 < 2200, so ignored.")
    print(add(board, {"meera": 100}, gt=True, ch=True))
    print(score(board, "meera"))

    print("(*) ZADD LT — only lower a score. Now it applies.")
    print(add(board, {"meera": 100}, lt=True, ch=True))
    print(score(board, "meera"))

    print("(*) ZADD NX — never touch an existing member.")
    print(add(board, {"meera": 5000, "newbie": 50}, nx=True, ch=True))
    print(scores(board, "meera", "newbie"))

    print("(*) ZADD XX — only update members that already exist.")
    print(add(board, {"newbie": 75, "stranger": 999}, xx=True, ch=True))
    print(scores(board, "newbie", "stranger"))

    print("(*) ZADD INCR — behaves like ZINCRBY, returns the new score.")
    print(add(board, {"dev": 250}, incr=True))

    print("(*) ZCOUNT — how many players scored between 1000 and 2000?")
    print(count_in_score_range(board, 1000, 2000))

    print("(*) ZCOUNT with exclusive bounds and infinities.")
    print(count_in_score_range(board, "(1500", "+inf"))

    print("(*) ZRANGEBYSCORE — everyone in the 1000..2500 band.")
    print(range_by_score(board, 1000, 2500, withscores=True))

    print("(*) ZRANGEBYSCORE with LIMIT (offset/num) for pagination.")
    print(range_by_score(board, "-inf", "+inf", start=0, num=2, withscores=True))

    print("(*) ZREVRANGEBYSCORE — same band, highest first.")
    print(reverse_range_by_score(board, 2500, 1000, withscores=True))

    print("(*) ZRANGE ... BYSCORE is the modern unified form of the above.")
    print(range_by_rank(board, 1000, 2500, byscore=True, withscores=True))

    print("(*) ZRANGESTORE — persist the top 3 into its own key.")
    print(range_store("leaderboard:top3", board, 0, 2, desc=True))
    print(range_by_rank("leaderboard:top3", 0, -1, desc=True, withscores=True))

    print("(*) ZRANDMEMBER — random picks, with and without scores.")
    print(random_member(board))
    print(random_member(board, count=3, with_scores=True))
    print("negative count allows repeats:", random_member(board, count=-5))

    print("(*) ZSCAN — cursor iteration for large sorted sets.")
    print(scan(board))

    print("(*) Set algebra across two seasons.")
    add("leaderboard:season2", {"riya": 700, "arjun": 1200, "zoya": 3000})

    print("    ZUNION (default aggregate SUM) — careers totals.")
    print(union([board, "leaderboard:season2"], with_scores=True))

    print("    ZINTER — only players who appeared in both seasons.")
    print(intersection([board, "leaderboard:season2"], with_scores=True))

    print("    ZINTER with aggregate MAX instead of SUM.")
    print(intersection([board, "leaderboard:season2"], aggregate="MAX", with_scores=True))

    print("    Weighted union — season 2 counts double.")
    print(union({board: 1, "leaderboard:season2": 2}, with_scores=True))

    print("    ZDIFF — players only in season 1.")
    print(difference([board, "leaderboard:season2"], with_scores=True))

    print("    ZINTERCARD — how many players overlap (Redis 7.0+).")
    print(intersection_count([board, "leaderboard:season2"]))

    print("    The *STORE variants write the result to a key.")
    print(union_store("leaderboard:combined", [board, "leaderboard:season2"]))
    print(range_by_rank("leaderboard:combined", 0, -1, desc=True, withscores=True))
    print(intersection_store("leaderboard:both", [board, "leaderboard:season2"], aggregate="MIN"))
    print(range_by_rank("leaderboard:both", 0, -1, withscores=True))
    print(difference_store("leaderboard:new", ["leaderboard:season2", board]))
    print(range_by_rank("leaderboard:new", 0, -1, withscores=True))

    print("(*) A sorted set as a PRIORITY QUEUE: lower score = higher priority.")
    add("jobs", {"send-invoice": 1, "resize-image": 5, "page-oncall": 0, "gc-temp": 9})
    print("next up:", pop_lowest("jobs"))
    print("two lowest:", pop_lowest("jobs", 2))
    print("lowest-priority job:", pop_highest("jobs"))

    print("(*) BZPOPMIN — blocking pop with a 1s timeout on an empty key.")
    print(blocking_pop_lowest(["jobs"], timeout=1))

    print("(*) ZMPOP — pop from the first non-empty key among several (Redis 7.0+).")
    add("jobs:2", {"a": 1, "b": 2, "c": 3})
    print(pop_many("jobs", "jobs:2", min=True, count=2))

    print("(*) A sorted set as a SLIDING-WINDOW RATE LIMITER.")
    print("    Score = timestamp; drop everything older than the window, then count.")
    now = time.time()
    window = 60
    for offset in (120, 90, 30, 10, 1):   # seconds ago
        add("requests:user:1", {f"req-{offset}": now - offset})
    removed = remove_by_score("requests:user:1", "-inf", f"({now - window}")
    print("    evicted stale requests:", removed)
    print("    requests in the last 60s:", count("requests:user:1"))

    print("(*) A sorted set as an AUTOCOMPLETE index: identical scores, lexical range.")
    add("autocomplete", {w: 0 for w in
        ["red", "redis", "redis-cli", "redistribute", "reduce", "reef", "ruby"]})
    print("    ZRANGEBYLEX for the prefix 're':")
    print(range_by_lex("autocomplete", "[re", "[re\xff"))
    print("    ZRANGEBYLEX for the prefix 'redis':")
    print(range_by_lex("autocomplete", "[redis", "[redis\xff"))
    print("    ZLEXCOUNT for that same prefix:")
    print(count_in_lex_range("autocomplete", "[redis", "[redis\xff"))
    print("    ZRANGE ... BYLEX, the modern unified form:")
    print(range_by_rank("autocomplete", "[re", "[re\xff", bylex=True))

    print("(*) ZREM / ZREMRANGEBYRANK / ZREMRANGEBYLEX.")
    print(remove(board, "dev"))
    print(remove_by_rank(board, 0, 0))
    print(range_by_rank(board, 0, -1, withscores=True))
    print(remove_by_lex("autocomplete", "[ruby", "[ruby"))
    print(range_by_rank("autocomplete", 0, -1))

    print("(*) Cleaning up.")
    print(delete_keys(board, "leaderboard:season2", "leaderboard:combined", "leaderboard:top3",
                      "leaderboard:both", "leaderboard:new", "autocomplete", "jobs", "jobs:2",
                      "requests:user:1"))
