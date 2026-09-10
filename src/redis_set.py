import redis


redis_client: redis.Redis = None
def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def add_members(key, *members):
    global redis_client
    return redis_client.sadd(key, *members)

def remove_members(key, *members):
    global redis_client
    return redis_client.srem(key, *members)

def get_all_members(key):
    global redis_client
    return redis_client.smembers(key)

def count_members(key):
    global redis_client
    return redis_client.scard(key)

def is_member(key, value):
    global redis_client
    return redis_client.sismember(key, value)

def are_members(key, *values):
    global redis_client
    return redis_client.smismember(key, *values)

def pop_random_member(key, count=1):
    global redis_client
    return redis_client.spop(key, count)

def get_random_member(key, count=1):
    global redis_client
    return redis_client.srandmember(key, count)

def move_member(source, destination, member):
    global redis_client
    return redis_client.smove(source, destination, member)

def intersection(*keys):
    global redis_client
    return redis_client.sinter(*keys)

def union(*keys):
    global redis_client
    return redis_client.sunion(*keys)

def difference(*keys):
    global redis_client
    return redis_client.sdiff(*keys)

def intersection_store(destination, *keys):
    global redis_client
    return redis_client.sinterstore(destination, *keys)

def union_store(destination, *keys):
    global redis_client
    return redis_client.sunionstore(destination, *keys)

def difference_store(destination, *keys):
    global redis_client
    return redis_client.sdiffstore(destination, *keys)

def intersection_count(*keys, limit=0):
    global redis_client
    return redis_client.sintercard(len(keys), keys, limit=limit)


if __name__ == "__main__":
    init_client()

    print("(*) Adding tags to article:1.")
    resp = add_members("article:1:tags", "python", "redis", "backend")
    print(resp)

    print("(*) Adding tags to article:2.")
    resp = add_members("article:2:tags", "redis", "database", "nosql")
    print(resp)

    print("(*) All tags on article:1.")
    resp = get_all_members("article:1:tags")
    print(resp)

    print("(*) Tag count on article:1.")
    resp = count_members("article:1:tags")
    print(resp)

    print("(*) Is 'python' a tag on article:1?")
    resp = is_member("article:1:tags", "python")
    print(resp)

    print("(*) Which of these are tags on article:1: python, java, redis?")
    resp = are_members("article:1:tags", "python", "java", "redis")
    print(resp)

    print("(*) Tags common to both articles (intersection).")
    resp = intersection("article:1:tags", "article:2:tags")
    print(resp)

    print("(*) All tags across both articles (union).")
    resp = union("article:1:tags", "article:2:tags")
    print(resp)

    print("(*) Tags unique to article:1 (difference).")
    resp = difference("article:1:tags", "article:2:tags")
    print(resp)

    print("(*) Storing shared tags under 'shared:tags'.")
    resp = intersection_store("shared:tags", "article:1:tags", "article:2:tags")
    print(resp)

    print("(*) Members of 'shared:tags'.")
    resp = get_all_members("shared:tags")
    print(resp)

    print("(*) Removing 'backend' tag from article:1.")
    resp = remove_members("article:1:tags", "backend")
    print(resp)

    print("(*) Moving 'python' tag from article:1 to article:2.")
    resp = move_member("article:1:tags", "article:2:tags", "python")
    print(resp)

    print("(*) article:1 tags now.")
    resp = get_all_members("article:1:tags")
    print(resp)

    print("(*) article:2 tags now.")
    resp = get_all_members("article:2:tags")
    print(resp)

    print("(*) Random tag from article:2, without removing it.")
    resp = get_random_member("article:2:tags")
    print(resp)

    print("(*) Popping a random tag from article:2 (removes it).")
    resp = pop_random_member("article:2:tags")
    print(resp)

    print("(*) Count of tags common to article:1 and article:2, via SINTERCARD.")
    resp = intersection_count("article:1:tags", "article:2:tags")
    print(resp)

