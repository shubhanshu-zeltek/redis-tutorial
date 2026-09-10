# Redis (Dockerized) — Local Development Setup

A self-contained Redis instance, run via Docker Compose, reachable from local Python scripts. This README covers how to run it, how to talk to it from Python, and the core Redis concepts you need to work with it confidently.

## Table of Contents

- [What is Redis?](#what-is-redis)
- [Project Structure](#project-structure)
- [Choosing a Setup: Plain Redis vs Redis Stack](#choosing-a-setup-plain-redis-vs-redis-stack)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Verifying Redis is Running](#verifying-redis-is-running)
- [Connecting from Python](#connecting-from-python)
- [Docker Compose Files Explained](#docker-compose-files-explained)
- [Redis Data Types](#redis-data-types)
- [Persistence: RDB vs AOF](#persistence-rdb-vs-aof)
- [Key Expiration (TTL)](#key-expiration-ttl)
- [Pub/Sub](#pubsub)
- [Transactions](#transactions)
- [Redis Stack Extras: RedisInsight & Modules](#redis-stack-extras-redisinsight--modules)
- [Redis CLI Cheat Sheet](#redis-cli-cheat-sheet)
- [Replication, Sentinel & Cluster (Beyond This Setup)](#replication-sentinel--cluster-beyond-this-setup)
- [Security Notes](#security-notes)
- [Licensing](#licensing)
- [Troubleshooting](#troubleshooting)
- [Resources](#resources)

---

## What is Redis?

Redis ("**RE**mote **DI**ctionary **S**erver") is an **in-memory data structure store**. It's most commonly used as a:

- **Cache** — store frequently-read data in memory to avoid hitting a slower database.
- **Database** — a fast, key-value primary store, optionally persisted to disk.
- **Message broker** — via Pub/Sub or Streams, for passing messages between services.
- **Session store** — for web apps that need shared, fast session/state storage.

Key properties:

- **In-memory first**: data lives in RAM, which is why reads/writes are extremely fast (sub-millisecond).
- **Single-threaded core**: the main command execution loop processes one command at a time, which avoids race conditions and makes most operations atomic by default. (Newer versions offload I/O — like reading from the socket — to background threads, but command execution itself stays single-threaded.)
- **Optional persistence**: by default Redis is memory-only, but it can be configured to snapshot or log data to disk so it survives restarts (this project does this — see [Persistence](#persistence-rdb-vs-aof)).
- **Rich data types**: unlike a plain key-value cache (e.g. Memcached), Redis understands structured types like lists, sets, and hashes natively (see [Redis Data Types](#redis-data-types)).
- **Default port**: `6379`.

---

## Project Structure

```
redis-tutorial/
├── myvenv/                     # Python virtual environment (not committed)
├── src/                        # Scripts used to revise Redis concepts
├── test/                       # Testing scripts (e.g. test_connection.py — verifies Redis connectivity)
├── .gitignore
├── docker-compose.yaml         # Plain Redis container
├── docker-compose-stack.yaml   # Redis Stack container (modules + RedisInsight)
├── README.md                   # This file
└── requirements.txt            # Python dependencies (e.g. redis)
```

---

## Choosing a Setup: Plain Redis vs Redis Stack

This repo ships **two** Compose files — pick whichever fits what you're doing right now:

| | `docker-compose.yaml` | `docker-compose-stack.yaml` |
|---|---|---|
| Image | `redis:7-alpine` | `redis/redis-stack:latest` |
| Core Redis commands (strings, lists, sets, etc.) | Yes | Yes |
| Bloom filters, JSON, TimeSeries, full-text/vector search | No | Yes |
| RedisInsight (browser-based GUI) | No | Yes — `http://localhost:8001` |
| Good for | Plain caching / core data-structure practice | Working with modules (e.g. Bloom filters) or browsing data visually |

**Only run one at a time.** Both map Redis to host port `6379`, so starting the second one while the first is still up will fail with `port is already allocated`. Run `docker compose down` (or, for the stack file, `docker compose -f docker-compose-stack.yaml down`) before switching.

---

## Prerequisites

- **Docker** and **Docker Compose** installed ([Docker Desktop](https://www.docker.com/products/docker-desktop/) includes both).
- **Python 3.8+** with `pip`, if you want to run `test_connection.py`.

Check your setup:

```bash
docker --version
docker compose version
python3 --version
```

---

## Getting Started

1. **Start Redis in the background:**
   ```bash
   docker compose up -d
   ```

2. **Check it's running:**
   ```bash
   docker compose ps
   ```

3. **Stop it (keeps your data, since it's in a named volume):**
   ```bash
   docker compose down
   ```

4. **Stop it AND wipe all stored data:**
   ```bash
   docker compose down -v
   ```

5. **View logs:**
   ```bash
   docker compose logs -f redis
   ```

### Using Redis Stack Instead

The commands above default to `docker-compose.yaml` (Compose picks it up automatically since that's its default filename). To use Redis Stack instead, add `-f docker-compose-stack.yaml` to any command:

```bash
docker compose -f docker-compose-stack.yaml up -d
docker compose -f docker-compose-stack.yaml ps
docker compose -f docker-compose-stack.yaml logs -f redis-stack
docker compose -f docker-compose-stack.yaml down
```

---

## Verifying Redis is Running

**Option A — via the healthcheck:**
```bash
docker compose ps
```
The `STATUS` column should show `healthy` once the container's internal `redis-cli ping` check succeeds.

**Option B — via `redis-cli` inside the container:**
```bash
docker exec -it redis redis-cli ping
```
Expected output: `PONG`

*(Running Redis Stack instead? Its container is named `redis-stack`: `docker exec -it redis-stack redis-cli ping`.)*

**Option C — via the included Python script (see below).**

---

## Connecting from Python

Install the client library:

```bash
pip install redis
```

Run the included script:

```bash
python3 test_connection.py
```

It connects to `localhost:6379` (because `docker-compose.yml` maps the container's port 6379 to your host's port 6379), sets a test key, reads it back, pings the server, then deletes the test key so it doesn't leave data behind.

**Important — hostname depends on where your script runs:**

| Where your Python script runs                          | Correct `host` value |
|----------------------------------------------------------|-----------------------|
| Directly on your machine (outside Docker)                 | `localhost`           |
| Inside another container on the **same** Compose network  | `redis` (the service name) |

---

## Docker Compose Files Explained

### `docker-compose.yaml` (plain Redis)

```yaml
services:
  redis:
    image: redis:7-alpine        # Official Redis image, Alpine variant (small footprint)
    container_name: redis        # Fixed, human-readable container name
    restart: unless-stopped      # Auto-restart on crash/reboot unless you stop it manually
    ports:
      - "6379:6379"              # host_port:container_port — makes Redis reachable at localhost:6379
    command: ["redis-server", "--appendonly", "yes"]  # Enables AOF persistence (see below)
    volumes:
      - redis_data:/data         # Named volume, mounted where Redis stores its persistence files
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  redis_data:                    # Declares the named volume so Docker manages its lifecycle
```

| Field | What it does |
|---|---|
| `image` | Which Redis build to pull. `7-alpine` = Redis 7.x on a minimal Linux base. |
| `container_name` | Lets you refer to the container by a fixed name (`docker exec -it redis ...`) instead of an auto-generated one. |
| `restart` | Restart policy. `unless-stopped` survives daemon/machine reboots but respects a manual `docker compose down`. |
| `ports` | Exposes the container's port to your host so local scripts/tools can reach it. |
| `command` | Overrides the container's default startup command — here, to turn on AOF persistence. |
| `volumes` | Mounts a named volume at `/data`, the directory Redis uses for RDB/AOF files, so data outlives the container. |
| `healthcheck` | Lets Docker (and `docker compose ps`) report whether Redis is actually accepting commands, not just "started." |

### `docker-compose-stack.yaml` (Redis Stack)

```yaml
services:
  redis-stack:
    image: redis/redis-stack:latest   # Redis + Bloom/JSON/TimeSeries/Search modules + RedisInsight
    container_name: redis-stack
    restart: unless-stopped
    ports:
      - "6379:6379"    # Redis server
      - "8001:8001"    # RedisInsight (browser GUI) — http://localhost:8001
    environment:
      - REDIS_ARGS=--appendonly yes   # Enable AOF persistence, same as the plain setup
    volumes:
      - redis_stack_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  redis_stack_data:
```

| Field | What it does |
|---|---|
| `image` | `redis/redis-stack` bundles core Redis with extra modules and RedisInsight, all in one image. |
| `ports` (`8001`) | Exposes RedisInsight's web UI on your host, separate from the Redis protocol port. |
| `environment: REDIS_ARGS` | Redis Stack's way of passing flags to the underlying `redis-server` process — the equivalent of `command:` in the plain setup. |
| `volumes` | Its own named volume (`redis_stack_data`), kept separate from the plain setup's `redis_data`, so the two never share or overwrite each other's data. |

---

## Redis Data Types

Redis keys can hold more than plain strings. This is a core reason it's used as more than a cache.

| Type | What it is | Example use case |
|---|---|---|
| **String** | Binary-safe text/bytes/numbers (up to 512MB) | Caching a rendered page, counters (`INCR`) |
| **List** | Ordered, linked list of strings | Queues, activity feeds |
| **Set** | Unordered collection of unique strings | Tags, deduplication, membership checks |
| **Sorted Set (ZSet)** | Set where each member has a score, kept in order | Leaderboards, rate limiting, priority queues |
| **Hash** | Field-value pairs under one key (like a mini-object) | Storing a user record (`name`, `email`, …) under one key |
| **Bitmap** | Bit-level operations on string values | Feature flags, real-time analytics (e.g. daily active users) |
| **HyperLogLog** | Probabilistic structure for approximate unique counts | "How many unique visitors today?" at huge scale, tiny memory |
| **Stream** | Append-only log of entries, each with an ID | Event sourcing, activity logs, lightweight message queues |
| **Geospatial** | Sorted-set variant storing lat/long | "Find nearby drivers/stores" |
| **Vector Set** *(Redis 8+)* | Stores high-dimensional embeddings for similarity search | AI/ML: semantic search, recommendations |

Basic examples (via `redis-cli`):

```bash
SET user:1:name "Shubhanshu"      # String
LPUSH tasks "email" "invoice"     # List
SADD tags "python" "docker"       # Set
ZADD leaderboard 100 "player1"    # Sorted Set
HSET user:1 name "Shubhanshu" age "25"  # Hash
```

---

## Persistence: RDB vs AOF

By default, Redis keeps everything in RAM only — a restart means data loss. This project enables **AOF**, one of two persistence strategies:

| | **RDB** (snapshotting) | **AOF** (Append-Only File) |
|---|---|---|
| How it works | Periodically dumps the entire dataset to a `.rdb` file | Logs every write operation to a file, replayed on restart |
| Recovery speed | Fast (loading a snapshot) | Slower (replaying a log) |
| Data safety | Can lose data since the last snapshot | Can be configured to lose almost nothing (`fsync` every write) |
| File size | Compact | Grows continuously (Redis periodically rewrites/compacts it) |
| This project | Not enabled | **Enabled** via `--appendonly yes` |

You can enable both at once for extra safety — RDB for fast restarts/backups, AOF for durability — which is what most production Redis deployments do.

---

## Key Expiration (TTL)

Any key can be given a **time-to-live**, after which Redis deletes it automatically. This is what makes Redis a natural fit for caching.

```bash
SET session:abc123 "user_data" EX 3600   # Expires in 3600 seconds (1 hour)
TTL session:abc123                        # Check remaining seconds
PERSIST session:abc123                    # Remove the expiration, make it permanent
```

From Python (`redis-py`):

```python
r.set("session:abc123", "user_data", ex=3600)
r.ttl("session:abc123")
```

---

## Pub/Sub

Redis supports simple publish/subscribe messaging — publishers send messages to a channel, subscribers listening on that channel receive them in real time. Messages aren't stored; if nobody's subscribed when a message is published, it's gone.

```bash
# In one terminal:
SUBSCRIBE notifications

# In another terminal:
PUBLISH notifications "New order received"
```

For a message queue that needs to be replayed or persisted, use **Streams** instead — Pub/Sub is fire-and-forget.

---

## Transactions

Redis transactions (`MULTI`/`EXEC`) queue a batch of commands and run them atomically, back-to-back, with no other client's commands interleaved:

```bash
MULTI
SET balance:1 100
DECRBY balance:1 30
EXEC
```

Note: unlike SQL transactions, Redis doesn't roll back on a command failing mid-way (except for syntax errors caught before `EXEC`) — it's about atomicity and isolation from other clients, not "undo."

---

## Redis Stack Extras: RedisInsight & Modules

Only relevant if you're running `docker-compose-stack.yaml`. Plain Redis (`docker-compose.yaml`) doesn't include any of this.

### RedisInsight (GUI)

Open `http://localhost:8001` in a browser. You can browse keys, run commands, and inspect data structures — including Bloom filters — visually, without touching the CLI.

### Bloom Filters

A **Bloom filter** is a probabilistic structure for fast, memory-cheap "have I seen this before?" checks. It can produce false positives (says "maybe seen" when it wasn't) but never false negatives (if it says "definitely not seen," that's certain).

```bash
docker exec -it redis-stack redis-cli
BF.ADD myfilter "item1"            # Add an item
BF.EXISTS myfilter "item1"         # -> 1 (probably present)
BF.EXISTS myfilter "item2"         # -> 0 (definitely absent)
BF.MADD myfilter "item2" "item3"   # Add multiple items at once
```

Good for things like "has this user already claimed this coupon?" or "have we crawled this URL before?" at scale, without storing every single item in a Set.

### Other Modules Available

| Module | Command prefix | Use case |
|---|---|---|
| RedisJSON | `JSON.*` | Store and query JSON documents directly in Redis |
| RediSearch | `FT.*` | Full-text search, and vector similarity search |
| RedisTimeSeries | `TS.*` | Time-stamped data (metrics, sensor readings) with built-in downsampling |
| Probabilistic types | `BF.*`, `CF.*`, `CMS.*`, `TOPK.*` | Bloom filters, Cuckoo filters, Count-Min Sketch, Top-K |

These commands only work against `docker-compose-stack.yaml` — running them against the plain `redis:7-alpine` container returns an `unknown command` error.

---

## Redis CLI Cheat Sheet

```bash
PING                     # Check server is alive -> PONG
KEYS *                   # List all keys (avoid in production — it's slow on big datasets)
SCAN 0                   # Safer alternative to KEYS for large datasets
TYPE mykey               # What data type is this key?
DEL mykey                # Delete a key
EXISTS mykey             # 1 if it exists, 0 if not
EXPIRE mykey 60          # Set a 60-second TTL on an existing key
FLUSHALL                 # Delete EVERYTHING in all databases (careful!)
INFO                     # Server stats: memory, clients, persistence, etc.
MONITOR                  # Live stream of every command hitting the server (debugging only)
DBSIZE                   # Number of keys in the current database
```

---

## Replication, Sentinel & Cluster (Beyond This Setup)

This project runs a **single Redis instance** — fine for local development. In production, Redis is often deployed with:

- **Replication**: one primary, one or more read-only replicas that mirror it, for read scaling and failover.
- **Sentinel**: monitors primary/replica nodes and automates failover if the primary goes down.
- **Cluster**: shards data automatically across multiple nodes, for horizontal scaling beyond one machine's RAM.

None of this is needed for local development against a single container, but it's worth knowing these exist as your usage grows.

---

## Security Notes

This setup is intended for **local development only**. Before using anything like it outside your machine:

- No password is set — anyone who can reach port 6379 has full access. Set one with `requirepass` (or the `--requirepass` command flag) for anything beyond localhost.
- Don't expose port 6379 to the public internet. If you must reach it remotely, put it behind a VPN, SSH tunnel, or firewall rules.
- Consider Redis ACLs (`ACL SETUSER`, available since Redis 6) if you need per-user permissions instead of one shared password.

---

## Licensing

Since Redis 8.0 (2025), Redis ships under a **tri-license model** — you can use it under **AGPLv3** (OSI-approved open source), or the source-available **SSPLv1**/**RSALv2**. Versions before 7.4 (including the `redis:7-alpine` image used here, depending on the exact patch tag) were BSD-3-Clause. If licensing terms matter for your use case (e.g. offering Redis as a managed service), check the exact version tag you're pulling and Redis's official licensing page.

---

## Troubleshooting

| Problem | Likely cause / fix |
|---|---|
| `port is already allocated` | Either something else on your machine is using port 6379, or you have both `docker-compose.yaml` and `docker-compose-stack.yaml` running at once (they both use 6379 — see [Choosing a Setup](#choosing-a-setup-plain-redis-vs-redis-stack)). Stop one, or change the host side of a mapping, e.g. `"6380:6379"`. |
| `Connection refused` from Python | Redis isn't running yet, or you're using the wrong host (`redis` vs `localhost` — see [Connecting from Python](#connecting-from-python)). Run `docker compose ps` to check status. |
| Data disappeared after `docker compose down` | You likely ran `docker compose down -v`, which also removes the named volume. Use `docker compose down` (without `-v`) to keep data. |
| `docker compose ps` shows `unhealthy` | Check logs with `docker compose logs redis` (or `docker compose -f docker-compose-stack.yaml logs redis-stack`) — often a config/startup error. |
| `ModuleNotFoundError: No module named 'redis'` | Run `pip install redis` in the Python environment you're using to run the script. |
| `ERR unknown command 'BF.ADD'` (or `JSON.*`, `FT.*`, `TS.*`) | You're connected to the plain Redis container, not Redis Stack. These module commands only work against `docker-compose-stack.yaml`. |

---

## Resources

- [Official Redis Documentation](https://redis.io/docs/latest/)
- [Redis Commands Reference](https://redis.io/commands/)
- [redis-py (Python client) Documentation](https://redis-py.readthedocs.io/)
- [Redis University (free courses)](https://university.redis.com/)
- [RedisInsight Documentation](https://redis.io/insight/)
- [Probabilistic Data Types (Bloom, Cuckoo, Count-Min Sketch, Top-K)](https://redis.io/docs/latest/develop/data-types/probabilistic/)
