import redis


redis_client: redis.Redis = None
def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def set_field(key, field, value):
    global redis_client
    return redis_client.hset(key, field, value)

def set_fields(key, mapping):
    global redis_client
    return redis_client.hset(key, mapping=mapping)

def set_field_if_not_exists(key, field, value):
    global redis_client
    return redis_client.hsetnx(key, field, value)

def get_field(key, field):
    global redis_client
    return redis_client.hget(key, field)

def get_fields(key, *fields):
    global redis_client
    return redis_client.hmget(key, fields)

def get_all(key):
    global redis_client
    return redis_client.hgetall(key)

def get_field_names(key):
    global redis_client
    return redis_client.hkeys(key)

def get_values(key):
    global redis_client
    return redis_client.hvals(key)

def count_fields(key):
    global redis_client
    return redis_client.hlen(key)

def field_exists(key, field):
    global redis_client
    return redis_client.hexists(key, field)

def field_value_length(key, field):
    global redis_client
    return redis_client.hstrlen(key, field)

def delete_fields(key, *fields):
    global redis_client
    return redis_client.hdel(key, *fields)

def increment_field(key, field, amount=1):
    global redis_client
    return redis_client.hincrby(key, field, amount)

def increment_field_float(key, field, amount=1.0):
    global redis_client
    return redis_client.hincrbyfloat(key, field, amount)

def get_random_field(key, count=None, with_values=False):
    global redis_client
    return redis_client.hrandfield(key, count, withvalues=with_values)

def scan_fields(key, match=None, count=None):
    """Incrementally walk every field in a (potentially huge) hash instead of pulling it all in one HGETALL."""
    global redis_client
    cursor = 0
    results = {}
    while True:
        cursor, data = redis_client.hscan(key, cursor=cursor, match=match, count=count)
        results.update(data)
        if cursor == 0:
            break
    return results

# --- Field-level TTL (Redis 7.4+) ---

def expire_fields(key, seconds, *fields):
    global redis_client
    return redis_client.hexpire(key, seconds, *fields)

def field_ttl(key, *fields):
    global redis_client
    return redis_client.httl(key, *fields)

def persist_fields(key, *fields):
    global redis_client
    return redis_client.hpersist(key, *fields)

# --- Atomic get + expire / get + delete (Redis 8.0+) ---

def get_and_set_expiry(key, *fields, seconds):
    global redis_client
    return redis_client.hgetex(key, *fields, ex=seconds)

def get_and_delete(key, *fields):
    global redis_client
    return redis_client.hgetdel(key, *fields)


if __name__ == "__main__":
    init_client()

    key = "student:1001"

    print("(*) Setting multiple fields at once.")
    resp = set_fields(key, {
        "name": "Shubhanshu",
        "email": "shubhanshu@college.edu",
        "roll_number": "CS-2024-045",
        "attendance_count": 0,
        "library_card_token": "abc123",
    })
    print(resp)

    print("(*) Getting a single field.")
    resp = get_field(key, "name")
    print(resp)

    print("(*) Getting multiple specific fields.")
    resp = get_fields(key, "name", "roll_number")
    print(resp)

    print("(*) Getting every field and value.")
    resp = get_all(key)
    print(resp)

    print("(*) Field names only.")
    resp = get_field_names(key)
    print(resp)

    print("(*) Values only.")
    resp = get_values(key)
    print(resp)

    print("(*) Number of fields on the hash.")
    resp = count_fields(key)
    print(resp)

    print("(*) Does 'email' exist on this hash?")
    resp = field_exists(key, "email")
    print(resp)

    print("(*) Length of the 'email' value, in bytes.")
    resp = field_value_length(key, "email")
    print(resp)

    print("(*) Trying to set 'name' via HSETNX (should NOT overwrite, field exists).")
    resp = set_field_if_not_exists(key, "name", "SomeoneElse")
    print(resp)

    print("(*) Incrementing 'attendance_count' by 1 (student marked present).")
    resp = increment_field(key, "attendance_count", 1)
    print(resp)

    print("(*) Setting fees due, then reducing it after a partial payment.")
    set_field(key, "fees_due", "500.75")
    resp = increment_field_float(key, "fees_due", -150.25)
    print(resp)

    print("(*) Getting one random field name.")
    resp = get_random_field(key)
    print(resp)

    print("(*) Getting 2 random fields WITH their values.")
    resp = get_random_field(key, count=2, with_values=True)
    print(resp)

    print("(*) Setting a 60-second TTL on just the 'library_card_token' field (Redis 7.4+).")
    resp = expire_fields(key, 60, "library_card_token")
    print(resp)

    print("(*) Checking remaining TTL on 'library_card_token' and 'name'.")
    resp = field_ttl(key, "library_card_token", "name")
    print(resp)

    print("(*) Removing that TTL again, making 'library_card_token' permanent.")
    resp = persist_fields(key, "library_card_token")
    print(resp)

    print("(*) Reading 'attendance_count' while also giving it a fresh 30s TTL, atomically (Redis 8.0+).")
    try:
        resp = get_and_set_expiry(key, "attendance_count", seconds=30)
        print(resp)
    except redis.exceptions.ResponseError:
        print("Skipped — HGETEX requires Redis 8.0+. Your server is on Redis 7.x (redis:7-alpine), "
              "which doesn't have it yet. HEXPIRE/HTTL/HPERSIST above still work since those only need 7.4+.")

    print("(*) Reading and clearing 'fees_due' in one atomic step, once fully paid (Redis 8.0+).")
    try:
        resp = get_and_delete(key, "fees_due")
        print(resp)
    except redis.exceptions.ResponseError:
        print("Skipped — HGETDEL also requires Redis 8.0+. Falling back to a manual HGET + HDEL instead:")
        resp = get_field(key, "fees_due")
        delete_fields(key, "fees_due")
        print(resp)

    print("(*) Deleting the 'email' field outright.")
    resp = delete_fields(key, "email")
    print(resp)

    print("(*) Scanning every remaining field (HSCAN, useful for large hashes).")
    resp = scan_fields(key)
    print(resp)
