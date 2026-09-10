"""Redis Hashes — https://redis.io/docs/latest/develop/data-types/hashes

A hash is a key holding a flat map of field -> value: one Redis key for a whole
record, instead of one key per attribute. Fields can be read, written and
counted individually, and since Redis 7.4 they can even expire individually.
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


# --- Writing ---

def set_field(key, field, value):
    global redis_client
    return redis_client.hset(key, field, value)

def set_fields(key, mapping):
    """HSET with a whole mapping — the modern replacement for HMSET."""
    global redis_client
    return redis_client.hset(key, mapping=mapping)

def set_field_if_absent(key, field, value):
    """HSETNX — write only when the field doesn't exist yet."""
    global redis_client
    return redis_client.hsetnx(key, field, value)

def delete_fields(key, *fields):
    global redis_client
    return redis_client.hdel(key, *fields)


# --- Reading ---

def get_field(key, field):
    global redis_client
    return redis_client.hget(key, field)

def get_fields(key, *fields):
    global redis_client
    return redis_client.hmget(key, list(fields))

def get_all(key):
    """HGETALL — fine for small records, dangerous on huge hashes. Use HSCAN then."""
    global redis_client
    return redis_client.hgetall(key)

def field_names(key):
    global redis_client
    return redis_client.hkeys(key)

def field_values(key):
    global redis_client
    return redis_client.hvals(key)

def field_count(key):
    global redis_client
    return redis_client.hlen(key)

def field_exists(key, field):
    global redis_client
    return redis_client.hexists(key, field)

def value_length(key, field):
    global redis_client
    return redis_client.hstrlen(key, field)

def random_field(key, count=None, with_values=False):
    global redis_client
    return redis_client.hrandfield(key, count, withvalues=with_values)

def scan_fields(key, match=None, count=None):
    """HSCAN — cursor-based iteration that never blocks the server."""
    global redis_client
    cursor = 0
    results = {}
    while True:
        cursor, data = redis_client.hscan(key, cursor=cursor, match=match, count=count)
        results.update(data)
        if cursor == 0:
            return results


# --- Counters living inside a hash ---

def increment_field(key, field, amount=1):
    global redis_client
    return redis_client.hincrby(key, field, amount)

def increment_field_float(key, field, amount=1.0):
    global redis_client
    return redis_client.hincrbyfloat(key, field, amount)


# --- Per-field TTL (Redis 7.4+) ---

def expire_fields(key, seconds, *fields):
    global redis_client
    return redis_client.hexpire(key, seconds, *fields)

def expire_fields_at(key, unix_time, *fields):
    global redis_client
    return redis_client.hexpireat(key, unix_time, *fields)

def field_ttl(key, *fields):
    global redis_client
    return redis_client.httl(key, *fields)

def field_expiretime(key, *fields):
    global redis_client
    return redis_client.hexpiretime(key, *fields)

def persist_fields(key, *fields):
    global redis_client
    return redis_client.hpersist(key, *fields)


def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "student:1001"
    delete_keys(key, "student:1002")

    print("(*) HSET with a mapping — one record, five fields.")
    print(set_fields(key, {
        "name": "Shubhanshu",
        "email": "shubhanshu@college.edu",
        "roll_number": "CS-2024-045",
        "attendance_count": 0,
        "library_token": "abc123",
    }))

    print("(*) HGET a single field.")
    print(get_field(key, "name"))

    print("(*) HMGET several fields, including one that doesn't exist.")
    print(get_fields(key, "name", "roll_number", "phone"))

    print("(*) HGETALL — the whole record as a dict.")
    print(get_all(key))

    print("(*) HKEYS / HVALS / HLEN.")
    print(field_names(key))
    print(field_values(key))
    print(field_count(key))

    print("(*) HEXISTS.")
    print(field_exists(key, "email"), field_exists(key, "phone"))

    print("(*) HSTRLEN — byte length of the email value.")
    print(value_length(key, "email"))

    print("(*) HSETNX — 'name' already exists, so this refuses to overwrite.")
    print(set_field_if_absent(key, "name", "SomeoneElse"))

    print("(*) HSETNX on a new field does write.")
    print(set_field_if_absent(key, "phone", "+91-99999-00000"))
    print(get_field(key, "phone"))

    print("(*) HINCRBY — mark the student present three times.")
    for _ in range(3):
        print(increment_field(key, "attendance_count", 1))

    print("(*) HINCRBY with a negative amount subtracts.")
    print(increment_field(key, "attendance_count", -1))

    print("(*) HINCRBYFLOAT — fees due, then a partial payment.")
    set_field(key, "fees_due", "500.75")
    print(increment_field_float(key, "fees_due", -150.25))

    print("(*) HRANDFIELD — one random field name.")
    print(random_field(key))

    print("(*) HRANDFIELD with count and values.")
    print(random_field(key, count=3, with_values=True))

    print("(*) HRANDFIELD with a NEGATIVE count allows repeats.")
    print(random_field(key, count=-5))

    print("(*) HEXPIRE — 60s TTL on just the library token (Redis 7.4+).")
    print(expire_fields(key, 60, "library_token"))

    print("(*) HTTL — seconds left per field. -1 means 'no TTL', -2 'no such field'.")
    print(field_ttl(key, "library_token", "name", "ghost"))

    print("(*) HEXPIRETIME — the absolute unix second each field dies at.")
    print(field_expiretime(key, "library_token", "name"))

    print("(*) HPERSIST — cancel that TTL.")
    print(persist_fields(key, "library_token"))
    print(field_ttl(key, "library_token"))

    print("(*) HDEL — drop a field.")
    print(delete_fields(key, "phone"))

    print("(*) HSCAN — iterate every field without a blocking HGETALL.")
    print(scan_fields(key))

    print("(*) HSCAN with a MATCH pattern — only fields starting with 'f'.")
    print(scan_fields(key, match="f*"))

    print("(*) A second record, to show hashes are just independent keys.")
    set_fields("student:1002", {"name": "Riya", "roll_number": "CS-2024-046"})
    print(get_all("student:1002"))

    print("(*) Cleaning up.")
    print(delete_keys(key, "student:1002"))
