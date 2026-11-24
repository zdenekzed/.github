# ADR-0002: Two-tier reviewer models (`gemini-3.8-flash` passes + `gemini-4-neon` high-thinking judge)

- **Status:** Accepted (updated 2026-11-24 after live A/B benchmark)
- **Date:** 2026-11-24

## Context

Upstream [`doitintl/antigravity-code-review`](https://github.com/doitintl/antigravity-code-review) (`8ef939d8`) hardcodes `gemini-3.7-flash` with default thinking level for both the four contract audit passes and the final ruling judge. Upstream's own M5 evaluation (PR #5, 24 runs) measured strong security recall (4/6) and moderate local recall (5/11), but weak cross-file recall (2/25) and noted `thinking_level=HIGH` remained untested.

Live probing of the Vertex AI `global` endpoint confirms `gemini-3.8-flash` (same introductory pricing as `gemini-3.7-flash` through 2026-12-31) and `gemini-4-neon` (GA Nov 18, 2026, `$3.00 / $15.00` per 1M tokens) are available and supported by `google-antigravity==0.1.12` via `types.ModelTarget` and `types.ThinkingLevel`. A live A/B run on a large PR showed `MEDIUM` thinking on all 4 audit passes took ~31 min and `$0.90` on passes alone while the high-thinking judge took only 9 tool calls and surfaced 3 real cross-file defects missed by `3.7-flash`.

## Decision

1. **Keep upstream un-forked:** Reuse `antigravity_code_review` modules (GitHub collector/poster, diff tools, contract prompts, usage hooks, cost report formatter) and wrap execution in `scripts/run_review.py` inside `zdenekzed/.github`.
2. **Two-tier model split with explicit thinking levels:**
   - **4 audit passes:** `gemini-3.8-flash` with `ThinkingLevel.LOW` (keeps evidence gathering fast and prevents budget/time blow-up on large diffs while retaining current Flash quality).
   - **Final judge ruling:** `gemini-4-neon` with `ThinkingLevel.HIGH` and `max_output_tokens=45_000` (flagship reasoning where all final DEFECT vs INTENDED decisions are made).
   - **Safety guardrail:** `timeout-minutes: 30` on the `review` job.
3. **Dual-stage cost accounting:** Track pass and judge token usage in separate `UsageCollector` instances, price each against its own published rate entry via `price_session(..., overrides=ALL_RATES)`, merge totals with unknown-cost propagation intact, and emit per-stage breakdown in `review-cost.json`.
4. **Central default, per-repo override:** Expose `pass_model`, `judge_model`, `pass_thinking_level`, and `judge_thinking_level` as optional `workflow_call` inputs in `.github/workflows/ai-code-review.yml` so all repositories upgrade automatically without touching caller workflows.

## Consequences

- Every repository calling `zdenekzed/.github/.github/workflows/ai-code-review.yml@main` immediately uses `gemini-3.8-flash (low)` + `gemini-4-neon (high)`.
- Lowering pass thinking from `MEDIUM` to `LOW` trims latency and pass token spend while upgrading the single judge turn to `gemini-4-neon` (`HIGH`).
- Any repository can override models/thinking levels per caller workflow if needed.
