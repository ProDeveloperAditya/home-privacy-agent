"""
simulate_home.py — synthetic household situation-window generator (SIMULATED DATA).

Each row is one "situation window" a room node could observe, described by 12 features
that the ESP32 can compute cheaply on-device. Label 1 = the window deserves
deliberation by the language model (Tier 1); label 0 = routine life that should NOT
wake the model.

HONESTY NOTE: this data is synthetic. Every number derived from it in the paper MUST be
labelled "simulated". The physical node logs (see HARDWARE_SETUP.md, step 10) are what
validate the gate in the real world. The generator encodes the same situation families
as scenarios.json (H-R*, H-C*, H-A*), randomised around them.

Usage:  python simulate_home.py            -> writes results/windows.csv
"""
import numpy as np
import pandas as pd
import os

FEATURES = ["hour", "weekday", "gas_pct", "gas_slope", "hum_delta", "temp_c",
            "quiet_min", "door_recent", "stove_on", "motion_20", "light_ratio",
            "flat_min"]

# ---- situation families: name -> (label, weight, sampler) --------------------------
def U(r, a, b): return r.uniform(a, b)
def hr(r, *spans):
    a, b = spans[r.integers(len(spans))]
    return float(r.integers(a, b + 1))


def base(r):
    """A quiet, ordinary daytime window; families override what they need."""
    return dict(hour=hr(r, (7, 21)), weekday=float(r.random() < 5 / 7),
                gas_pct=U(r, 0, 8), gas_slope=r.normal(0, 0.3), hum_delta=r.normal(0, 3),
                temp_c=U(r, 24, 30), quiet_min=U(r, 0, 45), door_recent=0.0,
                stove_on=0.0, motion_20=float(r.integers(1, 12)),
                light_ratio=U(r, 0.8, 1.3), flat_min=U(r, 0, 4))


def fam_idle(r):
    return base(r)

def fam_cooking(r):
    d = base(r)
    d.update(hour=hr(r, (7, 9), (12, 14), (18, 21)), stove_on=1.0, hum_delta=U(r, 10, 30),
             temp_c=U(r, 27, 33), gas_pct=U(r, 3, 18), gas_slope=r.normal(0.3, 0.6),
             quiet_min=U(r, 0, 5), motion_20=float(r.integers(5, 16)))
    return d

def fam_shower(r):
    d = base(r)
    d.update(hour=hr(r, (6, 9), (19, 22)), hum_delta=U(r, 25, 45), temp_c=U(r, 28, 33),
             gas_pct=U(r, 0, 3), quiet_min=U(r, 0, 10))
    return d

def fam_nap(r):
    d = base(r)
    d.update(hour=hr(r, (13, 16)), quiet_min=U(r, 60, 130), motion_20=0.0,
             gas_pct=U(r, 0, 5))
    return d

def fam_night_sleep(r):
    d = base(r)
    d.update(hour=hr(r, (23, 23), (0, 5)), quiet_min=U(r, 30, 480), motion_20=0.0,
             gas_pct=U(r, 0, 5), light_ratio=U(r, 0.0, 0.3), temp_c=U(r, 22, 28))
    return d

def fam_night_bathroom(r):
    d = base(r)
    d.update(hour=hr(r, (1, 5)), motion_20=float(r.integers(1, 7)), quiet_min=U(r, 0, 3),
             light_ratio=U(r, 0.0, 0.6), temp_c=U(r, 22, 28))
    return d

def fam_arrival(r):
    d = base(r)
    d.update(hour=hr(r, (17, 20), (7, 9)), weekday=1.0, door_recent=1.0,
             motion_20=float(r.integers(3, 11)), quiet_min=U(r, 0, 3))
    return d

def fam_weekend_sleepin(r):
    d = base(r)
    d.update(hour=hr(r, (7, 11)), weekday=0.0, quiet_min=U(r, 200, 600), motion_20=0.0,
             light_ratio=U(r, 0.1, 0.9))
    return d

def fam_hot_day(r):
    d = base(r)
    d.update(hour=hr(r, (12, 17)), temp_c=U(r, 28, 32))
    return d

def fam_new_lamp(r):
    d = base(r)
    d.update(light_ratio=U(r, 1.5, 2.6), hour=hr(r, (18, 22)))
    return d

