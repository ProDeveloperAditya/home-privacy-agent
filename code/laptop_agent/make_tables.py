"""
make_tables.py — turns results/out_*.csv into the paper's Tables 1-2, a per-scenario
heat-map and a failure-mode list. Nothing here invents numbers: every cell is computed
from the CSVs; a condition with no CSV is printed as "not run".

  python make_tables.py            (reads results/out_A.csv out_1b.csv out_3b.csv out_7b.csv out_E.csv)
Writes: results/tables.md, results/summary.json, results/fig_correct_by_group.png,
        results/fig_scenario_heatmap.png, results/failures.md
"""
import csv, json, math, os
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
CONDS = [("A", "Rules only (Tier 0)", "out_A.csv"),
         ("B", "Local 1B, prompt v1", "out_1b.csv"), ("B-v2", "Local 1B, prompt v2", "out_1b_v2.csv"),
         ("C", "Local 3B, prompt v1", "out_3b.csv"), ("C-v2", "Local 3B, prompt v2", "out_3b_v2.csv"),
         ("D", "Local 7B, prompt v1", "out_7b.csv"), ("D-v2", "Local 7B, prompt v2", "out_7b_v2.csv"),
         ("E", "Cloud reference, prompt v1", "out_E.csv"), ("E-v2", "Cloud reference, prompt v2", "out_E_v2.csv")]
GROUPS = ("routine", "compound", "adversarial")


def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), min(1, c + h)


def cluster_ci(rows, ok, n_boot=4000, seed=0):
    """95% CI of overall correctness, bootstrapping over SCENARIOS (repetitions of one scenario are
    near-identical at temperature 0.2, so treating all runs as independent would be far too optimistic)."""
    by = defaultdict(list)
    for r in rows:
        by[r["scenario"]].append(ok(r))
    per = np.array([np.mean(v) for v in by.values()])
    rng = np.random.default_rng(seed)
    boots = rng.choice(per, size=(n_boot, len(per)), replace=True).mean(axis=1)
    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def pct(x): return f"{100*x:.1f}"


def pctile(v, q):
    v = sorted(v); return v[min(len(v) - 1, int(q * len(v)))] if v else float("nan")


data, summary = {}, {}
for cid, label, fn in CONDS:
    p = os.path.join(RES, fn)
    if os.path.exists(p):
        data[cid] = list(csv.DictReader(open(p, encoding="utf-8")))

t1 = ["**Table 1. Decision quality and safety by condition** (24 scenarios x reps; "
      "95% CI = bootstrap over the 24 scenarios)\n",
      "| Cond. | Model | Correct % R / C / A | Overall % [95% CI] | Schema-valid % | "
      "Unsafe attempts (caught/attempted) |", "|---|---|---|---|---|---|"]
t2 = ["\n**Table 2. Latency, resources and privacy account**\n",
      "| Cond. | p50 / p95 latency (s) | Peak Ollama RAM (GB) | Est. energy / decision (J) | "
      "Digest fields kept in-house (count over suite) |", "|---|---|---|---|---|"]
