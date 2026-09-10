"""Redis Streams — https://redis.io/docs/latest/develop/data-types/streams

An append-only log of entries, each with an auto-generated
`<milliseconds>-<sequence>` id and a flat field/value map.

Two ways to read:
  * XREAD          — every consumer sees every entry (fan-out / pub-sub-ish).
  * XREADGROUP     — a consumer group splits entries across consumers, tracks a
                     Pending Entries List (PEL), and needs an XACK per entry.
                     Unacked work can be reclaimed with XCLAIM / XAUTOCLAIM.
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


# --- Writing ---

def append(key, fields, entry_id="*", **kwargs):
    """XADD. kwargs: maxlen, minid, approximate, nomkstream, limit."""
    global redis_client
    return redis_client.xadd(key, fields, id=entry_id, **kwargs)

def trim(key, **kwargs):
    """XTRIM. kwargs: maxlen or minid, approximate, limit."""
    global redis_client
    return redis_client.xtrim(key, **kwargs)

def delete_entries(key, *entry_ids):
    global redis_client
    return redis_client.xdel(key, *entry_ids)

def set_last_id(key, entry_id):
    global redis_client
    return redis_client.xsetid(key, entry_id)


# --- Reading without groups ---

def length(key):
    global redis_client
    return redis_client.xlen(key)

def read_range(key, start="-", finish="+", count=None):
    global redis_client
    return redis_client.xrange(key, min=start, max=finish, count=count)

def read_range_reverse(key, finish="+", start="-", count=None):
    global redis_client
    return redis_client.xrevrange(key, max=finish, min=start, count=count)

def read(streams, count=None, block=None):
    """XREAD — streams is {key: last_id}. '$' means 'only new entries'."""
    global redis_client
    return redis_client.xread(streams, count=count, block=block)


# --- Consumer groups ---

def create_group(key, group, entry_id="0", mkstream=False):
    global redis_client
    return redis_client.xgroup_create(key, group, id=entry_id, mkstream=mkstream)

def destroy_group(key, group):
    global redis_client
    return redis_client.xgroup_destroy(key, group)

def set_group_id(key, group, entry_id):
    global redis_client
    return redis_client.xgroup_setid(key, group, entry_id)

def create_consumer(key, group, consumer):
    global redis_client
    return redis_client.xgroup_createconsumer(key, group, consumer)

def delete_consumer(key, group, consumer):
    global redis_client
    return redis_client.xgroup_delconsumer(key, group, consumer)

def read_group(group, consumer, streams, count=None, block=None, noack=False):
    """XREADGROUP — '>' delivers never-before-delivered entries;
    an explicit id replays that consumer's own pending entries."""
    global redis_client
    return redis_client.xreadgroup(group, consumer, streams,
                                   count=count, block=block, noack=noack)

def acknowledge(key, group, *entry_ids):
    global redis_client
    return redis_client.xack(key, group, *entry_ids)

def pending_summary(key, group):
    global redis_client
    return redis_client.xpending(key, group)

def pending_detail(key, group, start="-", finish="+", count=10, consumer=None, idle=None):
    global redis_client
    return redis_client.xpending_range(key, group, min=start, max=finish,
                                       count=count, consumername=consumer, idle=idle)

def claim(key, group, consumer, min_idle_time, entry_ids, **kwargs):
    """XCLAIM — forcibly reassign specific pending entries to another consumer."""
    global redis_client
    return redis_client.xclaim(key, group, consumer, min_idle_time, entry_ids, **kwargs)

def auto_claim(key, group, consumer, min_idle_time, start_id="0-0", count=None, justid=False):
    """XAUTOCLAIM — scan for stale pending entries and claim them (Redis 6.2+)."""
    global redis_client
    return redis_client.xautoclaim(key, group, consumer, min_idle_time,
                                   start_id=start_id, count=count, justid=justid)


# --- Introspection ---

def stream_info(key, full=False):
    global redis_client
    return redis_client.xinfo_stream(key, full=full)

def group_info(key):
    global redis_client
    return redis_client.xinfo_groups(key)

def consumer_info(key, group):
    global redis_client
    return redis_client.xinfo_consumers(key, group)