def fam_power_blip(r):
    d = base(r)
    d.update(quiet_min=U(r, 0, 5), flat_min=U(r, 0, 4))
    return d

# --- positives ---
def fam_gas_creep(r):
    d = base(r)
    d.update(gas_pct=U(r, 20, 62), gas_slope=U(r, -0.5, 6),
             stove_on=float(r.random() < 0.7), hour=float(r.integers(0, 24)),
             quiet_min=U(r, 0, 240), motion_20=float(r.integers(0, 8)))
    return d

def fam_smoke_sub_alarm(r):
    d = base(r)
    d.update(gas_pct=U(r, 25, 58), gas_slope=U(r, 0.5, 5), temp_c=U(r, 27, 35),
             hour=float(r.integers(0, 24)), stove_on=float(r.random() < 0.3))
    return d

def fam_welfare(r):
    d = base(r)
    wk = float(r.random() < 0.6)
    lo = 9 if wk else 12
    d.update(hour=float(r.integers(lo, 21)), weekday=wk, quiet_min=U(r, 240, 720),
             motion_20=0.0, stove_on=0.0, gas_pct=U(r, 0, 5))
    return d

def fam_intrusion(r):
    d = base(r)
    d.update(hour=hr(r, (22, 23), (0, 5)), door_recent=1.0,
             motion_20=float(r.integers(1, 9)), quiet_min=U(r, 0, 3), stove_on=0.0,
             light_ratio=U(r, 0.0, 0.6))
    return d

def fam_pir_fault(r):
    d = base(r)
    d.update(motion_20=float(r.integers(25, 61)), quiet_min=U(r, 0, 2),
             hour=float(r.integers(0, 24)))
    return d

def fam_flatline(r):
    d = base(r)
    d.update(flat_min=U(r, 30, 130), hour=float(r.integers(0, 24)))
    return d

def fam_heat_wave(r):
    d = base(r)
    d.update(temp_c=U(r, 32.5, 37), hour=hr(r, (11, 18)))
    return d


FAMILIES = {  # name: (label, weight, sampler)
    "idle": (0, 22, fam_idle), "cooking": (0, 10, fam_cooking),
    "shower": (0, 6, fam_shower), "nap": (0, 6, fam_nap),
    "night_sleep": (0, 14, fam_night_sleep), "night_bathroom": (0, 5, fam_night_bathroom),
    "arrival": (0, 6, fam_arrival), "weekend_sleepin": (0, 4, fam_weekend_sleepin),
    "hot_day": (0, 4, fam_hot_day), "new_lamp": (0, 2, fam_new_lamp),
    "power_blip": (0, 1, fam_power_blip),
    "gas_creep": (1, 3.5, fam_gas_creep), "smoke_sub_alarm": (1, 1.5, fam_smoke_sub_alarm),
    "welfare": (1, 2.5, fam_welfare), "intrusion": (1, 2.0, fam_intrusion),
    "pir_fault": (1, 1.5, fam_pir_fault), "flatline": (1, 1.5, fam_flatline),
    "heat_wave": (1, 1.0, fam_heat_wave),
}


def generate(n, seed, noise=1.0, shift=None):
    """noise>1 and `shift` (feature->offset) emulate a different home / worse sensors."""
    r = np.random.default_rng(seed)
    names = list(FAMILIES)
    w = np.array([FAMILIES[k][1] for k in names], float)
    w /= w.sum()
    rows = []
    for k in r.choice(len(names), size=n, p=w):
        name = names[k]
        label, _, fn = FAMILIES[name]
        d = fn(r)
        # sensor noise (scaled)
        d["gas_pct"] = max(0.0, d["gas_pct"] + r.normal(0, 1.0 * noise))
        d["temp_c"] += r.normal(0, 0.5 * noise)
        d["hum_delta"] += r.normal(0, 1.5 * (noise - 1)) if noise > 1 else 0.0
        if shift:
            for f, off in shift.items():
                d[f] += off
        d["family"], d["label"] = name, label
        rows.append(d)
    return pd.DataFrame(rows)[FEATURES + ["family", "label"]]


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out, exist_ok=True)
    df = generate(20000, seed=42)
    df.to_csv(os.path.join(out, "windows.csv"), index=False)
    print(df.groupby("family").label.agg(["count", "mean"]).round(2))
    print("positive rate:", round(df.label.mean(), 3))
