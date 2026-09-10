"""Redis Bitfields — https://redis.io/docs/latest/develop/data-types/strings/bitfields

BITFIELD packs many small integers into one string. Instead of ten keys holding
tiny counters, you get ten 8-bit slots inside a single 10-byte value, each with
atomic get/set/incrby and its own overflow policy.

Encodings are 'u<bits>' (unsigned, 1..63) or 'i<bits>' (signed, 1..64).
Offsets are bit offsets, or '#n' meaning "the nth field of this width".
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def bitfield(key, default_overflow=None):
    """Start a BITFIELD pipeline. Chain .set()/.get()/.incrby() then .execute()."""
    global redis_client
    return redis_client.bitfield(key, default_overflow=default_overflow)

def set_field(key, fmt, offset, value):
    global redis_client
    return redis_client.bitfield(key).set(fmt, offset, value).execute()

def get_field(key, fmt, offset):
    global redis_client
    return redis_client.bitfield(key).get(fmt, offset).execute()

def increment_field(key, fmt, offset, increment, overflow=None):
    global redis_client
    return redis_client.bitfield(key).incrby(fmt, offset, increment, overflow=overflow).execute()

def read_only_fields(key, encoding, offset, items=None):
    """BITFIELD_RO — the replica-safe subset: GET operations only."""
    global redis_client
    return redis_client.bitfield_ro(key, encoding, offset, items=items)

def byte_length(key):
    global redis_client
    return redis_client.strlen(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "player:1:stats"
    delete_keys(key, "counters", "temps")

    print("(*) One BITFIELD call writing three packed fields:")
    print("    #0 = level (u8), #1 = lives (u8), #2 = coins (u8).")
    print(bitfield(key)
          .set("u8", "#0", 7)
          .set("u8", "#1", 3)
          .set("u8", "#2", 250)
          .execute())

    print("(*) All three stats live inside a single 3-byte string.")
    print("bytes:", byte_length(key))

    print("(*) Reading them all back in one round trip.")
    print(bitfield(key).get("u8", "#0").get("u8", "#1").get("u8", "#2").execute())

    print("(*) Mixing reads and writes atomically: spend a life, gain 5 coins,")
    print("    and read the resulting level — all in one command.")
    print(bitfield(key)
          .incrby("u8", "#1", -1)
          .incrby("u8", "#2", 5)
          .get("u8", "#0")
          .execute())

    print("(*) Default WRAP overflow: coins is u8 (max 255) at 255, +10 wraps to 9.")
    print(set_field(key, "u8", "#2", 255))
    print(increment_field(key, "u8", "#2", 10))

    print("(*) SAT overflow: the same +10 saturates at 255 instead of wrapping.")
    print(set_field(key, "u8", "#2", 255))
    print(increment_field(key, "u8", "#2", 10, overflow="SAT"))

    print("(*) FAIL overflow: the increment is rejected outright and returns None.")
    print(increment_field(key, "u8", "#2", 10, overflow="FAIL"))

    print("(*) An overflow policy set mid-chain applies to every op AFTER it.")
    print(set_field(key, "u8", "#2", 250))
    print(bitfield(key)
          .incrby("u8", "#2", 10)          # WRAP (the default) -> 4
          .overflow("SAT")
          .incrby("u8", "#2", 300)         # saturates at 255
          .overflow("FAIL")
          .incrby("u8", "#2", 1)           # would overflow -> None
          .execute())

    print("(*) default_overflow sets the policy for the whole chain up front.")
    print(bitfield(key, default_overflow="SAT")
          .set("u8", "#2", 255)
          .incrby("u8", "#2", 100)
          .execute())

    print("(*) Signed fields: i8 spans -128..127, so SAT clamps at -128.")
    print(bitfield("temps", default_overflow="SAT")
          .set("i8", "#0", -120)
          .incrby("i8", "#0", -50)
          .get("i8", "#0")
          .execute())

    print("(*) Raw bit offsets instead of '#n' — a 4-bit field at bit 0 and one at bit 4.")
    print(bitfield("counters")
          .set("u4", 0, 15)
          .set("u4", 4, 9)
          .get("u4", 0)
          .get("u4", 4)
          .execute())
    print("bytes used:", byte_length("counters"))

    print("(*) Eight independent u8 counters packed into 8 bytes.")
    op = bitfield("counters")
    for i in range(8):
        op = op.set("u8", f"#{i}", i * 10)
    print(op.execute())
    print(bitfield("counters").get("u8", "#0").get("u8", "#4").get("u8", "#7").execute())
    print("bytes used:", byte_length("counters"))

    print("(*) BITFIELD_RO — read-only, safe to route to a replica.")
    print(read_only_fields("counters", "u8", "#0", items=[("u8", "#1"), ("u8", "#2")]))

    print("(*) reset() clears a chain so the builder can be reused.")
    op = bitfield(key).get("u8", "#0")
    op.reset()
    print(op.get("u8", "#1").execute())

    print("(*) Cleaning up.")
    print(delete_keys(key, "counters", "temps"))
