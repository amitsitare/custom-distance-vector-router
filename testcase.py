from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
ROUTERS_TRIANGLE = ("router_a", "router_b", "router_c")
ROUTERS_RING5 = ("router_a", "router_b", "router_c", "router_d", "router_e")
# Six lab subnets (must match docker-compose.yml; 10.100.x avoids Windows 10.0.2.0/24 clashes).
SUBNETS_RING5 = tuple(f"10.100.{i}.0/24" for i in range(1, 7))
LOG_MARKERS = ("[init]", "[tx]", "[rx]", "[bf]", "[warn]", "[send]", "[purge]", "[timeout]", "[direct]", "[nh]")

_compose_cmd_cache: Optional[list[str]] = None


def _run(cmd: list[str], timeout: float = 60) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def compose_command() -> list[str]:
    """Docker Compose v2 (`docker compose`) or legacy v1 (`docker-compose`)."""
    global _compose_cmd_cache
    if _compose_cmd_cache is not None:
        return _compose_cmd_cache
    code, _, _ = _run(["docker", "compose", "version"], timeout=15)
    if code == 0:
        _compose_cmd_cache = ["docker", "compose"]
        return _compose_cmd_cache
    code, _, _ = _run(["docker-compose", "version"], timeout=15)
    if code == 0:
        _compose_cmd_cache = ["docker-compose"]
        return _compose_cmd_cache
    _compose_cmd_cache = ["docker", "compose"]
    return _compose_cmd_cache


def running_container_names() -> set[str]:
    code, out, _ = _run(["docker", "ps", "--format", "{{.Names}}"], timeout=30)
    if code != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def detect_topology() -> str:
    names = running_container_names()
    if "router_e" in names:
        return "ring5"
    return "triangle"


def routers_for_topology(top: str) -> tuple[str, ...]:
    return ROUTERS_RING5 if top == "ring5" else ROUTERS_TRIANGLE


def docker_ok() -> bool:
    code, out, err = _run(["docker", "version", "-f", "{{.Server.Version}}"], timeout=15)
    if code != 0:
        print("FAIL: docker CLI not working:", err or out)
        return False
    return True


def containers_running(top: str) -> bool:
    names = running_container_names()
    need = routers_for_topology(top)
    missing = [n for n in need if n not in names]
    if missing:
        print("FAIL: containers not running:", ", ".join(missing))
        c = " ".join(compose_command())
        print(f"Hint: {c} up -d --build   (from the project folder that contains docker-compose.yml)")
        return False
    print("OK: routers running:", ", ".join(need))
    return True


def ip_route_on(name: str) -> str:
    code, out, err = _run(["docker", "exec", name, "ip", "route"], timeout=30)
    if code != 0:
        raise RuntimeError(f"ip route failed on {name}: {err}")
    return out


def has_route_via(table: str, subnet: str, via: str) -> bool:
    for line in table.splitlines():
        if subnet in line and f"via {via}" in line:
            return True
    return False


def route_line_for_subnet(table: str, subnet: str) -> Optional[str]:
    for line in table.splitlines():
        if subnet in line and "via" in line:
            return line.strip()
    return None


def has_subnet_route(table: str, subnet: str) -> bool:
    """True if kernel FIB has an entry for this prefix (connected or static)."""
    for line in table.splitlines():
        s = line.strip()
        if s.startswith(subnet):
            return True
    return False


def compose_up() -> bool:
    cmd = [*compose_command(), "up", "-d", "--build"]
    print("Starting stack:", " ".join(cmd), "...")
    code, out, err = _run(cmd, timeout=300)
    if code != 0:
        print("FAIL: compose up failed:", err or out)
        print("Hint: start Docker Desktop / the Docker daemon; run this from the repo root.")
        print("      Try: docker compose up -d --build   or legacy: docker-compose up -d --build")
        return False
    print("OK: compose up finished")
    return True


def test_converged_triangle() -> bool:
    table = ip_route_on("router_a")
    print("--- router_a ip route (snippet) ---")
    for line in table.splitlines()[:12]:
        print(line)
    line = route_line_for_subnet(table, "10.0.2.0/24")
    if not line:
        print("FAIL: no kernel route to 10.0.2.0/24 on router_a")
        return False
    if has_route_via(table, "10.0.2.0/24", "10.0.3.2"):
        print("OK: 10.0.2.0/24 via 10.0.3.2 (Net_AC)")
        return True
    if has_route_via(table, "10.0.2.0/24", "10.0.1.2"):
        print("OK: 10.0.2.0/24 via 10.0.1.2 (alternate equal-cost path)")
        return True
    print("FAIL: unexpected next hop for 10.0.2.0/24:", line)
    return False


