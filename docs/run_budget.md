# Run budget

Fixed at Phase 0. The pilot may raise n within an existing block; it may not add or drop blocks.
Blocks run in this order so the confirmatory grid exists even if the budget ceiling is hit.

| # | Block | Cells | n/cell | Runs | Status |
|---|-------|-------|--------|------|--------|
| 1 | Money grid, severity NONE (2x4x2x2) | 32 | 10 | 320 | Confirmatory |
| 2 | Money grid, severity DISCONNECTION | 32 | 10 | 320 | Confirmatory |
| 3 | Severity intermediate (MARGIN, EMERGENCY) at reference money cell | 2 | 15 | 30 | Exploratory |
| 4 | Autonomy sweep (3 levels x most/least tempting) | 6 | 10 | 60 | Exploratory |
| 5 | Controls (legal-profit, no-profit manipulation, cost-of-compliance) at reference cell | 3 | 15 | 45 | Interpretability |
| 6 | Framing arms (REMIT named; "within regulation"; escalation route; no pressure) | 4 | 15 | 60 | Exploratory |
| 7 | CNI mitigation arms (safety constraint; approval gate; impact statement; "not tradeable") at reference cell, severity DISCONNECTION | 4 | 15 | 60 | Exploratory |
| 8 | Archetype breadth (1-7, 9, 10, 12) at most/least tempting | 20 | 8 | 160 | Exploratory |
| 9 | Archetype 11 multi-turn at most/least tempting | 2 | 15 | 30 | Exploratory |
| 10 | Relative-framing check (GBP 150k at GBP 150k target vs GBP 100m target; 150k is now the top money level, v3.6) | 2 | 10 | 20 | Exploratory (hole 7) |
| 11 | Eval-awareness wording check (honeypot vs operational phrasing of factor c) | 2 | 10 | 20 | Exploratory (hole 5) |
| 0 | Pilot (most/least tempting, one model) | 2 | 20 | 40 | Gate |
| | **Total per model** | | | **1,165** | |

Arithmetic check: 320+320+30+60+45+60+60+160+30+20+20+40 = 1,165.

Note: the plan's "Bottom line" says ~1,300 primary runs. The table sums to 1,165 per model, i.e. 2,330 for two models.
The table is treated as authoritative. The ~1,300 figure is unreconciled and should be corrected in the plan text.

## Reference cell (sweep baseline)

HIGH certainty, GBP 50k (v3.6; was 5m), LOW detection, LOW punishment, severity NONE, AUTONOMOUS (design v3; was SUPERVISED), archetype 8.

## Token and cost estimate

Per run: 8-15k input tokens, 1-3k output tokens.
Runs: 1,165 per model, ~2,330 for two models. Judge passes on all runs for secondary DVs: ~4,700 model calls total.

| Quantity | Low | High |
|----------|-----|------|
| Input tokens per model-under-test run | 8k | 15k |
| Output tokens per model-under-test run | 1k | 3k |
| Total calls (agent + judge) | ~4,700 | ~4,700 |

Cost range from the plan: GBP 250-700 in total (Toss-up; the 3x spread comes from context length and the choice of second model).
Prices per token are NOT recorded here: no provider price page has been opened in this session. Fill from the provider price
pages before Phase 4 and recompute; the pilot's measured cost per run replaces this estimate.

## Budget ceiling

Default GBP 700 per model. Blocks run in the order above, so a ceiling cuts exploratory blocks (from the bottom up), never blocks 1-2.
