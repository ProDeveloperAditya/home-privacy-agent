"""
paired_stats.py — paired comparisons between conditions, bootstrapped over the 24 scenarios.

All conditions run the SAME scenarios, so the right test of "is X better than Y" is on the
per-scenario difference in fraction-correct (not on two overlapping marginal intervals).
Writes results/paired.md.   python paired_stats.py
"""
import csv, os
from collections import defaultdict
import numpy as np

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
FILES = {"A": "out_A.csv", "B": "out_1b.csv", "B-v2": "out_1b_v2.csv", "C": "out_3b.csv",
         "C-v2": "out_3b_v2.csv", "D": "out_7b.csv", "D-v2": "out_7b_v2.csv", "E": "out_E.csv", "E-v2": "out_E_v2.csv"}
PAIRS = [("B-v2", "B"), ("C-v2", "C"), ("D-v2", "D"),            # effect of the prompt
         ("C", "B"), ("D", "C"), ("C-v2", "B-v2"), ("D-v2", "C-v2"),   # effect of scale
         ("B-v2", "A"), ("C-v2", "A"), ("D-v2", "A"),
         ("E-v2", "E"), ("E-v2", "D-v2"), ("E", "D"), ("E-v2", "A")]     # cloud reference            # vs rules only


def per_scenario(cid):
    by = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(RES, FILES[cid]), encoding="utf-8")):
        by[r["scenario"]].append(r["got_tool"] == r["expected_tool"])
    return {k: float(np.mean(v)) for k, v in by.items()}


P = {c: per_scenario(c) for c in FILES if os.path.exists(os.path.join(RES, FILES[c]))}
rng = np.random.default_rng(0)
lines = ["| Comparison (X vs Y) | Mean diff, points [95% CI] | X better on / Y better on / tie (scenarios) |", "|---|---|---|"]
for x, y in PAIRS:
    if x not in P or y not in P:
        continue
    ids = sorted(P[x])
    d = np.array([P[x][i] - P[y][i] for i in ids])
    boots = rng.choice(d, size=(4000, len(d)), replace=True).mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    lines.append(f"| {x} vs {y} | {100*d.mean():+.1f} [{100*lo:+.1f}, {100*hi:+.1f}] | "
                 f"{(d>0).sum()} / {(d<0).sum()} / {(d==0).sum()} |")
out = "**Table 6. Paired differences in correctness (bootstrap over 24 scenarios)**\n\n" + "\n".join(lines) + "\n"
open(os.path.join(RES, "paired.md"), "w", encoding="utf-8").write(out)
print(out)
