# Escalation gate — SIMULATED-data results

## iid_test

| Method | Precision | Recall | F1 | Escalation rate |
|---|---|---|---|---|
| H_heuristic | 0.7464 | 0.5598 | 0.6398 | 0.1144 |
| T_tree | 0.9638 | 0.9811 | 0.9724 | 0.1552 |
| T+_tree_or_gasband | 0.9638 | 0.9811 | 0.9724 | 0.1552 |
| IF_isolation_forest | 0.5921 | 0.382 | 0.4644 | 0.0984 |

LLM calls avoided vs escalate-everything: 84.5%

## shifted_test

| Method | Precision | Recall | F1 | Escalation rate |
|---|---|---|---|---|
| H_heuristic | 0.7101 | 0.5217 | 0.6015 | 0.1056 |
| T_tree | 0.7576 | 0.9757 | 0.8529 | 0.1851 |
| T+_tree_or_gasband | 0.7576 | 0.9757 | 0.8529 | 0.1851 |
| IF_isolation_forest | 0.4538 | 0.4017 | 0.4262 | 0.1273 |

LLM calls avoided vs escalate-everything: 81.5%
