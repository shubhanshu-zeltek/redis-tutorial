# Redis Geospatial Indexes — Notes

Practice script: [`src/geospatial_redis.py`](../src/geospatial_redis.py)
Official docs: https://redis.io/docs/latest/develop/data-types/geospatial

---

## What it is

**A [sorted set](SORTED_SET_NOTES.md) in disguise.** Redis encodes a
longitude/latitude pair into a single 52-bit **geohash integer** and stores it
as the member's **score**. The `GEO*` commands are convenience wrappers that do
that encoding and the distance maths for you.

This is not a trivia point — it has real consequences:

- `TYPE` on a geo key returns **`zset`**.
- `ZCARD`, `ZRANGE`, `ZREM`, `ZSCORE` all work on geo keys.
- **There is no `GEODEL`.** You remove a location with `ZREM`.
- A geo key can be `ZUNIONSTORE`d, expired, copied — it's a sorted set.

---

## Key facts

- Valid **longitude**: `-180` to `180`.
- Valid **latitude**: `-85.05112878` to `85.05112878`. Not ±90 — that's the
  limit of the Mercator-style projection the geohash uses, so **the poles are
  not representable**. Out-of-range coordinates are an error.
- **Coordinates come back slightly different from what you put in.** The 52-bit
  geohash quantizes position; the error is under about 0.5 m. Never round-trip
  a coordinate through Redis and expect bit-identical values.
- Distance units: **`m`, `km`, `mi`, `ft`**. `GEODIST` defaults to `m`.
- Distance is computed on a **sphere (haversine)**, not the WGS84 ellipsoid, so
  there's a small error (well under 0.5%) versus a proper GIS library.

---

## Complexity

| Operation | Cost |
|---|---|
| `GEOADD` | O(log N) per member |
| `GEOPOS`, `GEOHASH`, `GEODIST` | O(1) / O(log N) |
| `GEOSEARCH` | O(N + log M) — N = members in the bounding area, M = total |

---

## Adding locations

```bash
GEOADD key <lon> <lat> <member> [<lon> <lat> <member> ...]
GEOADD key NX <lon> <lat> <member>    # only add new members
GEOADD key XX <lon> <lat> <member>    # only update existing members
GEOADD key CH <lon> <lat> <member>    # return count CHANGED, not just added
```

**Longitude comes first, then latitude.** This trips up nearly everyone, because
people say and write "lat, long". Redis wants `lon lat`.

The `NX` / `XX` / `CH` flags behave exactly as they do for `ZADD` — because
under the hood, that's what this is.

In redis-py the values are a **flat sequence**, not tuples:

```python
client.geoadd("key", [77.5946, 12.9716, "bengaluru", 72.8777, 19.0760, "mumbai"])
```

---

## Reading positions

```bash
GEOPOS key member [member ...]     # [[lon, lat], ...]; nil per unknown member
GEOHASH key member [member ...]    # standard 11-char geohash.org strings
GEODIST key m1 m2 [m|km|mi|ft]     # nil if either member is unknown
```

`GEOHASH` returns the **standard** geohash string, which is portable — you can
paste it into geohash.org. That's different from the internal 52-bit score,
which you'd see via `ZSCORE`.

---

## Searching — `GEOSEARCH`

The modern, single command for proximity queries (Redis 6.2+). It replaces
`GEORADIUS`, `GEORADIUSBYMEMBER`, and their `_RO` variants, all now deprecated.

You must pick **a centre** and **a shape**:

```bash
# Centre: an existing member...
GEOSEARCH key FROMMEMBER bengaluru BYRADIUS 600 km ASC

# ...or raw coordinates
GEOSEARCH key FROMLONLAT 77.5946 12.9716 BYRADIUS 600 km ASC

# Shape: a circle...
GEOSEARCH key FROMMEMBER bengaluru BYRADIUS 600 km

# ...or a rectangle
GEOSEARCH key FROMMEMBER bengaluru BYBOX 1000 1000 km
```

Modifiers:

