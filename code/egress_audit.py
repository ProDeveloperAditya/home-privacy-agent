"""
egress_audit.py — software check of the zero-egress claim on the GATEWAY machine.

Watches every TCP/UDP socket owned by the home-agent processes (ollama, mosquitto, python)
and flags any connection whose remote address is NOT loopback/private/multicast.
This is the cheap first check; the paper's evidence is the Wireshark capture at the
router (HARDWARE_SETUP.md step 8), which also covers the ESP32 nodes.

  python egress_audit.py --minutes 30 --out results/egress_log.csv
Exit code 1 if any public-IP connection was seen (so it can gate a demo script).

NOTE: Ollama may contact the internet for update checks / model pulls. For the audit,
pull all models first, turn off Ollama auto-update in its tray settings, then run this
while the system operates. Any hit is data: identify the process, then decide.
"""
import argparse, csv, ipaddress, sys, time
import psutil

WATCH = ("ollama", "mosquitto", "python", "node")

ap = argparse.ArgumentParser()
ap.add_argument("--minutes", type=float, default=5)
ap.add_argument("--out", default="results/egress_log.csv")
a = ap.parse_args()


def is_local(ip):
    try:
        x = ipaddress.ip_address(ip)
        return x.is_private or x.is_loopback or x.is_multicast or x.is_link_local or x.is_unspecified
    except ValueError:
        return True


seen, hits = set(), 0
end = time.time() + a.minutes * 60
with open(a.out, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["time", "process", "pid", "remote_ip", "remote_port", "status"])
    while time.time() < end:
        for conn in psutil.net_connections(kind="inet"):
            if not conn.raddr or not conn.pid:
                continue
            try:
                name = psutil.Process(conn.pid).name().lower()
            except psutil.Error:
                continue
            if not any(k in name for k in WATCH):
                continue
            key = (name, conn.raddr.ip, conn.raddr.port)
            if not is_local(conn.raddr.ip) and key not in seen:
                seen.add(key); hits += 1
                w.writerow([time.strftime("%T"), name, conn.pid, conn.raddr.ip,
                            conn.raddr.port, conn.status]); f.flush()
                print("PUBLIC CONNECTION:", key)
        time.sleep(1)
print(f"audit done: {hits} public-IP connection(s) from watched processes in {a.minutes} min")
sys.exit(1 if hits else 0)
