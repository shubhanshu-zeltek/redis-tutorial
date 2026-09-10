"""Redis Vector sets — https://redis.io/docs/latest/develop/data-types/vector-sets

A sorted set, but ordered by VECTOR SIMILARITY instead of a numeric score.
Each element carries a high-dimensional vector; VSIM returns the elements whose
vectors point in most nearly the same direction (cosine similarity), backed by
an HNSW graph so the search stays fast as the set grows.

This is the native building block for semantic search, recommendations and
RAG retrieval. JSON attributes on each element let you filter the search —
"similar to this, but only in stock and under 20000" — in a single call.

Requires Redis 8.0+. Neither docker-compose.yaml (redis:7-alpine) nor the
current redis/redis-stack image has vector sets, so run a Redis 8 server:

    docker run -d --rm --name redis8 -p 6380:6379 redis:8-alpine
    python src/vector_set_redis.py

In redis-py these commands live behind the .vset() accessor, not on the client
directly — redis_client.vset().vadd(...), not redis_client.vadd(...).
"""

import redis
from redis.commands.vectorset.commands import QuantizationOptions


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


def add_vector(key, vector, element, **kwargs):
    """VADD. kwargs: reduce_dim (random projection), cas, ef, attributes,
    numlinks, and quantization — which redis-py wants as a QuantizationOptions
    enum member (QuantizationOptions.Q8), not a plain string."""
    global redis_client
    return redis_client.vset().vadd(key, vector, element, **kwargs)

def similar(key, query, **kwargs):
    """VSIM — query is a vector, or the name of an element already in the set.
    kwargs: count, with_scores, with_attribs, filter, filter_ef, ef, epsilon, truth."""
    global redis_client
    return redis_client.vset().vsim(key, query, **kwargs)

def dimensions(key):
    global redis_client
    return redis_client.vset().vdim(key)

def cardinality(key):
    global redis_client
    return redis_client.vset().vcard(key)

def remove_element(key, element):
    global redis_client
    return redis_client.vset().vrem(key, element)

def embedding(key, element, raw=False):
    """VEMB — the stored vector. Quantization makes it approximate."""
    global redis_client
    return redis_client.vset().vemb(key, element, raw=raw)

def links(key, element, with_scores=False):
    """VLINKS — the element's HNSW neighbours, per graph layer."""
    global redis_client
    return redis_client.vset().vlinks(key, element, with_scores=with_scores)

def set_attributes(key, element, attributes):
    global redis_client
    return redis_client.vset().vsetattr(key, element, attributes)

def get_attributes(key, element):
    global redis_client
    return redis_client.vset().vgetattr(key, element)

def random_elements(key, count=None):
    global redis_client
    return redis_client.vset().vrandmember(key, count)

def lexical_range(key, start, end, count=None):
    """VRANGE — elements in a lexicographic range, ignoring similarity."""
    global redis_client
    return redis_client.vset().vrange(key, start, end, count=count)

def info(key):
    global redis_client
    return redis_client.vset().vinfo(key)

