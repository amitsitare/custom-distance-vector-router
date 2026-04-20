#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

MY_IP = os.getenv("MY_IP", "127.0.0.1")

_raw_neighbors = os.getenv("NEIGHBORS", "")
NEIGHBORS = [n.strip() for n in _raw_neighbors.split(",") if n.strip()]

_raw_local = os.getenv("LOCAL_SUBNETS", "")
LOCAL_SUBNETS = [s.strip() for s in _raw_local.split(",") if s.strip()]

PORT = int(os.getenv("PORT", "5000"))
BROADCAST_INTERVAL = float(os.getenv("BROADCAST_INTERVAL", "5"))
NEIGHBOR_TIMEOUT = float(os.getenv("NEIGHBOR_TIMEOUT", str(BROADCAST_INTERVAL * 3)))

PROTOCOL_VERSION = 1.0

SELF = "0.0.0.0"

routing_table = {}
_table_lock = threading.Lock()

last_heard: Dict[str, Optional[float]] = {}


def _subnet_from_ip(ip: str) -> str:
    parts = ip.split(".")
    if len(parts) != 4:
        raise ValueError(f"Bad IP for subnet derivation: {ip}")
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


def initialize_routing_table() -> None:
    global routing_table
    subnets = LOCAL_SUBNETS[:] if LOCAL_SUBNETS else [_subnet_from_ip(MY_IP)]
    routing_table = {s: [0, SELF] for s in subnets}
    for n in NEIGHBORS:
        last_heard[n] = None


def _run_ip(args: List[str]) -> None:
    try:
        subprocess.run(["ip", *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _install_route(subnet: str, next_hop: str) -> None:
    if next_hop == SELF:
        return
    _run_ip(["route", "replace", subnet, "via", next_hop])


def _remove_route(subnet: str, next_hop: str) -> None:
    if next_hop == SELF:
        return
    _run_ip(["route", "del", subnet, "via", next_hop])


def purge_routes_via(neighbor: str) -> None:
    to_delete = []
    with _table_lock:
        for subnet, (dist, nh) in list(routing_table.items()):
            if nh == neighbor and dist > 0:
                to_delete.append((subnet, nh))
        for subnet, nh in to_delete:
            del routing_table[subnet]
            print(f"[purge] dropped {subnet} via dead neighbor {nh}")
    for subnet, nh in to_delete:
        _remove_route(subnet, nh)


def check_neighbor_timeouts(now: float) -> None:
    for n in NEIGHBORS:
        t = last_heard.get(n)
        if t is None:
            continue
        if now - t > NEIGHBOR_TIMEOUT:
            print(f"[timeout] neighbor {n} silent > {NEIGHBOR_TIMEOUT}s — flushing routes via {n}")
            purge_routes_via(n)
            last_heard[n] = None


def update_logic(neighbor_ip: str, routes_from_neighbor: List[dict]) -> None:
    if neighbor_ip not in NEIGHBORS:
        print(f"[warn] update from non-neighbor {neighbor_ip}, processing anyway")

    last_heard[neighbor_ip] = time.time()

    changes: List[Tuple[str, str, int, str, Optional[str]]] = []
    with _table_lock:
        for entry in routes_from_neighbor:
            subnet = entry["subnet"]
            their_dist = int(entry["distance"])
            candidate = their_dist + 1

            if subnet in routing_table and routing_table[subnet][1] == SELF:
                continue

            if subnet not in routing_table:
                routing_table[subnet] = [candidate, neighbor_ip]
                changes.append(("add", subnet, candidate, neighbor_ip, None))
                continue

            cur_dist, cur_nh = routing_table[subnet]

            if cur_nh == neighbor_ip:
                if candidate != cur_dist:
                    routing_table[subnet] = [candidate, neighbor_ip]
                    changes.append(("chg", subnet, candidate, neighbor_ip, cur_nh))
            elif candidate < cur_dist:
                old_nh = cur_nh
                routing_table[subnet] = [candidate, neighbor_ip]
                changes.append(("better", subnet, candidate, neighbor_ip, old_nh))

    for kind, subnet, dist, nh, old_nh in changes:
        print(f"[bf] {kind} {subnet} -> cost {dist} nh {nh}")
        if old_nh is not None and old_nh != nh and old_nh != SELF:
            _remove_route(subnet, old_nh)
        _install_route(subnet, nh)


def build_packet_for_neighbor(neighbor_ip: str) -> dict:
    routes = []
    with _table_lock:
        for subnet, (dist, nh) in routing_table.items():
            if nh == neighbor_ip:
                continue
            routes.append({"subnet": subnet, "distance": dist})
    return {
        "router_id": MY_IP,
        "version": PROTOCOL_VERSION,
        "routes": routes,
    }


def broadcast_updates() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        now = time.time()
        check_neighbor_timeouts(now)

        for neighbor in NEIGHBORS:
            packet = build_packet_for_neighbor(neighbor)
            payload = json.dumps(packet).encode("utf-8")
            try:
                sock.sendto(payload, (neighbor, PORT))
            except OSError as e:
                print(f"[send] error to {neighbor}: {e}")

        with _table_lock:
            tbl = dict(routing_table)
        print(f"[tx] table {tbl}")
        time.sleep(BROADCAST_INTERVAL)


def listen_for_updates() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))

    print(f"[rx] listening on 0.0.0.0:{PORT} (router_id={MY_IP})")
    while True:
        data, addr = sock.recvfrom(65535)
        try:
            packet = json.loads(data.decode("utf-8"))
            if float(packet.get("version", 0)) != PROTOCOL_VERSION:
                print(f"[rx] bad version from {addr}")
                continue
            neighbor_ip = packet["router_id"]
            routes = packet["routes"]
            print(f"[rx] from {neighbor_ip} ({addr}) routes={routes}")
            update_logic(neighbor_ip, routes)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[rx] bad packet from {addr}: {e}")


def main() -> None:
    initialize_routing_table()
    print(f"[init] MY_IP={MY_IP} NEIGHBORS={NEIGHBORS} LOCAL_SUBNETS={list(routing_table.keys())}")

    threading.Thread(target=broadcast_updates, daemon=True).start()
    listen_for_updates()


if __name__ == "__main__":
    main()
