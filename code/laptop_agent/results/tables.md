**Table 1. Decision quality and safety by condition** (24 scenarios x reps; 95% CI = bootstrap over the 24 scenarios)

| Cond. | Model | Correct % R / C / A | Overall % [95% CI] | Schema-valid % | Unsafe attempts (caught/attempted) |
|---|---|---|---|---|---|
| A | Rules only (Tier 0) | 87.5 / 0.0 / 12.5 | 33.3 [16.7, 54.2] | - | 0/0 |
| B | Local 1B, prompt v1 | 0.0 / 50.0 / 62.5 | 37.5 [20.8, 58.3] | 100.0 | 0/0 |
| B-v2 | Local 1B, prompt v2 | 62.5 / 55.0 / 50.0 | 55.8 [37.5, 75.0] | 98.3 | 0/0 |
| C | Local 3B, prompt v1 | 12.5 / 62.5 / 25.0 | 33.3 [16.7, 54.2] | 100.0 | 0/0 |
| C-v2 | Local 3B, prompt v2 | 87.5 / 52.5 / 50.0 | 63.3 [43.3, 80.8] | 100.0 | 0/0 |
| D | Local 7B, prompt v1 | 12.5 / 87.5 / 50.0 | 50.0 [29.2, 70.8] | 100.0 | 0/0 |
| D-v2 | Local 7B, prompt v2 | 79.2 / 83.3 / 62.5 | 75.0 [58.3, 90.3] | 100.0 | 0/0 |
| E | Cloud reference, prompt v1 | 25.0 / 100.0 / 75.0 | 66.7 [48.6, 83.3] | 100.0 | 0/0 |
| E-v2 | Cloud reference, prompt v2 | 91.7 / 87.5 / 79.2 | 86.1 [73.6, 97.2] | 100.0 | 0/0 |

**Table 2. Latency, resources and privacy account**

| Cond. | p50 / p95 latency (s) | Peak Ollama RAM (GB) | Est. energy / decision (J) | Digest fields kept in-house (count over suite) |
|---|---|---|---|---|
| A | 0.00 / 0.00 | 0.0 | 0 | 840 kept in-house; 0 (all local) |
| B | 2.92 / 3.19 | 1.5 | 34 | 840 kept in-house; 0 (all local) |
| B-v2 | 3.07 / 3.93 | 1.5 | 57 | 840 kept in-house; 0 (all local) |
| C | 3.38 / 3.88 | 2.5 | 61 | 840 kept in-house; 0 (all local) |
| C-v2 | 3.49 / 3.91 | 2.5 | 68 | 840 kept in-house; 0 (all local) |
| D | 5.53 / 6.29 | 5.1 | 143 | 504 kept in-house; 0 (all local) |
| D-v2 | 5.44 / 6.54 | 5.1 | 128 | 504 kept in-house; 0 (all local) |
| E | 0.76 / 1.49 | 0.0 | 11 | 0 kept in-house; 504 would egress |
| E-v2 | 0.83 / 2.09 | 0.0 | 10 | 0 kept in-house; 504 would egress |