def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    import sys

    # Vector sets need Redis 8; pass a port on the command line if your Redis 8
    # server isn't on the default one, e.g.  python src/vector_set_redis.py 6380
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6379
    init_client(port=port)

    try:
        redis_client.vset().vadd("vset:probe", [1.0, 0.0], "probe")
        redis_client.delete("vset:probe")
    except (redis.exceptions.ResponseError, AttributeError):
        version = redis_client.info("server").get("redis_version", "unknown")
        raise SystemExit(
            f"Vector sets need Redis 8.0+, and the server on port {port} reports {version}.\n"
            "Start one and point this script at it:\n"
            "    docker run -d --rm --name redis8 -p 6380:6379 redis:8-alpine\n"
            "    python src/vector_set_redis.py 6380"
        )

    key = "catalog:embeddings"
    delete_keys(key, "vecs:reduced")

    # Toy 4-dimensional "embeddings". Real ones come from an embedding model and
    # are typically 384-1536 dimensions; the API is identical either way.
    products = {
        "keyboard":   ([0.90, 0.10, 0.05, 0.20], {"category": "peripherals", "price": 4999, "stock": 12}),
        "keypad":     ([0.88, 0.14, 0.07, 0.18], {"category": "peripherals", "price": 1999, "stock": 40}),
        "mouse":      ([0.80, 0.20, 0.10, 0.25], {"category": "peripherals", "price": 1499, "stock": 0}),
        "monitor":    ([0.20, 0.85, 0.15, 0.30], {"category": "displays",    "price": 18999, "stock": 5}),
        "tv":         ([0.15, 0.90, 0.20, 0.25], {"category": "displays",    "price": 42999, "stock": 2}),
        "novel":      ([0.05, 0.10, 0.95, 0.10], {"category": "books",       "price": 499, "stock": 100}),
        "textbook":   ([0.08, 0.12, 0.90, 0.15], {"category": "books",       "price": 1299, "stock": 7}),
        "headphones": ([0.60, 0.25, 0.10, 0.85], {"category": "audio",       "price": 8999, "stock": 9}),
    }

    print("(*) VADD — one element per product, with JSON attributes attached.")
    for name, (vector, attrs) in products.items():
        print(name, add_vector(key, vector, name, attributes=attrs))

    print("(*) VCARD and VDIM.")
    print(cardinality(key), dimensions(key))

    print("(*) VSIM by ELEMENT — what's most like the keyboard?")
    print(similar(key, "keyboard"))

    print("(*) VSIM with scores — 1.0 is identical, 0.0 is opposite.")
    print(similar(key, "keyboard", with_scores=True))

    print("(*) VSIM by raw QUERY VECTOR — this is the semantic-search path:")
    print("    embed the user's text, hand the vector straight to VSIM.")
    print(similar(key, [0.85, 0.15, 0.05, 0.20], count=3, with_scores=True))

    print("(*) COUNT limits the result set.")
    print(similar(key, "novel", count=2, with_scores=True))

    print("(*) WITHATTRIBS returns each element's JSON payload alongside it, so")
    print("    one round trip gives you the ranking AND the data to render.")
    print(similar(key, "monitor", count=3, with_scores=True, with_attribs=True))

    print("(*) HYBRID SEARCH — similarity plus a structured filter over the")
    print("    attributes. Similar to the keyboard, but only items in stock:")
    print(similar(key, "keyboard", filter=".stock > 0", with_scores=True))

    print("    Similar to the monitor, but under 20,000:")
    print(similar(key, "monitor", filter=".price < 20000", with_scores=True))

    print("    Combined predicates:")
    print(similar(key, "keyboard", filter='.category == "peripherals" and .stock > 5'))

    print("(*) filter_ef widens the graph search so a restrictive filter still")
    print("    finds enough candidates.")
    print(similar(key, "novel", filter=".price < 1000", filter_ef=500))

    print("(*) EF raises search effort: more accurate, slower.")
    print(similar(key, "keyboard", count=3, ef=200, with_scores=True))

    print("(*) TRUTH forces an exact linear scan — the ground truth you can")
    print("    check the approximate results against.")
    print(similar(key, "keyboard", count=3, truth=True, with_scores=True))

    print("(*) VGETATTR / VSETATTR — read and rewrite an element's attributes.")
    print(get_attributes(key, "mouse"))
    print(set_attributes(key, "mouse", {"category": "peripherals", "price": 1299, "stock": 25}))
    print(get_attributes(key, "mouse"))

    print("(*) That restock immediately changes what the filtered search returns —")
    print("    'mouse' now passes the .stock > 0 filter.")
    print(similar(key, "keyboard", filter=".stock > 0", with_scores=True))

    print("(*) VEMB — the stored vector, quantized and therefore approximate.")
    print(embedding(key, "keyboard"))

    print("(*) VEMB with raw=True exposes the internal representation.")
    print(embedding(key, "keyboard", raw=True))

    print("(*) VLINKS — the element's neighbours in each HNSW layer.")
    print(links(key, "keyboard", with_scores=True))

    print("(*) VRANDMEMBER — random sampling.")
    print(random_elements(key))
    print(random_elements(key, 3))
    print("negative count allows repeats:", random_elements(key, -5))

    print("(*) VRANGE — plain lexicographic range, no similarity involved.")
    print(lexical_range(key, "-", "+"))
    print(lexical_range(key, "[k", "[n"))

    print("(*) VINFO — dimensions, quantization, HNSW parameters, node counts.")
    print(info(key))

    print("(*) QUANTIZATION trades recall for memory. Q8 (int8) is the default;")
    print("    NOQUANT keeps full float32; BIN is one bit per dimension.")
    for quant in (QuantizationOptions.NOQUANT, QuantizationOptions.Q8, QuantizationOptions.BIN):
        target = f"vecs:{quant.value.lower()}"
        delete_keys(target)
        for name, (vector, _) in products.items():
            add_vector(target, vector, name, quantization=quant)
        print(f"    {quant.value:<8} stored as {info(target)['quant-type']:<8} "
              f"{redis_client.memory_usage(target)} bytes")
        print("            ", similar(target, "keyboard", count=3, with_scores=True))
        delete_keys(target)
    print("    BIN collapses each dimension to one bit, so on 4-dim toy vectors")
    print("    it throws away nearly everything and the ranking goes nonsense.")
    print("    On real 768/1536-dim embeddings it holds up far better.")

    print("(*) REDUCE applies random projection to shrink the dimension on write,")
    print("    which is how a 1536-dim embedding stays affordable.")
    for name, (vector, _) in products.items():
        add_vector("vecs:reduced", vector, name, reduce_dim=2)
    print("    stored dimension:", dimensions("vecs:reduced"))
    print("   ", similar("vecs:reduced", "keyboard", count=3, with_scores=True))

    print("(*) CAS does the expensive graph insert without holding the lock.")
    print(add_vector(key, [0.5, 0.5, 0.5, 0.5], "mystery-item", cas=True))

    print("(*) VREM — delete an element from the set and the graph.")
    print(remove_element(key, "mystery-item"))
    print(cardinality(key))

    print("(*) Cleaning up.")
    print(delete_keys(key, "vecs:reduced"))
