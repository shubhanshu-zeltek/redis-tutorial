"""Redis Strings — https://redis.io/docs/latest/develop/data-types/strings

A string is just a sequence of bytes, up to 512 MB. It is the type you get when
you SET a key to a plain value, and it doubles as Redis' integer/float counter.
"""

import time

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


# --- Basic set / get ---

def set_value(key, value, **kwargs):
    """SET. kwargs: ex/px (TTL), nx/xx (conditional), keepttl, get."""
    global redis_client
    return redis_client.set(key, value, **kwargs)

def get_value(key):
    global redis_client
    return redis_client.get(key)

def set_if_absent(key, value):
    """SETNX — only create the key when it doesn't already exist."""
    global redis_client
    return redis_client.setnx(key, value)

def set_with_ttl(key, value, seconds):
    """SETEX — set value and TTL in one atomic command."""
    global redis_client
    return redis_client.setex(key, seconds, value)

def set_with_ttl_ms(key, value, milliseconds):
    """PSETEX — same as SETEX but millisecond precision."""
    global redis_client
    return redis_client.psetex(key, milliseconds, value)

def get_and_set(key, value):
    """GETSET — return the old value while writing the new one."""
    global redis_client
    return redis_client.getset(key, value)

def get_and_delete(key):
    """GETDEL — read the value and drop the key, atomically."""
    global redis_client
    return redis_client.getdel(key)

def get_and_expire(key, **kwargs):
    """GETEX — read the value and (re)set its TTL. kwargs: ex/px/exat/pxat/persist."""
    global redis_client
    return redis_client.getex(key, **kwargs)


# --- Multi-key variants (one round trip instead of N) ---

def set_many(mapping):
    global redis_client
    return redis_client.mset(mapping)

def set_many_if_all_absent(mapping):
    """MSETNX — all-or-nothing: writes only if every key is missing."""
    global redis_client
    return redis_client.msetnx(mapping)

def get_many(*keys):
    global redis_client
    return redis_client.mget(keys)


# --- Treating the string as text ---

def append_value(key, value):
    global redis_client
    return redis_client.append(key, value)

def value_length(key):
    global redis_client
    return redis_client.strlen(key)

def get_substring(key, start, end):
    """GETRANGE — inclusive byte range; negative indexes count from the end."""
    global redis_client
    return redis_client.getrange(key, start, end)

def overwrite_at(key, offset, value):
    """SETRANGE — patch bytes in place starting at offset."""
    global redis_client
    return redis_client.setrange(key, offset, value)

def longest_common_subsequence(key1, key2, **kwargs):
    """LCS — diff two strings. kwargs: len=True, idx=True, minmatchlen, withmatchlen."""
    global redis_client
    return redis_client.lcs(key1, key2, **kwargs)


# --- Treating the string as a number ---

def increment(key, amount=1):
    global redis_client
    return redis_client.incr(key, amount)

def increment_by(key, amount):
    global redis_client
    return redis_client.incrby(key, amount)

def decrement(key, amount=1):
    global redis_client
    return redis_client.decr(key, amount)

def decrement_by(key, amount):
    global redis_client
    return redis_client.decrby(key, amount)

def increment_float(key, amount):
    global redis_client
    return redis_client.incrbyfloat(key, amount)


# --- Key lifecycle, shared by every data type but easiest to show on strings ---

def key_exists(*keys):
    global redis_client
    return redis_client.exists(*keys)

def key_type(key):
    global redis_client
    return redis_client.type(key)

def set_expiry(key, seconds):
    global redis_client
    return redis_client.expire(key, seconds)

def time_to_live(key):
    """TTL — seconds left, -1 if no TTL, -2 if the key is gone."""
    global redis_client
    return redis_client.ttl(key)

def expiry_timestamp(key):
    """EXPIRETIME — the absolute unix time the key dies at."""
    global redis_client
    return redis_client.expiretime(key)

def remove_expiry(key):
    global redis_client
    return redis_client.persist(key)