| Modifier | Effect |
|---|---|
| `ASC` / `DESC` | Sort by distance from the centre, nearest / farthest first |
| `COUNT n` | Return at most `n` results |
| `COUNT n ANY` | Return as soon as `n` are found — **faster, but not the nearest `n`** |
| `WITHCOORD` | Include each match's coordinates |
| `WITHDIST` | Include the distance from the centre, in the query's unit |
| `WITHHASH` | Include the raw 52-bit score |

**`COUNT n` alone still sorts to find the genuinely nearest `n`.** Adding `ANY`
short-circuits that — much faster, but the results are arbitrary members within
the radius, not the closest ones. Use `ANY` only when "some nearby" is enough.

**`BYBOX` dimensions are width and height, both centred on the point** — a
`BYBOX 1000 1000 km` search extends 500 km in each direction, not 1000.

---

## Storing search results

```bash
GEOSEARCHSTORE dst src FROMMEMBER m BYRADIUS 600 km ASC
GEOSEARCHSTORE dst src FROMMEMBER m BYRADIUS 600 km STOREDIST
```

- Without `STOREDIST`, the destination is a **geo key** — scores are geohashes,
  so you can search it again.
- With **`STOREDIST`**, the scores are the **distances** from the centre. The
  destination is then an ordinary sorted set ranked nearest-first, which you can
  page through with `ZRANGE`. Handy, but it is no longer a valid geo index.

---

## The deprecated commands

Still present, still working, but don't write new code against them:

| Deprecated | Use instead |
|---|---|
| `GEORADIUS key lon lat r unit` | `GEOSEARCH key FROMLONLAT lon lat BYRADIUS r unit` |
| `GEORADIUSBYMEMBER key m r unit` | `GEOSEARCH key FROMMEMBER m BYRADIUS r unit` |
| `GEORADIUS_RO`, `GEORADIUSBYMEMBER_RO` | `GEOSEARCH` (already read-only) |
| `GEORADIUS ... STORE` | `GEOSEARCHSTORE` |

The old ones were deprecated in 6.2 largely because `GEORADIUS` was a write
command (it could `STORE`), which meant it couldn't be routed to replicas.

---

## Gotchas worth remembering

- **`GEOADD` takes longitude FIRST.** The single most common mistake.
- **Latitude is capped at ±85.05°**, not ±90°. The poles don't exist here.
- **Coordinates you read back are not the ones you wrote** — 52-bit
  quantization, sub-metre error.
- **There is no `GEODEL`.** Use `ZREM`.
- **`COUNT n ANY` does not give you the nearest n.**
- **`BYBOX` width/height are the full extent**, so the search reaches half that
  distance in each direction.
- **`GEODIST` defaults to metres**, while most examples use `km`. Be explicit.
- **`GEOHASH` (the 11-char string) ≠ the internal score.** Different encodings.
- **Distances are spherical**, not ellipsoidal — fine for "shops near me",
  not for surveying.
- A geo key with a member added at a bogus coordinate can't be "fixed" by
  re-adding with `NX` — `NX` refuses to update. Use plain `GEOADD` or `XX`.

---

## Complete command cheat sheet

| Command | What it does |
|---|---|
| `GEOADD key [NX\|XX] [CH] lon lat member [...]` | Add / update locations |
| `GEOPOS key member [member ...]` | Coordinates of member(s) |
| `GEODIST key m1 m2 [m\|km\|mi\|ft]` | Distance between two members |
| `GEOHASH key member [member ...]` | Standard 11-char geohash strings |
| `GEOSEARCH key FROMMEMBER m \| FROMLONLAT lon lat` `BYRADIUS r unit \| BYBOX w h unit` `[ASC\|DESC] [COUNT n [ANY]] [WITHCOORD] [WITHDIST] [WITHHASH]` | Proximity search (6.2+) |
| `GEOSEARCHSTORE dst src <same args> [STOREDIST]` | Search and store the result |
| `GEORADIUS`, `GEORADIUSBYMEMBER`, `*_RO` | **Deprecated** — use `GEOSEARCH` |
| `ZREM key member` | **Remove a location** (there is no `GEODEL`) |
| `ZCARD key` | Number of locations |
| `ZRANGE key 0 -1` | List all members |
| `ZSCORE key member` | The raw 52-bit geohash score |
| `TYPE key` | Returns `zset` |
