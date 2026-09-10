import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client

if __name__ == "__main__":
    init_client()

    key = "msg:5"
    value = "Hey there, what's up??"
    # resp = redis_client.set(key, value, ex=10)  # TTL is 10sec, if wants in ms then go with px
    resp = redis_client.set(key, value)
    print(resp)
    resp = redis_client.expire(key, time=12)  # expire in 12sec
    print(resp)
