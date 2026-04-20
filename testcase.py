from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
ROUTERS = ("router_a", "router_b", "router_c")
LOG_MARKERS = ("[init]", "[tx]", "[rx]", "[bf]", "[warn]", "[send]", "[purge]", "[timeout]")


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


def docker_ok() -> bool:
    code, out, err = _run(["docker", "version", "-f", "{{.Server.Version}}"], timeout=15)
    if code != 0:
        print("FAIL: docker CLI not working:", err or out)
        return False
    return True


def containers_running() -> bool:
    code, out, err = _run(["docker", "ps", "--format", "{{.Names}}"], timeout=30)
    if code != 0:
        print("FAIL: docker ps:", err)
        return False
    names = {line.strip() for line in out.splitlines() if line.strip()}
    missing = [n for n in ROUTERS if n not in names]
    if missing:
        print("FAIL: containers not running:", ", ".join(missing))
        print("Hint: docker compose up -d --build")
        return False
    print("OK: routers running:", ", ".join(ROUTERS))
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


def compose_up() -> bool:
    print("Starting stack: docker compose up -d --build ...")
    code, out, err = _run(["docker", "compose", "up", "-d", "--build"], timeout=300)
    if code != 0:
        print("FAIL: docker compose:", err or out)
        return False
    print("OK: compose up finished")
    return True


def test_converged_primary() -> bool:
    table = ip_route_on("router_a")
    print("--- router_a ip route (snippet) ---")
    for line in table.splitlines()[:12]:
        print(line)
    line = route_line_for_subnet(table, "10.0.2.0/24")
    if not line:
        print("FAIL: no kernel route to 10.0.2.0/24 on router_a")
        return False
    if has_route_via(table, "10.0.2.0/24", "10.0.3.2"):
        print("OK: 10.0.2.0/24 via 10.0.3.2 (Net_AC / assignment-style path)")
        return True
    if has_route_via(table, "10.0.2.0/24", "10.0.1.2"):
        print("OK: 10.0.2.0/24 via 10.0.1.2 (same metric tie; both are 1 hop from A)")
        return True
    print("FAIL: unexpected next hop for 10.0.2.0/24:", line)
    return False


def test_logs_activity() -> bool:
    code, out, err = _run(["docker", "logs", "--tail", "400", "router_a"], timeout=30)
    if code != 0:
        print("FAIL: docker logs router_a:", err)
        return False
    if not any(m in out for m in LOG_MARKERS):
        print("FAIL: router_a logs show no router output ([init]/[tx]/[rx]/...)")
        print("Hint: rebuild image after Dockerfile sets PYTHONUNBUFFERED: docker compose up -d --build")
        return False
    print("OK: router_a logs show DV activity")
    return True


def wait_for_convergence(max_seconds: float, step: float = 5.0) -> tuple[bool, bool]:
    t0 = time.time()
    route_ok = False
    logs_ok = False
    while time.time() - t0 < max_seconds:
        code, out, _ = _run(["docker", "logs", "--tail", "400", "router_a"], timeout=30)
        if code == 0 and any(m in out for m in LOG_MARKERS):
            logs_ok = True
        try:
            table = ip_route_on("router_a")
            if route_line_for_subnet(table, "10.0.2.0/24") and (
                has_route_via(table, "10.0.2.0/24", "10.0.3.2")
                or has_route_via(table, "10.0.2.0/24", "10.0.1.2")
            ):
                route_ok = True
        except RuntimeError:
            pass
        if route_ok and logs_ok:
            print(f"OK: convergence after ~{int(time.time() - t0)}s (route + logs)")
            return True, True
        elapsed = int(time.time() - t0)
        print(f"... waiting ({elapsed}s / {int(max_seconds)}s) route={route_ok} logs={logs_ok}")
        time.sleep(step)
    return route_ok, logs_ok


def test_failover_path() -> bool:
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
        help="Same as --compose: start the stack, wait, then run checks (no separate .bat needed)",
    )
    ap.add_argument(
        "--wait",
        type=float,
        default=90.0,
        help="Max seconds to poll for routes + logs (default 90)",
    )
    ap.add_argument(
        "--failover",
        action="store_true",
        help="Also stop router_c and check alternate path (leaves C stopped unless you start it)",
    )
    args = ap.parse_args()

    if args.auto:
        args.compose = True

    if not docker_ok():
        return 1

    if args.compose:
        if not compose_up():
            return 1

    if not containers_running():
        return 1

    print(f"Polling up to {args.wait}s for DV logs and 10.0.2.0/24 on router_a ...")
    wait_for_convergence(max_seconds=args.wait, step=5.0)

    ok = True
    ok = test_logs_activity() and ok
    ok = test_converged_primary() and ok

    if args.failover:
        ok = test_failover_path() and ok

    if ok:
        print("\nALL CHECKS PASSED")
        return 0
    print("\nSOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
