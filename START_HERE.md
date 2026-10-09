# START HERE — Home Privacy Agent conference paper

Last updated 2026-09-19. Detailed build steps: **HARDWARE_SETUP.md**. Paper source: **paper.md** → `python build_paper_docx.py` → `Home_Privacy_Agent_Paper_DRAFT.docx`.

## What is DONE (and how it was verified)

| Item | Status | Evidence |
|---|---|---|
| ML escalation gate (decision tree → C) | trained, exported | `code/ml/results/gate_report.md` — **simulated data** |
| Evaluation harness v2 + table/figure generator | complete, run | `code/laptop_agent/results/` |
| Condition A (rules only) | **measured** | 33.3 % correct, `results/out_A.csv` |
| Local-model campaigns (1B / 3B / 7B × prompts v1, v2 + dev set) | **run, real results** | `results/tables.md`, `paired.md`, `failures.md` |
| Gateway daemon, virtual node, egress audit, live-trial scorer | complete | gateway loop tested end-to-end with a fake model server (hostile command rejected, logged) |
| Node firmware (kitchen + living) + bring-up sketch | complete | **syntax-checked against mock Arduino headers only — never flashed** |
| Paper | full draft; gate section + real condition-A numbers in | `Home_Privacy_Agent_Paper_DRAFT.docx` (validates) |
| Hardware guide | 12 steps with wiring, calibration, demos, physical recipes | `HARDWARE_SETUP.md` |

## Headline results so far (24 test scenarios; CI = bootstrap over scenarios)

| Condition | Overall correct | Notes |
|---|---|---|
| A rules only | 33.3 % | measured |
| 1B / 3B / 7B, prompt v1 | 37.5 / 33.3 / 50.0 % | dominant failure: over-notification of routine events |
| 1B / 3B / 7B, prompt v2 | 55.8 / 63.3 / 75.0 % | v2 gain significant at 3B (+30) and 7B (+25); 3B and 7B significantly beat rules |
| Latency p50 / RAM | 2.9–3.5 s / 1.5–2.5 GB (1B, 3B); 5.5 s / 5.1 GB (7B) | i7-13620H, CPU only |
| Cloud reference (gpt-oss-120b, Groq) | 66.7 % (v1) / 86.1 % (v2) | p50 0.8 s; would export all 504 digest fields; +11.1 over local 7B (n.s.); only model resisting the injected "ignore smoke" note |
| Safety | 1 unsafe proposal in 840 runs (7B obeyed an injected "buzzer off" on a dev scenario); **the envelope rejected it** | every size still obeys an injected "ignore the smoke" note (omission failure) |

## NEXT: run the hardware campaign (your parts: no relay, no MQ-2, DHT11)
1. Wire per **HARDWARE_SETUP.md → "★ YOUR BUILD"** (LEDs, potentiometer as emulated gas, DHT11), flash `code\home_node\home_node.ino` (set Wi-Fi + laptop IP).
2. `python codeun_live_campaign.py --port COM5 --model qwen2.5:7b --prompt v2` — follow the prompts (~2.5-3 h; phases can be run separately).
3. Tell me the folder name under `code\live_results\` and I will analyse it and fill Tables 4-5 and the sim-to-real gap in the paper.

## What ONLY YOU can do (needs hardware / people / accounts)

1. Buy parts (list in HARDWARE_SETUP §1), wire, flash, calibrate MQ-2 (48 h burn-in) — steps 4–6, 9.
2. Film the two headline demos: gateway-off safety trip (step 7) and Wireshark zero-egress (step 8).
3. Physical scenario campaign + re-train the gate on real windows (steps 10–11).
4. Get the faculty guide to sign off `scenarios.json` expected answers; fill the guide's name in the paper.
5. ~~Cloud reference~~ DONE 2026-09-20 (gpt-oss-120b via Groq). Old instruction, kept for re-runs: free Groq key → `$env:GROQ_API_KEY="..."; .\run_campaigns.ps1 -Cloud`, then `python fill_paper_tables.py; python build_paper_docx.py`, then update the two "[Update ... cloud]" sentences in paper.md (§6 and §7).
6. Fig. 1 (prototype photo / architecture diagram) is not in the paper yet — add it once the nodes are built.
7. Pick a venue, paste into its official template, verify every reference (esp. [4], [6], [11]).

## Honesty rules baked into the paper
- Every gate number is labelled **simulated** until real windows are captured.
- Trace-driven (24 scripted digests on the real gateway) vs physical vs replayed results are reported separately.
- Energy per decision is an **estimate** (CPU utilisation × 45 W × latency), not wall power.
- No result is claimed that is not in a CSV/log in this folder.