def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "orders:stream"
    group = "billing"
    delete_keys(key, "sensors:stream")

    print("(*) XADD with id='*' — Redis assigns <ms>-<seq> ids for you.")
    ids = []
    for i in range(1, 6):
        entry_id = append(key, {"order_id": f"ORD-{i:03d}", "amount": i * 100, "status": "new"})
        ids.append(entry_id)
        print(entry_id)

    print("(*) XLEN.")
    print(length(key))

    print("(*) XRANGE - + — the whole stream, oldest first.")
    for entry in read_range(key):
        print(entry)

    print("(*) XRANGE with COUNT — just the first two.")
    print(read_range(key, count=2))

    print("(*) XREVRANGE — newest first, the usual 'latest N events' query.")
    print(read_range_reverse(key, count=2))

    print("(*) XRANGE between two explicit ids (both inclusive).")
    print(read_range(key, ids[1], ids[3]))

    print("(*) Exclusive ranges with '(' (Redis 6.2+) — skips the boundary entry.")
    print(read_range(key, f"({ids[1]}", ids[3]))

    print("(*) XREAD from the very beginning — no group, everyone sees everything.")
    print(read({key: "0"}, count=3))

    print("(*) XREAD from a specific id returns only what came after it.")
    print(read({key: ids[2]}))

    print("(*) XREAD with '$' and a 200ms block — nothing new arrives, so None.")
    print(read({key: "$"}, block=200))

    print("(*) XADD with an explicit id, then XSETID to control the id sequence.")
    print(append("sensors:stream", {"temp": "21.5"}, entry_id="1000-1"))
    print(append("sensors:stream", {"temp": "21.9"}, entry_id="1000-2"))
    print(read_range("sensors:stream"))

    print("(*) XADD with NOMKSTREAM on a missing key returns None instead of creating it.")
    print(append("stream:does-not-exist", {"a": "b"}, nomkstream=True))

    print("(*) XADD with MAXLEN — a capped stream that trims itself as it grows.")
    for i in range(10):
        append("sensors:stream", {"temp": 20 + i}, maxlen=5, approximate=False)
    print("length after capped writes:", length("sensors:stream"))

    print("(*) ---------- Consumer groups ----------")
    print("(*) XGROUP CREATE at id '0' — the group replays the whole stream.")
    print(create_group(key, group, entry_id="0"))

    print("(*) Consumer 'worker-1' claims 2 entries with '>'.")
    batch1 = read_group(group, "worker-1", {key: ">"}, count=2)
    print(batch1)

    print("(*) Consumer 'worker-2' gets the NEXT 2 — the group splits the work.")
    batch2 = read_group(group, "worker-2", {key: ">"}, count=2)
    print(batch2)

    print("(*) XPENDING summary — 4 entries delivered, none acknowledged yet.")
    print(pending_summary(key, group))

    print("(*) XPENDING range — who holds what, and for how long.")
    for row in pending_detail(key, group):
        print(row)

    print("(*) worker-1 finishes its work and XACKs both entries.")
    worker1_ids = [entry_id for entry_id, _ in batch1[0][1]]
    print(acknowledge(key, group, *worker1_ids))
    print(pending_summary(key, group))

    print("(*) Re-reading with an explicit id ('0') replays a consumer's OWN pending")
    print("    entries — this is how a restarted worker recovers its unfinished work.")
    print(read_group(group, "worker-2", {key: "0"}))

    print("(*) worker-2 has died. XAUTOCLAIM hands its stale entries to worker-3.")
    print("    min_idle_time=0 so the demo doesn't have to wait.")
    next_start, claimed, deleted = auto_claim(key, group, "worker-3", min_idle_time=0)
    print("cursor:", next_start, "claimed:", claimed, "dropped ids:", deleted)

    print("(*) XCLAIM — the targeted version, for specific ids.")
    worker2_ids = [entry_id for entry_id, _ in batch2[0][1]]
    print(claim(key, group, "worker-4", 0, worker2_ids))

    print("(*) XCLAIM with justid=True skips returning the payload.")
    print(claim(key, group, "worker-3", 0, worker2_ids, justid=True))

    print("(*) Acking the reclaimed entries clears the PEL.")
    print(acknowledge(key, group, *worker2_ids))
    print(pending_summary(key, group))

    print("(*) XREADGROUP with noack=True skips the PEL entirely — at-most-once delivery.")
    print(read_group(group, "worker-1", {key: ">"}, count=1, noack=True))

    print("(*) XINFO GROUPS — lag, pending count, last-delivered id.")
    for g in group_info(key):
        print(g)

    print("(*) XINFO CONSUMERS — per-consumer pending and idle time.")
    for consumer in consumer_info(key, group):
        print(consumer)

    print("(*) XGROUP CREATECONSUMER / DELCONSUMER — manage consumers explicitly.")
    print(create_consumer(key, group, "worker-9"))
    print(delete_consumer(key, group, "worker-9"))

    print("(*) XGROUP SETID — rewind the group to the start to reprocess everything.")
    print(set_group_id(key, group, "0"))
    print(group_info(key))

    print("(*) XINFO STREAM — length, first/last entry, radix tree internals.")
    print(stream_info(key))

    print("(*) XDEL — remove a specific entry. Ids are never reused.")
    print(delete_entries(key, ids[0]))
    print(length(key))

    print("(*) XTRIM MAXLEN — cap the stream to its 2 newest entries.")
    print(trim(key, maxlen=2, approximate=False))
    print(read_range(key))

    print("(*) XTRIM MINID — drop everything older than a given id. approximate=False")
    print("    forces an exact trim; the default is approximate, which only trims")
    print("    on whole-node boundaries and may do nothing on a tiny stream.")
    print(trim("sensors:stream", minid=read_range("sensors:stream")[-1][0], approximate=False))
    print(read_range("sensors:stream"))

    print("(*) XGROUP DESTROY and cleanup.")
    print(destroy_group(key, group))
    print(delete_keys(key, "sensors:stream"))
