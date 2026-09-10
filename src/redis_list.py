import redis


redis_client: redis.Redis = None
def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def add_to_stack(key, value):
    global redis_client
    return redis_client.lpush(key, value)

def add_to_queue(key, value):
    global redis_client
    return redis_client.lpush(key, value)

def remove_from_stack(key):
    global redis_client
    return redis_client.lpop(key)

def remove_from_queue(key):
    global redis_client
    return redis_client.rpop(key)


if __name__ == "__main__":
    init_client()

    print("(*) Adding elements to Stack.")
    key = "counter:stack"
    for i in range(1, 6):
        resp = add_to_stack(key=key, value=i)
        print(resp)

    print("(*) Removing elements from Stack.")
    for i in range(1, 3):
        resp = remove_from_stack(key=key)
        print(resp)

    print("(*) Adding elements to Queue.")
    key = "counter:queue"
    for i in range(1, 6):
        resp = add_to_queue(key=key, value=i)
        print(resp)

    print("(*) Removing elements from Queue.")
    for i in range(1, 3):
        resp = remove_from_queue(key=key)
        print(resp)

    key = "counter:index"
    print("(*) Adding some elements into the List.")
    for i in range(1, 5):
        resp = redis_client.lpush(key, i)
        print(resp)

    resp = redis_client.lrange(key, 0, -1)
    print(resp)
    
