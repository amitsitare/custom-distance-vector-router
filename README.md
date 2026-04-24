# Distance-vector router (Docker lab)

Files:

- **`router.py`** — Distance-vector over UDP; **poison reverse** (advertise distance 16 back to the neighbor you learned a prefix from); neighbor keyed by **UDP source IP**; Linux routes use **`via … dev … onlink`** on multi-homed containers; optional **`STARTUP_DELAY`** (default 3s) before reading interfaces; if **`LOCAL_SUBNETS`** is empty, subnets are inferred from **`ip -4 addr`** like many reference solutions.
- **`Dockerfile`** — Alpine image that runs `router.py`.
- **`docker-compose.yml`** — Five routers on six `/24` subnets **`10.100.1.0/24` … `10.100.6.0/24`** (same topology as common `10.0.1`–`10.0.6` labs, but **`10.0.2.0/24` often collides** with WSL/VirtualBox on Windows, which causes Docker’s *“Pool overlaps with other one on this address space”* error).
- **`testcase.py`** — Local checks; auto-detects **ring5** vs **triangle** from running containers.

## Prerequisites

Docker with Compose (`docker compose` or `docker-compose`), run commands from this repo root.

## Run the lab

If a previous run failed halfway, clear networks first:

```bash
docker compose down -v
docker compose up -d --build
```

Use exactly: `docker compose` (two words). A typo like `docker composeose` will not run Compose.

Wait **about 30–90 seconds** for convergence (default DV broadcast interval is 5s).

Inspect:

```bash
docker exec router_a ip route
docker logs --tail 80 router_a
```

## Automated tests

```bash
python3 testcase.py --auto
```

On Windows: `py -3 testcase.py --auto`.

With the default `docker-compose.yml` (five routers), tests expect **every** router to have a kernel route for **all six** subnets. Increase wait on slow hosts:

```bash
python3 testcase.py --auto --wait 120
```

Force topology (optional):

```bash
python3 testcase.py --topology ring5
python3 testcase.py --topology triangle
```

`--failover` only applies to the **three-router** triangle setup (not ring5).

## Clean reset

```bash
docker compose down -v
docker compose up -d --build
```

## “Pool overlaps with other one on this address space”

Docker cannot create a bridge network whose subnet is already in use on your PC (very common for **`10.0.2.0/24`**). This project uses **`10.100.x.0/24`** in `docker-compose.yml` to avoid that. If your course **requires** `10.0.x` addresses, use the compose file your instructor provides, or change subnets in `docker-compose.yml` and the same prefixes in `router.py` / env vars / `testcase.py` together.

## `lookup registry-1.docker.io: no such host` (build fails)

This is a **network/DNS** problem on your PC, not a bug in `router.py`. Docker cannot reach **Docker Hub** to pull `alpine:3.20`.

Try, in order:

1. **Confirm the internet works** in a browser; turn off **VPN** / “ad blocker DNS” temporarily.
2. **Restart Docker Desktop** and your PC if DNS was flaky.
3. In PowerShell: `nslookup registry-1.docker.io` — if it fails, fix Windows DNS (e.g. adapter IPv4 → use **8.8.8.8** and **8.8.4.4**, or your router’s DNS).
4. **Docker Desktop → Settings → Docker Engine** — some users add `"dns": ["8.8.8.8","8.8.4.4"]`, Apply & Restart.
5. While online, pre-pull once: `docker pull alpine:3.20`, then `docker compose up -d --build` again.

This repo sets **`build.pull: false`** in `docker-compose.yml` so Compose can reuse a **cached** Alpine image when you already pulled it earlier.

**Command typo:** use `python testcase.py --auto --wait 120` (no extra text after `120`).

## Environment variables (`router.py`)

| Variable | Meaning |
|----------|---------|
| `MY_IP` | `router_id` field in JSON (advertised id) |
| `NEIGHBORS` | Comma-separated **peer** IPs on shared links |
| `LOCAL_SUBNETS` | Comma-separated attached `/24` networks |
| `PORT` | UDP port (default `5000`) |
| `BROADCAST_INTERVAL` | Seconds between sends (default `5`) |
| `NEIGHBOR_TIMEOUT` | Seconds without packets before flushing routes via that neighbor (default `3×` interval) |
| `STARTUP_DELAY` | Seconds to sleep before init (default `3`; set `0` to disable) |

Neighbors are keyed by **UDP source address** so routers with several interfaces (e.g. `router_b`, `router_c`) stay consistent with `NEIGHBORS`.
