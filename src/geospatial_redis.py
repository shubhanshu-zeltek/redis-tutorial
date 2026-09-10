"""Redis Geospatial indexes — https://redis.io/docs/latest/develop/data-types/geospatial

A geo index is a sorted set in disguise: Redis encodes longitude/latitude into a
52-bit geohash and stores it as the member's score. That's why ZREM, ZCARD and
ZRANGE all work on a geo key — and why GEOADD is really "ZADD with coordinates".

Valid ranges: longitude -180..180, latitude -85.05112878..85.05112878.
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def add_locations(key, values, **kwargs):
    """GEOADD. values is a flat sequence: lon1, lat1, name1, lon2, lat2, name2, ...
    kwargs: nx, xx, ch."""
    global redis_client
    return redis_client.geoadd(key, values, **kwargs)

def get_positions(key, *members):
    """GEOPOS — (longitude, latitude) per member, None if unknown."""
    global redis_client
    return redis_client.geopos(key, *members)

def distance(key, place1, place2, unit="km"):
    """GEODIST — unit is one of m, km, mi, ft."""
    global redis_client
    return redis_client.geodist(key, place1, place2, unit)

def geohashes(key, *members):
    """GEOHASH — standard 11-character geohash strings (geohash.org compatible)."""
    global redis_client
    return redis_client.geohash(key, *members)

def search(key, **kwargs):
    """GEOSEARCH — the modern replacement for GEORADIUS / GEORADIUSBYMEMBER.

    Centre: either member=..., or longitude=... + latitude=...
    Shape:  radius=... (circle) or width=... + height=... (box)
    Extras: unit, sort ('ASC'/'DESC'), count, any, withcoord, withdist, withhash.
    """
    global redis_client
    return redis_client.geosearch(key, **kwargs)

def search_store(destination, key, **kwargs):
    """GEOSEARCHSTORE — same query, result written to another key.
    storedist=True stores distances as scores instead of geohashes."""
    global redis_client
    return redis_client.geosearchstore(destination, key, **kwargs)


# Geo keys ARE sorted sets, so these all work on them:

def member_count(key):
    global redis_client
    return redis_client.zcard(key)

def all_members(key):
    global redis_client
    return redis_client.zrange(key, 0, -1)

def remove_locations(key, *members):
    global redis_client
    return redis_client.zrem(key, *members)

def key_type(key):
    global redis_client
    return redis_client.type(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    key = "stores:india"
    delete_keys(key, "stores:near:bengaluru", "stores:by:distance")

    print("(*) GEOADD — a handful of Indian cities as store locations.")
    print(add_locations(key, [
        77.5946, 12.9716, "bengaluru",
        72.8777, 19.0760, "mumbai",
        77.2090, 28.6139, "delhi",
        80.2707, 13.0827, "chennai",
        78.4867, 17.3850, "hyderabad",
        88.3639, 22.5726, "kolkata",
        73.8567, 18.5204, "pune",
        76.9366, 8.5241, "thiruvananthapuram",
    ]))

    print("(*) A geo key is literally a sorted set — TYPE proves it.")
    print(key_type(key), member_count(key))
    print(all_members(key))

    print("(*) GEOADD NX — never move an existing location.")
    print(add_locations(key, [0, 0, "bengaluru", 75.7873, 26.9124, "jaipur"], nx=True, ch=True))

    print("(*) GEOADD XX — only update locations that already exist.")
    print(add_locations(key, [77.5950, 12.9720, "bengaluru", 91.7362, 26.1445, "guwahati"],
                        xx=True, ch=True))

    print("(*) GEOPOS — coordinates come back slightly lossy; that's the 52-bit geohash.")
    print(get_positions(key, "bengaluru", "mumbai", "atlantis"))

    print("(*) GEODIST — Bengaluru to Mumbai, in four units.")
    for unit in ("km", "mi", "m", "ft"):
        print(f"    {unit}: {distance(key, 'bengaluru', 'mumbai', unit)}")

    print("(*) GEODIST with a member that doesn't exist returns None.")
    print(distance(key, "bengaluru", "atlantis"))

    print("(*) GEOHASH — shareable 11-char geohash strings.")
    print(geohashes(key, "bengaluru", "delhi"))

    print("(*) GEOSEARCH BYRADIUS around a MEMBER — stores within 600km of Bengaluru.")
    print(search(key, member="bengaluru", radius=600, unit="km"))

    print("(*) Same search, with distance, coordinates and hash attached, nearest first.")
    print(search(key, member="bengaluru", radius=600, unit="km",
                 withdist=True, withcoord=True, withhash=True, sort="ASC"))

    print("(*) GEOSEARCH BYRADIUS around raw COORDINATES (a user's GPS fix).")
    print(search(key, longitude=77.5946, latitude=12.9716, radius=1000, unit="km",
                 withdist=True, sort="ASC"))

    print("(*) COUNT limits the result to the N nearest.")
    print(search(key, member="bengaluru", radius=2000, unit="km",
                 withdist=True, sort="ASC", count=3))

    print("(*) COUNT with ANY=True returns as soon as N are found — faster, unsorted.")
    print(search(key, member="bengaluru", radius=2000, unit="km", count=3, any=True))

    print("(*) sort='DESC' — farthest first.")
    print(search(key, member="bengaluru", radius=2000, unit="km", withdist=True, sort="DESC"))

    print("(*) GEOSEARCH BYBOX — a rectangle instead of a circle.")
    print(search(key, longitude=77.5946, latitude=12.9716,
                 width=1000, height=1000, unit="km", withdist=True, sort="ASC"))

    print("(*) GEOSEARCHSTORE — persist the nearby stores into another key.")
    print(search_store("stores:near:bengaluru", key,
                       member="bengaluru", radius=600, unit="km", sort="ASC"))
    print(all_members("stores:near:bengaluru"))

    print("(*) GEOSEARCHSTORE with storedist=True stores DISTANCES as the scores,")
    print("    which turns the result into a ready-made 'nearest first' sorted set.")
    print(search_store("stores:by:distance", key,
                       member="bengaluru", radius=2000, unit="km", storedist=True))
    print(redis_client.zrange("stores:by:distance", 0, -1, withscores=True))

    print("(*) A tiny radius finds only the centre itself.")
    print(search(key, member="bengaluru", radius=1, unit="km"))

    print("(*) ZREM removes a location, because it's all just a sorted set.")
    print(remove_locations(key, "jaipur"))
    print(member_count(key))

    print("(*) 'guwahati' was never stored (the XX add above skipped it), so")
    print("    removing it returns 0.")
    print(remove_locations(key, "guwahati"))

    print("(*) Cleaning up.")
    print(delete_keys(key, "stores:near:bengaluru", "stores:by:distance"))
