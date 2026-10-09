"""
capture_features.py — record REAL labelled situation windows from a running node.

The firmware prints one "[FEAT],<node>,f0..f11" line per minute. This tool listens on the
node's USB serial port and appends each line to results/real_windows.csv with a label you
choose for the whole session, e.g. while you cook: --family cooking --label 0
                              while you puff unlit lighter gas: --family gas_creep --label 1
Then run retrain_from_logs.py.   pip install pyserial

  python capture_features.py --port COM5 --family cooking --label 0 --minutes 20
"""
import argparse, csv, os, time
import serial

FEATURES = ["hour", "weekday", "gas_pct", "gas_slope", "hum_delta", "temp_c",
            "quiet_min", "door_recent", "stove_on", "motion_20", "light_ratio", "flat_min"]
ap = argparse.ArgumentParser()
ap.add_argument("--port", required=True)
ap.add_argument("--family", required=True)
ap.add_argument("--label", type=int, choices=[0, 1], required=True,
                help="1 = should wake the LLM, 0 = routine")
ap.add_argument("--minutes", type=float, default=10)
ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results", "real_windows.csv"))
a = ap.parse_args()

new = not os.path.exists(a.out)
os.makedirs(os.path.dirname(a.out), exist_ok=True)
end, n = time.time() + a.minutes * 60, 0
with serial.Serial(a.port, 115200, timeout=2) as s, open(a.out, "a", newline="") as f:
    w = csv.writer(f)
    if new:
        w.writerow(FEATURES + ["family", "label"])
    while time.time() < end:
        line = s.readline().decode(errors="ignore").strip()
        if line.startswith("[FEAT]"):
            parts = line.split(",")[2:]
            if len(parts) == len(FEATURES):
                w.writerow(parts + [a.family, a.label]); f.flush(); n += 1
                print(f"captured window {n}: {line}")
print(f"saved {n} windows to {a.out}")
