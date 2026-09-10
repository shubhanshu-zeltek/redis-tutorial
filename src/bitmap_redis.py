"""Redis Bitmaps — https://redis.io/docs/latest/develop/data-types/strings/bitmaps

A bitmap isn't a separate type: it's a string you address one bit at a time.
The classic use is presence tracking — one bit per user id per day, so a million
users cost 125 KB instead of a million set members.
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def set_bit(key, offset, value):
    """SETBIT — write bit at offset (0 or 1). Returns the bit's OLD value."""
    global redis_client
    return redis_client.setbit(key, offset, value)

def get_bit(key, offset):
    """GETBIT — read a single bit. Offsets past the end read as 0."""
    global redis_client
    return redis_client.getbit(key, offset)

def count_bits(key, start=None, end=None, mode=None):
    """BITCOUNT — how many bits are set. mode='BIT' makes start/end bit offsets
    instead of byte offsets (Redis 7.0+)."""
    global redis_client
    if start is None:
        return redis_client.bitcount(key)
    return redis_client.bitcount(key, start, end, mode)

def find_bit(key, bit, start=None, end=None, mode=None):
    """BITPOS — offset of the first 0 or 1 bit in the range."""
    global redis_client
    return redis_client.bitpos(key, bit, start, end, mode)

def bit_operation(operation, destination, *keys):
    """BITOP — AND / OR / XOR across bitmaps, or NOT on a single one."""
    global redis_client
    return redis_client.bitop(operation, destination, *keys)

def byte_length(key):
    """STRLEN — bitmaps grow in whole bytes, so this shows the allocated size."""
    global redis_client
    return redis_client.strlen(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    mon, tue = "visits:2026-09-07", "visits:2026-09-08"
    delete_keys(mon, tue, "visits:both", "visits:either", "visits:changed", "visits:absent", "flags:user:1")

    print("(*) Marking users 1, 5, 42 and 300 as active on Monday.")
    for user_id in (1, 5, 42, 300):
        print(set_bit(mon, user_id, 1))

    print("(*) Marking users 5, 42 and 999 as active on Tuesday.")
    for user_id in (5, 42, 999):
        print(set_bit(tue, user_id, 1))

    print("(*) SETBIT returns the PREVIOUS bit — re-setting user 5 shows 1.")
    print(set_bit(tue, 5, 1))

    print("(*) Was user 42 active on Monday? And user 7?")
    print(get_bit(mon, 42), get_bit(mon, 7))

    print("(*) Reading a bit far past the end is safe — it's just 0.")
    print(get_bit(mon, 100000))

    print("(*) Daily active users = BITCOUNT.")
    print("Monday:", count_bits(mon), " Tuesday:", count_bits(tue))

    print("(*) Bytes actually allocated for each bitmap (highest bit set / 8, rounded up).")
    print(byte_length(mon), byte_length(tue))

    print("(*) BITCOUNT over a byte range — bytes 0..5 of Monday (user ids 0..47).")
    print(count_bits(mon, 0, 5))

    print("(*) BITCOUNT over a BIT range — user ids 0..100 only (Redis 7.0+).")
    print(count_bits(mon, 0, 100, "BIT"))

    print("(*) BITOP AND — users active on BOTH days (retention).")
    print(bit_operation("AND", "visits:both", mon, tue))
    print("count:", count_bits("visits:both"))

    print("(*) BITOP OR — users active on EITHER day (reach).")
    print(bit_operation("OR", "visits:either", mon, tue))
    print("count:", count_bits("visits:either"))

    print("(*) BITOP XOR — users whose status flipped between the two days.")
    print(bit_operation("XOR", "visits:changed", mon, tue))
    print("count:", count_bits("visits:changed"))

    print("(*) BITOP NOT — inverts Monday. Note it inverts whole bytes, so the")
    print("    count reflects every padding bit too, not just real user ids.")
    print(bit_operation("NOT", "visits:absent", mon))
    print("count:", count_bits("visits:absent"))

    print("(*) BITPOS — first user id that was active on Monday.")
    print(find_bit(mon, 1))

    print("(*) BITPOS — first user id that was NOT active on Monday.")
    print(find_bit(mon, 0))

    print("(*) BITPOS with a BIT range — first active id at or after 100.")
    print(find_bit(mon, 1, 100, -1, "BIT"))

    print("(*) Bitmaps also work as a compact set of feature flags per user.")
    DARK_MODE, BETA, EMAIL_OPT_IN = 0, 1, 2
    set_bit("flags:user:1", DARK_MODE, 1)
    set_bit("flags:user:1", EMAIL_OPT_IN, 1)
    print("dark_mode:", get_bit("flags:user:1", DARK_MODE))
    print("beta:", get_bit("flags:user:1", BETA))
    print("email_opt_in:", get_bit("flags:user:1", EMAIL_OPT_IN))
    print("flags enabled:", count_bits("flags:user:1"))

    print("(*) Turning a flag back off.")
    print(set_bit("flags:user:1", DARK_MODE, 0))
    print("flags enabled:", count_bits("flags:user:1"))

    print("(*) Cleaning up.")
    print(delete_keys(mon, tue, "visits:both", "visits:either", "visits:changed",
                      "visits:absent", "flags:user:1"))