def test_converged_ring5() -> bool:
    ok_all = True
    for r in ROUTERS_RING5:
        table = ip_route_on(r)
        missing = [s for s in SUBNETS_RING5 if not has_subnet_route(table, s)]
        if missing:
            print(f"FAIL: {r} missing routes for: {set(missing)}")
            ok_all = False
        else:
            print(f"OK: {r} has all {len(SUBNETS_RING5)} subnet routes")
    if ok_all:
        print("--- router_a ip route (sample) ---")
        for line in ip_route_on("router_a").splitlines()[:16]:
            print(line)
    return ok_all


def test_logs_activity() -> bool:
    code, out, err = _run(["docker", "logs", "--tail", "400", "router_a"], timeout=30)
    if code != 0:
        print("FAIL: docker logs router_a:", err)
        return False
    if not any(m in out for m in LOG_MARKERS):
        print("FAIL: router_a logs show no router output ([init]/[tx]/[rx]/...)")
        print("Hint: rebuild: docker compose up -d --build")
        return False
    print("OK: router_a logs show DV activity")
    return True


def ring5_converged() -> bool:
    try:
        for r in ROUTERS_RING5:
            table = ip_route_on(r)
            for s in SUBNETS_RING5:
                if not has_subnet_route(table, s):
                    return False
        return True
    except RuntimeError:
        return False


def triangle_converged() -> bool:
    try:
        table = ip_route_on("router_a")
        return bool(
            route_line_for_subnet(table, "10.0.2.0/24")
            and (
                has_route_via(table, "10.0.2.0/24", "10.0.3.2")
                or has_route_via(table, "10.0.2.0/24", "10.0.1.2")
            )
        )
    except RuntimeError:
        return False


def wait_for_convergence(top: str, max_seconds: float, step: float = 5.0) -> tuple[bool, bool]:
    t0 = time.time()
    route_ok = False
    logs_ok = False
    while time.time() - t0 < max_seconds:
        code, out, _ = _run(["docker", "logs", "--tail", "400", "router_a"], timeout=30)
        if code == 0 and any(m in out for m in LOG_MARKERS):
            logs_ok = True
        if top == "ring5":
            route_ok = ring5_converged()
        else:
            route_ok = triangle_converged()
        if route_ok and logs_ok:
            print(f"OK: convergence after ~{int(time.time() - t0)}s (route + logs)")
            return True, True
        elapsed = int(time.time() - t0)
        print(f"... waiting ({elapsed}s / {int(max_seconds)}s) route={route_ok} logs={logs_ok}")
        time.sleep(step)
    return route_ok, logs_ok


def test_failover_triangle() -> bool:
    print("Stopping router_c for failover check ...")
    code, _, err = _run(["docker", "stop", "router_c"], timeout=60)
    if code != 0:
        print("FAIL: docker stop router_c:", err)
        return False
    wait = 25
    print(f"Waiting {wait}s for neighbor timeout / reconvergence ...")
    time.sleep(wait)
    table = ip_route_on("router_a")
    print("--- router_a ip route after stop (snippet) ---")
    for line in table.splitlines()[:12]:
        print(line)
    if not has_route_via(table, "10.0.2.0/24", "10.0.1.2"):
        print("FAIL: expected 10.0.2.0/24 via 10.0.1.2 on router_a after C stopped")
        print("docker start router_c   # to restore lab")
        return False
    print("OK: 10.0.2.0/24 reachable via 10.0.1.2 after C stopped")
    print("Restore with: docker start router_c")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--compose",
        action="store_true",
        help="Run docker compose up -d --build before tests",
    )
    ap.add_argument(
        "--auto",
        action="store_true",
        help="Start the stack, wait, then run checks",
    )
    ap.add_argument(
        "--wait",
        type=float,
        default=90.0,
        help="Max seconds to poll for routes + logs (default 90)",
    )
    ap.add_argument(
        "--topology",
        choices=("auto", "triangle", "ring5"),
        default="auto",
        help="Which checks to run (default: auto-detect from running containers)",
    )
    ap.add_argument(
        "--failover",
        action="store_true",
        help="Triangle only: stop router_c and check backup path",
    )
    args = ap.parse_args()

    if args.auto:
        args.compose = True

    if not docker_ok():
        return 1

    if args.compose:
        if not compose_up():
            return 1

    top = args.topology
    if top == "auto":
        top = detect_topology()
        print(f"Detected topology: {top}")

    if not containers_running(top):
        return 1

    print(f"Polling up to {args.wait}s for DV convergence on router_a ...")
    wait_for_convergence(top, max_seconds=args.wait, step=5.0)

    ok = True
    ok = test_logs_activity() and ok
    if top == "ring5":
        ok = test_converged_ring5() and ok
    else:
        ok = test_converged_triangle() and ok

    if args.failover:
        if top == "ring5":
            print("SKIP: --failover is only defined for the three-router triangle topology.")
        else:
            ok = test_failover_triangle() and ok

    if ok:
        print("\nALL CHECKS PASSED")
        return 0
    print("\nSOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
