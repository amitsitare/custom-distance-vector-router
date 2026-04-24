# Distance-vector router (Docker lab)

Distance-vector routing over UDP with **poison reverse** (RIP-style: advertise distance **16** back to the neighbor you learned a prefix from). Neighbors are keyed by **UDP source IP** so multi-homed routers match `NEIGHBORS`. Linux static routes use **`ip route replace … via … dev … onlink`** where needed.

After **link** changes (e.g. Docker `network disconnect`), `router.py` periodically **re-syncs direct subnets** from `ip -4 addr` and drops **unreachable nexthops** so prefixes can be relearned through remaining neighbors.

## Files

| File | Role |
|------|------|
| **`router.py`** | DV protocol + kernel routes; read by the grader’s containers. |
| **`Dockerfile`** | Alpine + Python + `iproute2`; required for `docker build -t my-router .`. |
| **`docker-compose.yml`** | Local five-router lab on **`10.100.1.0/24` … `10.100.6.0/24`** (avoids **`10.0.2.0/24`** clashes with WSL/VirtualBox on Windows). |
| **`testcase.py`** | Local checks; auto-detects **ring5** vs **triangle** from running containers. |

## Prerequisites

- **Docker** with Compose (`docker compose` or `docker-compose`).
- **Python 3** for `testcase.py` and for any course evaluation scripts.
- Run compose and `docker build` from **this repo root** (where `Dockerfile` and `router.py` live).

## Run the lab locally

If a previous run failed halfway, clear networks first:

```bash
docker compose down -v
docker compose up -d --build
```

Use exactly: `docker compose` (two words).

Wait **about 30–90 seconds** for convergence (default DV broadcast interval is **5** s).

Inspect:

```bash
docker exec router_a ip route
docker logs --tail 80 router_a
```

## Automated local tests

```bash
python3 testcase.py --auto
```

On Windows:

```powershell
py -3 testcase.py --auto
```

Increase wait on slow hosts:

```bash
python3 testcase.py --auto --wait 120
```

Optional topology:

```bash
python3 testcase.py --topology ring5
python3 testcase.py --topology triangle
```

`--failover` applies only to the **three-router** triangle setup (not ring5).

## Course evaluation scripts (match your professor’s harness)

The grader typically builds from **your** repo and mounts **`router.py`** into each container with **`MY_IP`** and **`NEIGHBORS`** (often **no** `LOCAL_SUBNETS` — subnets come from interfaces).

**Docker Desktop must be running.** In **PowerShell**, from **this repo root**:

**Node failure evaluation** (`evaluate_routers_node.py` — adjust path if your copy is elsewhere):

```powershell
cd "c:\path\to\docker-network-route"
$R = (Resolve-Path ".\router.py").Path
python "c:\path\to\evaluate_routers_node.py" $R $R $R $R $R --log-file ".\routing_eval_node_test.log"
```

**Link failure evaluation** (`evaluate_routers_link.py` or `evaluate_routers.py` per your course):

```powershell
$R = (Resolve-Path ".\router.py").Path
python "c:\path\to\evaluate_routers_link.py" $R $R $R $R $R
```

**Pass:** console shows **`[PASS]`** only (no **`[FAIL]`**), no **`WARNING: Initial convergence failed`** for the node script, and exit code **0**.

Batch scripts (`batch_evaluator.py`, `batch_evaluator_node.py`) clone the repo and invoke the same evaluators; if the two commands above pass, batch runs should report **PASS** for your submission.

## What to push to GitHub

Minimum for grading:

- **`router.py`**
- **`Dockerfile`**

Recommended: push the **whole project** (this README, `docker-compose.yml`, `testcase.py`) and **omit** `__pycache__/`, `*.pyc`, secrets, and large unrelated files. Add a **`.gitignore`** for `__pycache__/`, `*.pyc`, `routing_eval*.log`, and local log folders if you use them.

## Clean reset

```bash
docker compose down -v
docker compose up -d --build
```

## “Pool overlaps with other one on this address space”

Docker cannot create a bridge network whose subnet is already in use on your PC (very common for **`10.0.2.0/24`**). This project uses **`10.100.x.0/24`** in `docker-compose.yml` for local dev. The **course** Docker scripts often use **`10.0.1.0/24` … `10.0.6.0/24`** inside Linux; that is fine when the grader runs on their machine — your **`router.py`** does not hard-code those addresses.

## `lookup registry-1.docker.io: no such host` (build fails)

This is a **network/DNS** issue on your PC, not a bug in `router.py`.

1. Confirm the internet works; try disabling **VPN** / odd DNS temporarily.
2. Restart **Docker Desktop** (and PC if DNS was flaky).
3. `nslookup registry-1.docker.io` — if it fails, fix Windows DNS (e.g. **8.8.8.8** / **8.8.4.4**).
4. Docker Desktop → **Settings → Docker Engine** — some users add `"dns": ["8.8.8.8","8.8.4.4"]`, Apply & Restart.
5. `docker pull alpine:3.20`, then `docker compose up -d --build` again.

This repo sets **`build.pull: false`** in `docker-compose.yml` so Compose can reuse a **cached** Alpine image when you already pulled it.

## Environment variables (`router.py`)

| Variable | Meaning |
|----------|---------|
| `MY_IP` | `router_id` in JSON packets |
| `NEIGHBORS` | Comma-separated peer IPs on shared links |
| `LOCAL_SUBNETS` | Optional comma-separated attached `/24` networks (compose sets this for the **10.100** lab) |
| `PORT` | UDP port (default **5000**) |
| `BROADCAST_INTERVAL` | Seconds between broadcasts (default **5**) |
| `NEIGHBOR_TIMEOUT` | Seconds without packets before flushing routes via that neighbor (default **3×** `BROADCAST_INTERVAL`) |
| `STARTUP_DELAY` | Seconds before init (default **3**; set **0** to disable) |
