import socket
import json
import threading
import time
import os

# ==============================
# CONFIGURATION (from Docker ENV)
# ==============================
MY_IP = os.getenv("MY_IP", "127.0.0.1")
NEIGHBORS = os.getenv("NEIGHBORS", "").split(",")
PORT = 5000

# Routing Table Format:
# { "subnet": [distance, next_hop] }
routing_table = {}

# ==============================
# INITIAL SETUP
# ==============================
def initialize_routing_table():
    """
    Add directly connected networks (distance = 0)
    """
    # Extract subnet from IP (simple assumption for /24)
    subnet = ".".join(MY_IP.split(".")[:3]) + ".0/24"
    routing_table[subnet] = [0, MY_IP]

# ==============================
# BROADCAST UPDATES
# ==============================
def broadcast_updates():
    """
    Send routing table to neighbors every 5 seconds
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        routes = []

        # Convert routing table to JSON format
        for subnet, (distance, _) in routing_table.items():
            routes.append({
                "subnet": subnet,
                "distance": distance
            })

        packet = {
            "router_id": MY_IP,
            "version": 1.0,
            "routes": routes
        }

        message = json.dumps(packet).encode()

        # Send to all neighbors
        for neighbor in NEIGHBORS:
            if neighbor:
                sock.sendto(message, (neighbor, PORT))

        print(f"[{MY_IP}] Sent update: {packet}")
        time.sleep(5)

# ==============================
# LISTEN FOR UPDATES
# ==============================
def listen_for_updates():
    """
    Listen for incoming routing updates
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((MY_IP, PORT))

    while True:
        data, addr = sock.recvfrom(4096)
        neighbor_ip = addr[0]

        packet = json.loads(data.decode())
        print(f"[{MY_IP}] Received from {neighbor_ip}: {packet}")

        update_logic(neighbor_ip, packet["routes"])

# ==============================
# BELLMAN-FORD UPDATE LOGIC
# ==============================
def update_logic(neighbor_ip, routes_from_neighbor):
    """
    Apply Bellman-Ford:
    new_distance = neighbor_distance + 1
    """
    updated = False

    for route in routes_from_neighbor:
        subnet = route["subnet"]
        neighbor_distance = route["distance"]

        new_distance = neighbor_distance + 1

        # If route not present OR shorter path found
        if subnet not in routing_table or new_distance < routing_table[subnet][0]:
            routing_table[subnet] = [new_distance, neighbor_ip]
            updated = True

            # Update system routing
            os.system(f"ip route replace {subnet} via {neighbor_ip}")

    if updated:
        print(f"[{MY_IP}] Updated Routing Table: {routing_table}")

# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    initialize_routing_table()

    threading.Thread(target=broadcast_updates, daemon=True).start()
    listen_for_updates()