def copy_key(source, destination, replace=False):
    global redis_client
    return redis_client.copy(source, destination, replace=replace)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    delete_keys("user:1:name", "user:1:bio", "page:home:views", "cart:99:total",
                "session:abc", "otp:9876", "user:1:name:copy", "text:a", "text:b")

    print("(*) Plain SET then GET.")
    print(set_value("user:1:name", "Shubhanshu"))
    print(get_value("user:1:name"))

    print("(*) SET with NX — the key already exists, so this must fail.")
    print(set_value("user:1:name", "SomeoneElse", nx=True))

    print("(*) SET with XX — only overwrite an existing key. This one succeeds.")
    print(set_value("user:1:name", "Shubhanshu Jha", xx=True))

    print("(*) SET ... GET — swap the value and get the previous one back in the same call.")
    print(set_value("user:1:name", "Shubhanshu", get=True))

    print("(*) SETNX on a fresh key — creates it.")
    print(set_if_absent("session:abc", "logged-in"))

    print("(*) SETNX again on the same key — refuses to clobber.")
    print(set_if_absent("session:abc", "hijacked"))

    print("(*) SETEX — a one-time password that self-destructs in 30s.")
    print(set_with_ttl("otp:9876", "441203", 30))
    print("TTL:", time_to_live("otp:9876"))

    print("(*) PSETEX — same idea, 1500 milliseconds.")
    print(set_with_ttl_ms("session:abc", "short-lived", 1500))

    print("(*) GETEX — read the OTP and stretch its life to 60s in one shot.")
    print(get_and_expire("otp:9876", ex=60))
    print("TTL now:", time_to_live("otp:9876"))

    print("(*) EXPIRETIME — the absolute unix second the OTP expires at.")
    print(expiry_timestamp("otp:9876"))

    print("(*) PERSIST — cancel the TTL, make it permanent again.")
    print(remove_expiry("otp:9876"))
    print("TTL now:", time_to_live("otp:9876"))

    print("(*) MSET — write three keys in one round trip.")
    print(set_many({"user:1:city": "Bengaluru", "user:1:role": "engineer", "user:1:lang": "python"}))

    print("(*) MGET — read them back, plus one key that doesn't exist.")
    print(get_many("user:1:city", "user:1:role", "user:1:lang", "user:1:nope"))

    print("(*) MSETNX — all-or-nothing; 'user:1:city' exists so nothing is written.")
    print(set_many_if_all_absent({"user:1:city": "Delhi", "user:1:pin": "560001"}))

    print("(*) APPEND — build a bio incrementally.")
    print(append_value("user:1:bio", "Backend engineer. "))
    print(append_value("user:1:bio", "Learning Redis."))
    print(get_value("user:1:bio"))

    print("(*) STRLEN — length of the bio in bytes.")
    print(value_length("user:1:bio"))

    print("(*) GETRANGE — first 18 bytes, then the last 15 via negative indexes.")
    print(get_substring("user:1:bio", 0, 17))
    print(get_substring("user:1:bio", -15, -1))

    print("(*) SETRANGE — patch 'Backend' into 'Platform' territory at offset 0.")
    print(overwrite_at("user:1:bio", 0, "Platform"))
    print(get_value("user:1:bio"))

    print("(*) INCR — a page-view counter. The key doesn't exist yet; Redis treats it as 0.")
    for _ in range(3):
        print(increment("page:home:views"))

    print("(*) INCRBY / DECRBY — bulk adjustments.")
    print(increment_by("page:home:views", 100))
    print(decrement_by("page:home:views", 3))

    print("(*) DECR — single step down.")
    print(decrement("page:home:views"))

    print("(*) INCRBYFLOAT — money, so decimals matter.")
    set_value("cart:99:total", "249.50")
    print(increment_float("cart:99:total", 30.25))
    print(increment_float("cart:99:total", -79.75))

    print("(*) LCS — longest common subsequence between two strings.")
    set_many({"text:a": "ohmytext", "text:b": "mynewtext"})
    print(longest_common_subsequence("text:a", "text:b"))
    print(longest_common_subsequence("text:a", "text:b", len=True))
    print(longest_common_subsequence("text:a", "text:b", idx=True, minmatchlen=4, withmatchlen=True))

    print("(*) TYPE and EXISTS.")
    print(key_type("user:1:name"))
    print(key_exists("user:1:name", "user:1:bio", "user:1:nope"))

    print("(*) COPY — duplicate a key.")
    print(copy_key("user:1:name", "user:1:name:copy", replace=True))
    print(get_value("user:1:name:copy"))

    print("(*) GETDEL — read the session token and burn it.")
    set_value("session:abc", "final-token")
    print(get_and_delete("session:abc"))
    print(get_value("session:abc"))

    print("(*) Watching a short TTL actually expire.")
    set_with_ttl("session:abc", "expiring", 1)
    print("TTL:", time_to_live("session:abc"))
    time.sleep(1.2)
    print("After 1.2s:", get_value("session:abc"), "TTL:", time_to_live("session:abc"))

    print("(*) DEL — cleaning up the keys this demo created.")
    print(delete_keys("user:1:name", "user:1:bio", "page:home:views", "cart:99:total",
                      "user:1:city", "user:1:role", "user:1:lang", "otp:9876",
                      "user:1:name:copy", "text:a", "text:b"))
