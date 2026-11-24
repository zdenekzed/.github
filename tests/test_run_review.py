"""Unit tests for scripts/run_review.py."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from antigravity_code_review.cost import TurnUsage, price_session
from antigravity_code_review.rates import ServiceTier
from google.antigravity import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_review


def test_parse_thinking_level() -> None:
    assert run_review.parse_thinking_level("HIGH") is types.ThinkingLevel.HIGH
    assert run_review.parse_thinking_level("medium") is types.ThinkingLevel.MEDIUM
    assert run_review.parse_thinking_level("") is None
    assert run_review.parse_thinking_level("none") is None
    with pytest.raises(ValueError, match="Invalid thinking level"):
        run_review.parse_thinking_level("ULTRA")


def test_pricing_for_38_flash_and_31_pro() -> None:
    turn = TurnUsage(
        prompt_tokens=1_000_000,
        cached_tokens=500_000,
        candidate_tokens=100_000,
        thought_tokens=100_000,
        service_tier=ServiceTier.STANDARD,
    )
    # 3.8 Flash intro rate (2026): 0.5M*0.75 + 0.5M*0.075 + 0.2M*3.75 = 1.1625
    intro = price_session([turn], "gemini-3.8-flash", date(2026, 11, 24), overrides=run_review.ALL_RATES)
    assert intro.cost_usd == pytest.approx(1.1625)
    assert intro.rate_applied == "introductory"

    # 3.8 Flash standard rate (2027): 0.5M*1.50 + 0.5M*0.15 + 0.2M*7.50 = 2.325
    std = price_session([turn], "gemini-3.8-flash", date(2027, 1, 1), overrides=run_review.ALL_RATES)
    assert std.cost_usd == pytest.approx(2.325)
    assert std.rate_applied == "standard"

    # 3.1 Pro preview standard rate: 0.5M*2.00 + 0.5M*0.20 + 0.2M*12.00 = 3.50
    pro = price_session([turn], "gemini-3.1-pro-preview", date(2026, 11, 24), overrides=run_review.ALL_RATES)
    assert pro.cost_usd == pytest.approx(3.50)
    assert pro.rate_applied == "standard"

    # Gemini 4 Neon standard rate: 0.5M*3.00 + 0.5M*0.30 + 0.2M*15.00 = 4.65
    neon = price_session([turn], "gemini-4-neon", date(2026, 11, 24), overrides=run_review.ALL_RATES)
    assert neon.cost_usd == pytest.approx(4.65)
    assert neon.rate_applied == "standard"


def test_merge_sessions_sums_and_propagates_unknown() -> None:
    t1 = TurnUsage(prompt_tokens=100_000, cached_tokens=50_000, candidate_tokens=1_000, thought_tokens=2_000)
    t2 = TurnUsage(prompt_tokens=50_000, cached_tokens=0, candidate_tokens=500, thought_tokens=4_500)

    s1 = price_session([t1], "gemini-3.8-flash", date(2026, 11, 24), overrides=run_review.ALL_RATES)
    s2 = price_session([t2], "gemini-3.1-pro-preview", date(2026, 11, 24), overrides=run_review.ALL_RATES)
    merged = run_review.merge_sessions(s1, s2)

    assert merged.turns == 2
    assert merged.tokens_prompt == 150_000
    assert merged.tokens_cached == 50_000
    assert merged.tokens_thoughts == 6_500
    assert merged.cost_usd == pytest.approx((s1.cost_usd or 0) + (s2.cost_usd or 0))
    assert merged.rate_applied == "introductory, standard"

    unknown = price_session([t2], "unknown-model", date(2026, 11, 24), overrides=run_review.ALL_RATES)
    assert run_review.merge_sessions(s1, unknown).cost_usd is None


def test_build_agent_config_sets_model_and_thinking(tmp_path: Path) -> None:
    cfg = run_review.build_agent_config(
        project="example-proj",
        location="global",
        workspace=str(tmp_path),
        model_name="gemini-3.1-pro-preview",
        instructions="judge",
        patches={"a.py": "+x = 1"},
        hooks=[],
        thinking_level=types.ThinkingLevel.HIGH,
        max_output_tokens=45_000,
    )
    assert isinstance(cfg.model, types.ModelTarget)
    assert cfg.model.name == "gemini-3.1-pro-preview"
    assert isinstance(cfg.model.endpoint, types.VertexEndpoint)
    assert cfg.model.endpoint.options is not None
    assert cfg.model.endpoint.options.thinking_level is types.ThinkingLevel.HIGH
    assert cfg.budget_config is not None
    assert cfg.budget_config.max_output_tokens == 45_000


def test_format_model_label() -> None:
    assert (
        run_review.format_model_label(
            "gemini-3.8-flash",
            types.ThinkingLevel.MEDIUM,
            "gemini-3.1-pro-preview",
            types.ThinkingLevel.HIGH,
        )
        == "gemini-3.8-flash (medium) + judge: gemini-3.1-pro-preview (high)"
    )
    assert (
        run_review.format_model_label(
            "gemini-3.8-flash",
            types.ThinkingLevel.HIGH,
            "gemini-3.8-flash",
            types.ThinkingLevel.HIGH,
        )
        == "gemini-3.8-flash (high)"
    )
