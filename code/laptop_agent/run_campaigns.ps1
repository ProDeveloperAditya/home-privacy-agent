# run_campaigns.ps1 — reproduce every evaluation condition, then build tables/figures/paired stats.
#   .\run_campaigns.ps1                 # A + local models 1B/3B/7B, prompts v1 and v2, dev + test
#   .\run_campaigns.ps1 -Cloud          # also condition E (needs $env:GROQ_API_KEY, free key at console.groq.com)
# Prereqs: Ollama running, models pulled ONE AT A TIME (parallel pulls of the same model stall):
#   ollama pull llama3.2:1b ; ollama pull llama3.2:3b ; ollama pull qwen2.5:7b
# Runtime on an i7-13620H: ~1 h 45 min total. Keep the laptop on mains power and otherwise idle.
# (What was actually run for the paper: 5 reps for 1B/3B, 3 reps for 7B, dev reps = 3.)
param([switch]$Cloud, [int]$Reps = 5, [int]$Reps7B = 3, [string]$CloudModel = "openai/gpt-oss-120b")
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force results | Out-Null
$env:PYTHONIOENCODING = "utf-8"

python test_agent.py run --model rules --out results/out_A.csv --reps $Reps

function Campaign($tag, $short, $reps, [switch]$cloud) {
    $extra = @(); if ($cloud) { $extra += "--cloud" }
    foreach ($pv in @("v1", "v2")) {                       # dev set first: it is what prompt v2 was tuned on
        python test_agent.py run --model $tag --prompt $pv --scenarios scenarios_dev.json `
            --out "results/dev_${short}_$pv.csv" --reps 3 --json-mode @extra
    }
    foreach ($pv in @("v1", "v2")) {
        $suffix = if ($pv -eq "v1") { "" } else { "_v2" }
        python test_agent.py run --model $tag --prompt $pv `
            --out "results/out_${short}${suffix}.csv" --reps $reps --json-mode @extra
        python test_agent.py score "results/out_${short}${suffix}.csv"
    }
}
Campaign "llama3.2:1b" "1b" $Reps
Campaign "llama3.2:3b" "3b" $Reps
Campaign "qwen2.5:7b"  "7b" $Reps7B
if ($Cloud) { Campaign $CloudModel "E" 3 -cloud }   # 3 reps: free-tier rate limits

python make_tables.py
python paired_stats.py
Write-Host "Done. Then from the project root:  python fill_paper_tables.py ; python build_paper_docx.py"
