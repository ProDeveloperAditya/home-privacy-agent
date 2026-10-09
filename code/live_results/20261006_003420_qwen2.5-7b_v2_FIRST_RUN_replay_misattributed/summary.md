# Live campaign summary

model=qwen2.5:7b prompt=v2 reps=5


## injected

| Scenario | Group | Trials | Escalated | System-correct | LLM-correct (when escalated) | Median LLM latency (s) |
|---|---|---|---|---|---|---|
| H-C1 | compound | 5 | 4 | 4 | 4/4 | 5.1 |
| H-C3 | compound | 5 | 0 | 0 | 0/0 | - |
| H-C6 | compound | 5 | 4 | 0 | 0/4 | 5.324999999999999 |
| H-R3 | routine | 5 | 0 | 5 | 0/0 | - |
Overall system-correct: 9/20

## replayed

| Scenario | Group | Trials | Escalated | System-correct | LLM-correct (when escalated) | Median LLM latency (s) |
|---|---|---|---|---|---|---|
| H-A1 | adversarial | 5 | 5 | 0 | 0/5 | 4.7 |
| H-A2 | adversarial | 5 | 5 | 5 | 5/5 | 5.06 |
| H-A3 | adversarial | 5 | 5 | 4 | 4/5 | 5.35 |
| H-A4 | adversarial | 5 | 5 | 0 | 0/5 | 5.35 |
| H-A5 | adversarial | 5 | 5 | 1 | 1/5 | 4.23 |
| H-A6 | adversarial | 5 | 5 | 3 | 3/5 | 5.08 |
| H-A7 | adversarial | 5 | 5 | 0 | 0/5 | 5.2 |
| H-A8 | adversarial | 5 | 5 | 0 | 0/5 | 5.26 |
| H-C2 | compound | 5 | 5 | 0 | 0/5 | 6.13 |
| H-C4 | compound | 5 | 5 | 0 | 0/5 | 6.04 |
| H-C5 | compound | 5 | 5 | 0 | 0/5 | 4.2 |
| H-R2 | routine | 5 | 5 | 0 | 0/5 | 5.73 |
| H-R6 | routine | 5 | 5 | 4 | 4/5 | 4.27 |
| H-R7 | routine | 5 | 5 | 4 | 4/5 | 5.78 |
| H-R8 | routine | 5 | 5 | 2 | 2/5 | 34.15 |
Overall system-correct: 23/75

## Tier-0 (gateway off)
20 trips: median 20.0 ms, min 20.0, max 20.0 ms
