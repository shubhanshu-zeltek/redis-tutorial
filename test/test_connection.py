"""
Quick check that Redis (started via docker-compose) is reachable
from a Python script running on your host machine.
"""

import redis

# Since docker-compose maps port 6379 on the container to 6379 on your
# host, "localhost" is the correct hostname when running this script
# directly on your machine (not inside another container).
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

r.set("hello", "world")
value = r.get("hello")

print(f"Connected. redis says: {value}")
print("PING ->", r.ping())

# Clean up: remove the test key so this script doesn't leave data behind
deleted = r.delete("hello")
print(f"Cleanup -> removed {deleted} key(s)")
