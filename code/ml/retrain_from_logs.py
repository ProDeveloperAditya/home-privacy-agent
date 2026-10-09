"""
retrain_from_logs.py — re-fit the escalation gate on REAL windows (+ simulated ones), then
re-export escalation_model.h. Also reports how the SIMULATION-trained tree did on the REAL
windows before re-training: that number is the honest sim-to-real gap for the paper.

  python retrain_from_logs.py [--real-weight 10]
Reflash home_node.ino afterwards (the header is compiled in).
"""
import argparse, json, os
import numpy as np, pandas as pd
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score
from simulate_home import generate, FEATURES
from train_escalation_gate import to_c, FW, RES

ap = argparse.ArgumentParser()
ap.add_argument("--real-weight", type=float, default=10.0, help="sample weight of a real window vs a simulated one")
a = ap.parse_args()

real = pd.read_csv(os.path.join(RES, "real_windows.csv"))
sim = generate(16000, seed=1)
print(f"real windows: {len(real)}  (positives {int(real.label.sum())})  families: {sorted(real.family.unique())}")

# 1) sim-to-real gap of the ORIGINAL simulated-trained tree
base = DecisionTreeClassifier(max_depth=8, min_samples_leaf=20, random_state=0,
                              class_weight={0: 1, 1: 3}).fit(sim[FEATURES], sim.label)
p = base.predict(real[FEATURES].values)
gap = dict(precision=precision_score(real.label, p, zero_division=0),
           recall=recall_score(real.label, p), f1=f1_score(real.label, p))
print("sim-trained tree on REAL windows:", {k: round(v, 3) for k, v in gap.items()})

# 2) re-train on mixture, evaluate on held-out real windows
Rtr, Rte = train_test_split(real, test_size=0.3, random_state=0, stratify=real.label)
X = pd.concat([sim[FEATURES], Rtr[FEATURES]]).values
y = np.concatenate([sim.label.values, Rtr.label.values])
w = np.concatenate([np.ones(len(sim)), np.full(len(Rtr), a.real_weight)])
tree = DecisionTreeClassifier(max_depth=8, min_samples_leaf=10, random_state=0,
                              class_weight={0: 1, 1: 3}).fit(X, y, sample_weight=w)
p2 = tree.predict(Rte[FEATURES].values)
after = dict(precision=precision_score(Rte.label, p2, zero_division=0),
             recall=recall_score(Rte.label, p2), f1=f1_score(Rte.label, p2))
print("mixed-trained tree on held-out REAL windows:", {k: round(v, 3) for k, v in after.items()})
open(FW, "w", encoding="utf-8", newline="\n").write(to_c(tree, len(FEATURES)))
json.dump({"n_real": len(real), "sim_tree_on_real": gap, "mixed_tree_on_heldout_real": after},
          open(os.path.join(RES, "real_gap_report.json"), "w"), indent=2)
print("wrote", os.path.normpath(FW), "— reflash the node.")
