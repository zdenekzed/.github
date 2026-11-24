"""Two-tier AI PR reviewer wrapper on top of doitintl/antigravity-code-review.

Runs the four contract audit passes on Gemini 4 Hydrogen
(default: gemini-4-hydrogen, thinking_level=LOW) and delegates the final
DEFECT vs INTENDED ruling to Gemini 4 Neon (default: gemini-4-neon,
thinking_level=HIGH). Tracks per-stage token usage and prices each stage
against its own published Vertex AI rate table.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from antigravity_code_review.collect_usage import UsageCollector
from antigravity_code_review.collector import format_file_line
from antigravity_code_review.config import (
    CONTRACT_PASSES,
    JUDGE_INSTRUCTIONS,
    LOCATION,
    PASS_INSTRUCTIONS,
    REVIEW_TOOLS,
)
from antigravity_code_review.cost import PricedSession, price_session
from antigravity_code_review.evalharness.runs import RunOutcome, classify
from antigravity_code_review.github import (
    get_pull_request,
    list_changed_files,
    post_review,
)
from antigravity_code_review.guards import is_fork
from antigravity_code_review.rates import RATES, Rate, ServiceTier
from antigravity_code_review.report import cost_artifact, cost_line, review_body
from antigravity_code_review.review import is_trivial, parse_findings
from antigravity_code_review.tools import make_view_diff, view_file
from google.antigravity import Agent, LocalAgentConfig, types

DEFAULT_PASS_MODEL = "gemini-4-hydrogen"
DEFAULT_JUDGE_MODEL = "gemini-4-neon"
DEFAULT_PASS_THINKING = "LOW"
DEFAULT_JUDGE_THINKING = "HIGH"

VERTEX_PRICING_SOURCE = "https://cloud.google.com/vertex-ai/generative-ai/pricing"
RATES_VERIFIED_ON = "2026-11-24"
_INTRO_ENDS = date(2026, 12, 31)


def _rate(inp: float, cached: float, out: float, until: date | None) -> Rate:
    return Rate(
        input_per_m=inp,
        cached_input_per_m=cached,
        output_per_m=out,
        effective_until=until,
        source=VERTEX_PRICING_SOURCE,
        verified_on=RATES_VERIFIED_ON,
    )


# Published Vertex AI global endpoint rates extending upstream's table.
ALL_RATES: dict[str, dict[ServiceTier, list[Rate]]] = {
    **RATES,
    "gemini-3.8-flash": {
        ServiceTier.STANDARD: [
            _rate(0.75, 0.075, 3.75, _INTRO_ENDS),
            _rate(1.50, 0.15, 7.50, None),
        ],
        ServiceTier.PRIORITY: [
            _rate(1.35, 0.135, 6.75, _INTRO_ENDS),
            _rate(2.70, 0.27, 13.50, None),
        ],
        ServiceTier.FLEX: [
            _rate(0.375, 0.0375, 1.875, _INTRO_ENDS),
            _rate(0.75, 0.075, 3.75, None),
        ],
    },
    "gemini-4-hydrogen": {
        # Published Vertex AI global endpoint rates (5% implicit cache read: $0.075/1M).
        ServiceTier.STANDARD: [
            _rate(1.50, 0.075, 7.50, None),
        ],
        ServiceTier.FLEX: [
            _rate(0.75, 0.0375, 3.75, None),
        ],
    },
    "gemini-4-neon": {
        # Published Vertex AI global endpoint paid rates (GA Nov 2026).
        ServiceTier.STANDARD: [
            _rate(3.00, 0.30, 15.00, None),
        ],
        ServiceTier.FLEX: [
            _rate(1.50, 0.15, 7.50, None),
        ],
    },
    "gemini-3.1-pro-preview": {
        # Standard <=200k prompt context rates on Vertex AI global endpoint.
        ServiceTier.STANDARD: [
            _rate(2.00, 0.20, 12.00, None),
        ],
        ServiceTier.FLEX: [
            _rate(1.00, 0.10, 6.00, None),
        ],
    },
}


def parse_thinking_level(raw: str | None) -> types.ThinkingLevel | None:
    """Parse an optional ThinkingLevel name (case-insensitive)."""
    if raw is None or not raw.strip() or raw.strip().lower() == "none":
        return None
    key = raw.strip().upper()
    try:
        return types.ThinkingLevel[key]
    except KeyError as exc:
        valid = ", ".join(m.name for m in types.ThinkingLevel)
        raise ValueError(f"Invalid thinking level {raw!r}; expected one of: {valid}") from exc


def build_agent_config(
    *,
    project: str,
    location: str,
    workspace: str,
    model_name: str,
    instructions: str,
    patches: dict[str, str],
    hooks: list[Any],
    thinking_level: types.ThinkingLevel | None = None,
    max_output_tokens: int = 30_000,
) -> LocalAgentConfig:
    """Build a read-only LocalAgentConfig targeting a specific Vertex model and thinking level."""
    options = (
        types.GeminiModelOptions(thinking_level=thinking_level)
        if thinking_level is not None
        else None
    )
    model = types.ModelTarget(
        name=model_name,
        endpoint=types.VertexEndpoint(
            project=project,
            location=location,
            options=options,
        ),
    )

    return LocalAgentConfig(
        vertex=True,
        project=project,
        location=location,
        model=model,
        system_instructions=instructions,
        tools=[view_file, make_view_diff(patches)],
        hooks=hooks,
        capabilities=types.CapabilitiesConfig(
            enabled_tools=list(REVIEW_TOOLS),
            enable_subagents=False,
            agent_behavior=types.AgentBehavior.AUTONOMOUS,
            compaction_threshold=300_000,
        ),
        workspaces=[workspace],
        app_data_dir=tempfile.mkdtemp(prefix="agy-review-", dir=tempfile.gettempdir()),
        budget_config=types.BudgetConfig(
            max_input_tokens=900_000,
            max_output_tokens=max_output_tokens,
            max_tool_calls=80,
        ),
        retry_config=types.RetryConfig(
            model_output_retry=types.ModelOutputRetryConfig(max_retries=1)
        ),
    )


def merge_sessions(*sessions: PricedSession) -> PricedSession:
    """Combine multiple PricedSession totals while preserving unknown-cost propagation."""
    active = [s for s in sessions if s.turns > 0]
    if not active:
        return PricedSession(
            turns=0,
            tokens_prompt=0,
            tokens_cached=0,
            tokens_candidates=0,
            tokens_thoughts=0,
            tokens_total=0,
            cost_usd=0.0,
            rate_applied=None,
            service_tiers={},
        )

    unknown = any(s.cost_usd is None for s in active)
    total_cost = None if unknown else sum(s.cost_usd or 0.0 for s in active)

    labels: list[str] = []
    tiers: Counter[str] = Counter()
    for s in active:
        if s.rate_applied:
            for part in s.rate_applied.split(","):
                cleaned = part.strip()
                if cleaned and cleaned not in labels:
                    labels.append(cleaned)
        tiers.update(s.service_tiers)

    return PricedSession(
        turns=sum(s.turns for s in active),
        tokens_prompt=sum(s.tokens_prompt for s in active),
        tokens_cached=sum(s.tokens_cached for s in active),
        tokens_candidates=sum(s.tokens_candidates for s in active),
        tokens_thoughts=sum(s.tokens_thoughts for s in active),
        tokens_total=sum(s.tokens_total for s in active),
        cost_usd=total_cost,
        rate_applied=", ".join(sorted(labels)) or None,
        service_tiers=dict(tiers),
    )


def format_model_label(
    pass_model: str,
    pass_thinking: types.ThinkingLevel | None,
    judge_model: str,
    judge_thinking: types.ThinkingLevel | None,
) -> str:
    """Format a compact model description for the PR review table."""
    p_lvl = f" ({pass_thinking.name.lower()})" if pass_thinking else ""
    j_lvl = f" ({judge_thinking.name.lower()})" if judge_thinking else ""
    if pass_model == judge_model and pass_thinking == judge_thinking:
        return f"{pass_model}{p_lvl}"
    return f"{pass_model}{p_lvl} + judge: {judge_model}{j_lvl}"


async def _run_turn(cfg: LocalAgentConfig, prompt: str, collector: UsageCollector) -> tuple[str, Any]:
    async with Agent(cfg) as agent:
        collector.bind(agent.conversation)
        response = await agent.chat(prompt)
        text = (await response.text()).strip()
        collector.record_cumulative(agent.conversation.total_usage)
    return text, response.stop_reason


async def run_two_tier_passes(
    *,
    project: str,
    location: str,
    workspace: str,
    patches: dict[str, str],
    listing: str,
    subject: str,
    pass_collector: UsageCollector,
    judge_collector: UsageCollector,
    pass_model: str = DEFAULT_PASS_MODEL,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    pass_thinking: types.ThinkingLevel | None = types.ThinkingLevel.LOW,
    judge_thinking: types.ThinkingLevel | None = types.ThinkingLevel.HIGH,
    passes: Sequence[tuple[str, str]] = CONTRACT_PASSES,
) -> tuple[list[dict[str, Any]], list[RunOutcome]]:
    """Run audit passes on pass_model and the ruling judge on judge_model."""
    reports: list[str] = []
    outcomes: list[RunOutcome] = []

    for name, question in passes:
        print(f"[pass] {name} ({pass_model}, thinking={pass_thinking.name if pass_thinking else 'default'})")
        cfg = build_agent_config(
            project=project,
            location=location,
            workspace=workspace,
            model_name=pass_model,
            instructions=PASS_INSTRUCTIONS,
            patches=patches,
            hooks=pass_collector.hooks(),
            thinking_level=pass_thinking,
            max_output_tokens=35_000,
        )
        prompt = f"{subject}:\n{listing}\n\nYOUR AUDIT QUESTION:\n{question}\n"
        try:
            text, stop = await _run_turn(cfg, prompt, pass_collector)
        except Exception as exc:  # noqa: BLE001 - a failed pass must not drop the others
            print(f"   FAILED: {type(exc).__name__}: {exc}")
            outcomes.append(classify(None, error=f"{type(exc).__name__}: {exc}", stage=name))
            continue

        outcome = classify(stop, text=text, stage=name)
        outcomes.append(outcome)
        if outcome.incomplete and not text:
            print(f"   INCOMPLETE — {outcome.reason}")
            continue
        print(f"   {len(text)} chars")
        reports.append(f"### {name}\n{text}")

    findings: list[dict[str, Any]] = []
    if reports:
        print(
            f"[judge] deciding defects ({judge_model}, "
            f"thinking={judge_thinking.name if judge_thinking else 'default'})"
        )
        cfg = build_agent_config(
            project=project,
            location=location,
            workspace=workspace,
            model_name=judge_model,
            instructions=JUDGE_INSTRUCTIONS,
            patches=patches,
            hooks=judge_collector.hooks(),
            thinking_level=judge_thinking,
            max_output_tokens=45_000,
        )
        joined = "AUDIT REPORT:\n\n" + "\n\n".join(reports)[:200_000]
        try:
            text, stop = await _run_turn(cfg, joined, judge_collector)
            findings = parse_findings(text)
            outcomes.append(classify(stop, text=text, findings=len(findings), stage="judge"))
            print(f"   {len(findings)} defect(s)")
        except Exception as exc:  # noqa: BLE001 - losing the judge must not lose the cost record
            print(f"   FAILED: {type(exc).__name__}: {exc}")
            outcomes.append(classify(None, error=f"{type(exc).__name__}: {exc}", stage="judge"))

    return findings, outcomes


async def review(
    repo: str,
    number: int,
    project: str,
    *,
    location: str = LOCATION,
    pass_model: str = DEFAULT_PASS_MODEL,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    pass_thinking: types.ThinkingLevel | None = types.ThinkingLevel.LOW,
    judge_thinking: types.ThinkingLevel | None = types.ThinkingLevel.HIGH,
) -> int:
    """Review one pull request and publish findings plus cost artifact."""
    pr = get_pull_request(repo, number)
    if is_fork(pr):
        print(f"SKIPPED: #{number} comes from a fork; no identity federation is available.")
        return 0

    files = list_changed_files(repo, number)
    skip = is_trivial(files)
    if skip:
        print(f"SKIPPED: {skip}. No review posted.")
        return 0

    patches = {f["filename"]: f["patch"] for f in files if f.get("patch")}
    listing = "\n".join(format_file_line(f) for f in files)
    print(f"collected {len(files)} changed files, diffs for {len(patches)}")

    workspace = os.getcwd()
    os.environ.setdefault("AGY_WORKSPACE", workspace)
    pass_collector = UsageCollector()
    judge_collector = UsageCollector()

    findings, outcomes = await run_two_tier_passes(
        project=project,
        location=location,
        workspace=workspace,
        patches=patches,
        listing=listing,
        subject=f"Pull request #{number} changes {len(files)} files",
        pass_collector=pass_collector,
        judge_collector=judge_collector,
        pass_model=pass_model,
        judge_model=judge_model,
        pass_thinking=pass_thinking,
        judge_thinking=judge_thinking,
    )
    incomplete = [o.stage or "stage" for o in outcomes if o.incomplete]

    today = datetime.now(tz=UTC).date()
    pass_priced = price_session(pass_collector.turns, pass_model, today, overrides=ALL_RATES)
    judge_priced = price_session(judge_collector.turns, judge_model, today, overrides=ALL_RATES)
    combined = merge_sessions(pass_priced, judge_priced)

    total_tool_calls = pass_collector.tool_calls + judge_collector.tool_calls
    total_compactions = pass_collector.compactions + judge_collector.compactions
    model_label = format_model_label(pass_model, pass_thinking, judge_model, judge_thinking)

    print(cost_line(combined, tool_calls=total_tool_calls))

    body = review_body(
        combined,
        tool_calls=total_tool_calls,
        model=model_label,
        findings=len(findings),
        stop_reason=f"{len(incomplete)} incomplete pass(es): {', '.join(incomplete)}"
        if incomplete
        else None,
    )
    posted = post_review(repo, number, findings, body)
    print(f"posted review with {posted} inline comment(s)")

    artifact = cost_artifact(
        combined,
        repo=repo,
        pr=number,
        model=model_label,
        tool_calls=total_tool_calls,
        compactions=total_compactions,
        retries={"api": 0, "model_output": 0},
    )
    artifact["stages"] = {
        "passes": {
            "model": pass_model,
            "thinking_level": pass_thinking.name if pass_thinking else None,
            "turns": pass_priced.turns,
            "tool_calls": pass_collector.tool_calls,
            "cost_usd": pass_priced.cost_usd,
        },
        "judge": {
            "model": judge_model,
            "thinking_level": judge_thinking.name if judge_thinking else None,
            "turns": judge_priced.turns,
            "tool_calls": judge_collector.tool_calls,
            "cost_usd": judge_priced.cost_usd,
        },
    }
    artifact["findings"] = findings
    artifact["incomplete_passes"] = incomplete
    Path("review-cost.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print("wrote review-cost.json")
    return 0


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY")
    number = os.environ.get("PR_NUMBER")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    missing = [
        n
        for n, v in (
            ("GITHUB_REPOSITORY", repo),
            ("PR_NUMBER", number),
            ("GOOGLE_CLOUD_PROJECT", project),
        )
        if not v
    ]
    if missing:
        raise SystemExit(f"FAIL: missing environment: {', '.join(missing)}")
    assert repo and number and project

    location = os.environ.get("GOOGLE_CLOUD_LOCATION", LOCATION)
    pass_model = os.environ.get("REVIEW_PASS_MODEL", DEFAULT_PASS_MODEL).strip() or DEFAULT_PASS_MODEL
    judge_model = os.environ.get("REVIEW_JUDGE_MODEL", DEFAULT_JUDGE_MODEL).strip() or DEFAULT_JUDGE_MODEL
    pass_thinking = parse_thinking_level(os.environ.get("REVIEW_PASS_THINKING", DEFAULT_PASS_THINKING))
    judge_thinking = parse_thinking_level(os.environ.get("REVIEW_JUDGE_THINKING", DEFAULT_JUDGE_THINKING))

    return asyncio.run(
        review(
            repo,
            int(number),
            project,
            location=location,
            pass_model=pass_model,
            judge_model=judge_model,
            pass_thinking=pass_thinking,
            judge_thinking=judge_thinking,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
