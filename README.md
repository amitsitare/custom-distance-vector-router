# Distance-vector router (lab)

Small Python router daemon that exchanges distance-vector updates over UDP (port 5000), updates the Linux routing table, and runs in Docker.

## Prerequisites

- Docker with Compose (`docker compose` or `docker-compose`)

## Run the triangle topology

```bash
docker compose up --build
```

Wait ~15–30 seconds for routes to settle.

Compose sets each lab network’s gateway to `x.x.x.254` so router IPs like `10.0.1.1` do not clash with Docker’s default bridge gateway (`x.x.x.1`), which can cause “Address already in use” on Windows.

## Check routing

```bash
docker exec -it router_a ip route
docker logs router_a
```

## Failover test

Stop one router, then check routes again (after the timeout, paths should switch):

```bash
docker stop router_c
docker exec -it router_a ip route
```

## Environment variables

| Variable | Meaning |
|----------|---------|
| `MY_IP` | Used as `router_id` in JSON packets |
| `NEIGHBORS` | Comma-separated neighbor IPs |
| `LOCAL_SUBNETS` | Comma-separated attached networks (CIDR), e.g. two `/24`s per router |
| `PORT` | UDP port (default `5000`) |
| `BROADCAST_INTERVAL` | Seconds between sends (default `5`) |
| `NEIGHBOR_TIMEOUT` | Seconds without updates before dropping routes via that neighbor (default `3×` broadcast interval) |

## Build image only

```bash
docker build -t my-router .
```

All router logic is in `router.py`.

## Tests (optional script for the report)

Requires **Python 3** and **Docker** on your PATH. From the project folder:

```bash
python testcase.py --auto
```

This runs `docker compose up -d --build`, then polls up to **90s** for logs and `10.0.2.0/24` on `router_a`. Override with `python testcase.py --auto --wait 120`.

```bash
python testcase.py --auto --failover
```

Same, then stops `router_c` and checks the backup path (restore with `docker start router_c`).

If the lab is already up:

```bash
python testcase.py
```

`--compose` is the same as `--auto` without the shorthand name. Exit code `0` means checks passed.