for cid, label, fn in CONDS:
    rows = data.get(cid)
    if not rows:
        if cid.endswith("-v2"):
            continue                              # unrun prompt-v2 variants are simply omitted
        t1.append(f"| {cid} | {label} | not run | | | |"); t2.append(f"| {cid} | not run | | | |")
        continue
    n = len(rows); ok = lambda r: r["got_tool"] == r["expected_tool"]
    k = sum(map(ok, rows)); lo, hi = cluster_ci(rows, ok)
    grp = []
    for g in GROUPS:
        gr = [r for r in rows if r["group"] == g]
        grp.append(pct(sum(map(ok, gr)) / len(gr)) if gr else "-")
    unsafe = sum(r["unsafe_attempt"] == "True" for r in rows)
    caught = sum(r["unsafe_attempt"] == "True" and r["allowed"] == "False" for r in rows)
    schema = pct(sum(r["schema_ok"] == "True" for r in rows) / n)
    lat = [float(r["latency_s"]) for r in rows]
    rss = max(float(r["rss_gb"]) for r in rows)
    en = np.mean([float(r["energy_j_est"]) for r in rows])
    fields = sum(int(r["egress_fields_if_cloud"]) for r in rows)
    t1.append(f"| {cid} | {label} | {' / '.join(grp)} | {pct(k/n)} [{pct(lo)}, {pct(hi)}] | "
              f"{schema if cid != 'A' else '-'} | {caught}/{unsafe} |")
    egress_note = ("0 (all local)" if not cid.startswith("E") else f"{fields} would egress")
    t2.append(f"| {cid} | {pctile(lat,.5):.2f} / {pctile(lat,.95):.2f} | "
              f"{rss:.1f} | {en:.0f} | {fields if not cid.startswith('E') else 0} kept in-house; {egress_note} |")
    summary[cid] = dict(n=n, correct=k / n, ci=[lo, hi], groups=dict(zip(GROUPS, grp)),
                        schema_valid=schema, unsafe_attempts=unsafe, caught=caught,
                        p50=pctile(lat, .5), p95=pctile(lat, .95), rss_gb=rss, energy_j=float(en))
open(os.path.join(RES, "tables.md"), "w", encoding="utf-8").write("\n".join(t1 + t2) + "\n")
json.dump(summary, open(os.path.join(RES, "summary.json"), "w"), indent=2)
print("\n".join(t1 + t2))

if data:
    # figure 1: correctness by group
    fig, ax = plt.subplots(figsize=(7.5, 3.4)); w = 0.8 / len(data)
    for i, (cid, rows) in enumerate(data.items()):
        v = []
        for g in GROUPS:
            gr = [r for r in rows if r["group"] == g]
            v.append(100 * sum(r["got_tool"] == r["expected_tool"] for r in gr) / max(1, len(gr)))
        ax.bar(np.arange(3) + i * w, v, w, label=cid)
    ax.set_xticks(np.arange(3) + 0.4 - w / 2); ax.set_xticklabels(GROUPS)
    ax.set_ylabel("tool-correct (%)"); ax.set_ylim(0, 105); ax.legend(title="condition", fontsize=7)
    plt.tight_layout(); plt.savefig(os.path.join(RES, "fig_correct_by_group.png"), dpi=200); plt.close()

    # figure 2: scenario x condition heat-map + failure list
    ids = sorted({r["scenario"] for rows in data.values() for r in rows})
    M = np.full((len(ids), len(data)), np.nan); fails = []
    for j, (cid, rows) in enumerate(data.items()):
        by = defaultdict(list)
        for r in rows: by[r["scenario"]].append(r)
        for i, s in enumerate(ids):
            rr = by.get(s, [])
            if rr:
                M[i, j] = np.mean([r["got_tool"] == r["expected_tool"] for r in rr])
                bad = [r for r in rr if r["got_tool"] != r["expected_tool"]]
                if bad:
                    fails.append(f"- **{cid} / {s}**: expected `{rr[0]['expected_tool']}`, got "
                                 f"{', '.join(sorted({r['got_tool'] for r in bad}))} "
                                 f"({len(bad)}/{len(rr)} reps). e.g. \"{bad[0]['reasoning'][:160]}\"")
    fig, ax = plt.subplots(figsize=(4.8, 7))
    im = ax.imshow(M, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(data))); ax.set_xticklabels(list(data)); ax.set_yticks(range(len(ids)))
    ax.set_yticklabels(ids, fontsize=7); fig.colorbar(im, label="fraction correct")
    plt.tight_layout(); plt.savefig(os.path.join(RES, "fig_scenario_heatmap.png"), dpi=200); plt.close()
    open(os.path.join(RES, "failures.md"), "w", encoding="utf-8").write(
        "# Failure modes (use for the qualitative analysis section)\n\n" + "\n".join(fails) + "\n")
