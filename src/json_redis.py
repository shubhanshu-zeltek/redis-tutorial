"""Redis JSON — https://redis.io/docs/latest/develop/data-types/json

Stores a real JSON document as a Redis value and lets you read or mutate any
node inside it with a JSONPath, so you never have to GET-parse-modify-SET a
whole blob just to bump one counter.

Requires the JSON module — run docker-compose-stack.yaml.yaml (Redis Stack),
not the plain redis:7-alpine compose file.

Path syntax: '$' is the root. JSONPath expressions like '$.address.city',
'$..price' (recursive) or '$.items[*].qty' (wildcard) return a LIST of every
match, which is why most replies below are lists.
"""

import redis


redis_client: redis.Redis = None

def init_client(host: str = "localhost", port: int = 6379):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, decode_responses=True)
    return redis_client


# --- Documents ---

def set_doc(key, path, obj, nx=False, xx=False):
    """JSON.SET — nx creates only, xx updates only."""
    global redis_client
    return redis_client.json().set(key, path, obj, nx=nx, xx=xx)

def get_doc(key, *paths):
    global redis_client
    return redis_client.json().get(key, *paths)

def get_many(keys, path):
    """JSON.MGET — the same path across several documents."""
    global redis_client
    return redis_client.json().mget(keys, path)

def set_many(triplets):
    """JSON.MSET — [(key, path, obj), ...] applied atomically (Redis Stack 7.0+)."""
    global redis_client
    return redis_client.json().mset(triplets)

def merge_doc(key, path, obj):
    """JSON.MERGE — RFC 7386 merge patch; a null value deletes that field."""
    global redis_client
    return redis_client.json().merge(key, path, obj)

def delete_path(key, path="$"):
    global redis_client
    return redis_client.json().delete(key, path)

def clear_path(key, path="$"):
    """JSON.CLEAR — empties containers / zeroes numbers, keeps the keys."""
    global redis_client
    return redis_client.json().clear(key, path)

def value_type(key, path="$"):
    global redis_client
    return redis_client.json().type(key, path)

def as_resp(key, path="$"):
    """JSON.RESP — the document rendered in RESP wire form."""
    global redis_client
    return redis_client.json().resp(key, path)


# --- Numbers ---

def increment(key, path, number):
    global redis_client
    return redis_client.json().numincrby(key, path, number)

def multiply(key, path, number):
    global redis_client
    return redis_client.json().nummultby(key, path, number)


# --- Strings ---

def append_string(key, path, value):
    global redis_client
    return redis_client.json().strappend(key, value, path)

def string_length(key, path):
    global redis_client
    return redis_client.json().strlen(key, path)


# --- Booleans ---

def toggle_bool(key, path):
    global redis_client
    return redis_client.json().toggle(key, path)


# --- Arrays inside the document ---

def array_append(key, path, *values):
    global redis_client
    return redis_client.json().arrappend(key, path, *values)

def array_insert(key, path, index, *values):
    global redis_client
    return redis_client.json().arrinsert(key, path, index, *values)

def array_index(key, path, scalar, start=None, stop=None):
    global redis_client
    return redis_client.json().arrindex(key, path, scalar, start=start, stop=stop)

def array_length(key, path):
    global redis_client
    return redis_client.json().arrlen(key, path)

def array_pop(key, path, index=-1):
    global redis_client
    return redis_client.json().arrpop(key, path, index)

def array_trim(key, path, start, stop):
    global redis_client
    return redis_client.json().arrtrim(key, path, start, stop)


# --- Objects inside the document ---

def object_keys(key, path="$"):
    global redis_client
    return redis_client.json().objkeys(key, path)

def object_length(key, path="$"):
    global redis_client
    return redis_client.json().objlen(key, path)


def delete_keys(*keys):
    global redis_client
    return redis_client.delete(*keys)


