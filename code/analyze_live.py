"""
[SUPERSEDED by run_live_campaign.py, which automates marking, scoring and logging. Kept for manual use.]
analyze_live.py — score the LIVE hardware campaign (physical scenarios) from the gateway log.

Workflow (see HARDWARE_SETUP.md step 10):
  1. gateway_agent.py is running and appending to transcripts.jsonl
  2. Before each physical trial:      python analyze_live.py mark H-C1
  3. Perform the physical recipe (e.g. puff unlit lighter gas at the MQ-2)
  4. After all trials:                python analyze_live.py score
Each trial is matched to the FIRST escalation the gateway handled after its mark (and before
the next mark). No escalation within --timeout seconds = "no_escalation" (a gate miss!).
"""
import argparse, csv, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
TRIALS = os.path.join(HERE, "live_trials.csv")
LOG = os.path.join(HERE, "transcripts.jsonl")
SCEN = {s["id"]: s for s in json.load(open(os.path.join(HERE, "laptop_agent", "scenarios.json"),
                                            encoding="utf-8"))}
ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["mark", "score"])
ap.add_argument("scenario", nargs="?")
ap.add_argument("--timeout", type=float, default=240)
a = ap.parse_args()

if a.cmd == "mark":
    if a.scenario not in SCEN:
        sys.exit("unknown scenario; valid: " + ", ".join(SCEN))
    new = not os.path.exists(TRIALS)
    with open(TRIALS, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["scenario", "start_epoch"])
        w.writerow([a.scenario, time.time()])
    print("marked", a.scenario, "— go perform it now")
    sys.exit()

trials = list(csv.DictReader(open(TRIALS)))
recs = [json.loads(l) for l in open(LOG, encoding="utf-8")] if os.path.exists(LOG) else []
res = {}
for i, tr in enumerate(trials):
    t0 = float(tr["start_epoch"])
    t1 = min(t0 + a.timeout, float(trials[i + 1]["start_epoch"]) if i + 1 < len(trials) else 9e18)
    hit = next((r for r in recs if t0 <= r["t"] < t1), None)
    exp = SCEN[tr["scenario"]]["expected_tool"]
    got = hit["action"].get("tool") if hit else "no_escalation"
    d = res.setdefault(tr["scenario"], dict(n=0, ok=0, esc=0, lat=[]))
    d["n"] += 1; d["ok"] += got == exp; d["esc"] += hit is not None
    if hit: d["lat"].append(hit["latency_s"])
    print(f"{tr['scenario']} trial {d['n']}: expected {exp}, got {got}")
print("\nscenario  trials  escalated  correct  median_latency_s")
tot = ok = esc = 0
for s, d in sorted(res.items()):
    lat = sorted(d["lat"])
    print(f"{s:8s} {d['n']:6d} {d['esc']:10d} {d['ok']:8d}  {lat[len(lat)//2] if lat else '-'}")
    tot += d["n"]; ok += d["ok"]; esc += d["esc"]
if tot:
    print(f"\nOVERALL: {ok}/{tot} correct ({100*ok/tot:.1f}%), gate escalated {esc}/{tot} trials")