if __name__ == "__main__":
    init_client()

    try:
        redis_client.json().set("json:probe", "$", {"ok": True})
        redis_client.delete("json:probe")
    except redis.exceptions.ResponseError:
        raise SystemExit(
            "This script needs the JSON module. Start Redis Stack instead of plain Redis:\n"
            "    docker compose -f docker-compose-stack.yaml.yaml up -d"
        )

    key = "product:2001"
    delete_keys(key, "product:2002", "order:1")

    print("(*) JSON.SET at the root — a whole nested document in one key.")
    print(set_doc(key, "$", {
        "sku": "KB-88",
        "name": "Mechanical Keyboard",
        "price": 4999.0,
        "in_stock": True,
        "stock_count": 12,
        "tags": ["peripherals", "typing"],
        "specs": {"switches": "brown", "layout": "75%", "backlit": True},
        "reviews": [
            {"user": "riya", "rating": 5, "text": "Great thock."},
            {"user": "arjun", "rating": 4, "text": "Slightly loud."},
        ],
    }))

    print("(*) JSON.GET the whole document.")
    print(get_doc(key))

    print("(*) JSON.GET a single scalar path.")
    print(get_doc(key, "$.price"))

    print("(*) JSON.GET several paths at once — returns a dict keyed by path.")
    print(get_doc(key, "$.name", "$.specs.layout", "$.tags"))

    print("(*) A recursive path '$..rating' pulls every rating, at any depth.")
    print(get_doc(key, "$..rating"))

    print("(*) A wildcard path '$.reviews[*].user'.")
    print(get_doc(key, "$.reviews[*].user"))

    print("(*) A filter expression — reviews rated 5.")
    print(get_doc(key, "$.reviews[?(@.rating==5)]"))

    print("(*) JSON.TYPE at the root and at a leaf.")
    print(value_type(key, "$"), value_type(key, "$.price"), value_type(key, "$.tags"))

    print("(*) JSON.SET on a nested path — update just one field, no read-modify-write.")
    print(set_doc(key, "$.specs.layout", "TKL"))
    print(get_doc(key, "$.specs"))

    print("(*) JSON.SET with NX — the path exists, so nothing happens (returns None).")
    print(set_doc(key, "$.price", 1.0, nx=True))
    print(get_doc(key, "$.price"))

    print("(*) JSON.SET with NX on a NEW path does create it.")
    print(set_doc(key, "$.warranty_months", 24, nx=True))
    print(get_doc(key, "$.warranty_months"))

    print("(*) JSON.SET with XX only updates what already exists.")
    print(set_doc(key, "$.nonexistent", "nope", xx=True))

    print("(*) JSON.NUMINCRBY — decrement stock atomically (a sale).")
    print(increment(key, "$.stock_count", -3))

    print("(*) JSON.NUMMULTBY — a 10% price rise.")
    print(multiply(key, "$.price", 1.1))

    print("(*) JSON.TOGGLE — flip a boolean in place.")
    print(toggle_bool(key, "$.in_stock"))
    print(toggle_bool(key, "$.in_stock"))

    print("(*) JSON.STRAPPEND / JSON.STRLEN on a string leaf.")
    print(append_string(key, "$.name", " (Hot-swappable)"))
    print(string_length(key, "$.name"))
    print(get_doc(key, "$.name"))

    print("(*) JSON.ARRAPPEND / ARRLEN on the tags array.")
    print(array_append(key, "$.tags", "mechanical", "rgb"))
    print(array_length(key, "$.tags"))
    print(get_doc(key, "$.tags"))

    print("(*) JSON.ARRINSERT at index 1.")
    print(array_insert(key, "$.tags", 1, "gaming"))
    print(get_doc(key, "$.tags"))

    print("(*) JSON.ARRINDEX — where is 'rgb'? And something that isn't there?")
    print(array_index(key, "$.tags", "rgb"), array_index(key, "$.tags", "wireless"))

    print("(*) JSON.ARRPOP — last element, then index 0.")
    print(array_pop(key, "$.tags"))
    print(array_pop(key, "$.tags", 0))
    print(get_doc(key, "$.tags"))

    print("(*) JSON.ARRTRIM — keep only elements 0..1.")
    print(array_trim(key, "$.tags", 0, 1))
    print(get_doc(key, "$.tags"))

    print("(*) Appending a whole object to the reviews array.")
    print(array_append(key, "$.reviews", {"user": "meera", "rating": 5, "text": "Worth it."}))
    print(get_doc(key, "$.reviews[*].user"))

    print("(*) JSON.OBJKEYS / JSON.OBJLEN on a nested object.")
    print(object_keys(key, "$.specs"))
    print(object_length(key, "$.specs"))
    print(object_keys(key, "$"))

    print("(*) JSON.MERGE — RFC 7386 patch: update one spec, add another,")
    print("    and delete 'backlit' by merging it to null.")
    print(merge_doc(key, "$.specs", {"switches": "silent red", "keycaps": "PBT", "backlit": None}))
    print(get_doc(key, "$.specs"))

    print("(*) JSON.MSET — write several documents atomically.")
    print(set_many([
        ("product:2002", "$", {"sku": "MS-10", "name": "Mouse", "price": 1499.0}),
        ("order:1", "$", {"items": ["KB-88", "MS-10"], "total": 6498.0}),
    ]))

    print("(*) JSON.MGET — the same path across many documents.")
    print(get_many([key, "product:2002"], "$.name"))
    print(get_many([key, "product:2002"], "$.price"))

    print("(*) JSON.CLEAR — empty the containers and zero the numbers, keys intact.")
    print(clear_path("product:2002", "$.price"))
    print(get_doc("product:2002"))

    print("(*) JSON.RESP — the document in RESP wire form.")
    print(as_resp("product:2002"))

    print("(*) JSON.DEL on a path removes just that node.")
    print(delete_path(key, "$.warranty_months"))
    print(object_keys(key, "$"))

    print("(*) JSON.DEL at the root deletes the whole document.")
    print(delete_path(key, "$"))
    print(get_doc(key))

    print("(*) Cleaning up.")
    print(delete_keys(key, "product:2002", "order:1"))
