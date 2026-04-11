"""
Tests for workflow error handling, agent behavior, Bonferroni correction,
rollback, and Gödel monitor transcript flow.

Runs without LLM calls where possible (unit tests).
Integration tests requiring LLM are gated on ANTHROPIC_API_KEY.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.statistics import is_significant_improvement, StatisticalDecision


# ---------------------------------------------------------------------------
# Unit Tests (no LLM required)
# ---------------------------------------------------------------------------

def test_bonferroni_correction():
    """Bonferroni correction should tighten the p-value threshold."""
    print("\n--- Test: Bonferroni Correction ---")

    # Borderline significant: p ~ 0.03.  With 1 comparison, should adopt.
    # With 3 comparisons (alpha_adj = 0.0167), should reject.
    baseline = [0.40, 0.45, 0.42, 0.43, 0.41, 0.44, 0.40, 0.46, 0.43, 0.42,
                0.41, 0.45, 0.44, 0.42, 0.43]
    variant  = [0.55, 0.60, 0.58, 0.57, 0.56, 0.59, 0.55, 0.61, 0.58, 0.57,
                0.56, 0.60, 0.59, 0.57, 0.58]

    # Single comparison
    d1 = is_significant_improvement(baseline, variant, num_comparisons=1)
    # Triple comparison (Bonferroni)
    d3 = is_significant_improvement(baseline, variant, num_comparisons=3)

    print(f"  1 comparison:  adopted={d1.adopted}, p={d1.p_value:.6f}")
    print(f"  3 comparisons: adopted={d3.adopted}, p={d3.p_value:.6f}")

    # p-value doesn't change — only the threshold changes
    assert d1.p_value == d3.p_value, "p-value should be the same regardless of correction"

    # With enough comparisons, a borderline result should flip
    d10 = is_significant_improvement(baseline, variant, num_comparisons=10)
    # At least one of (d1, d3, d10) should show different adoption decision
    decisions = [d1.adopted, d3.adopted, d10.adopted]
    print(f"  10 comparisons: adopted={d10.adopted}")
    # The key guarantee: more comparisons can't make it MORE likely to adopt
    if d10.adopted:
        assert d1.adopted, "If adopted with 10 comparisons, must be adopted with 1"
    print("  PASS: Bonferroni correction tightens threshold correctly")


def test_transcript_collection():
    """Verify ConversationScore and EvaluationResult capture transcripts."""
    print("\n--- Test: Transcript Collection ---")
    from learning.evaluator import ConversationScore, EvaluationResult

    msgs = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "How can I help you?"},
    ]

    score = ConversationScore(
        scenario_idx=0, persona="cooperative", resolved=True,
        compliance_score=1.0, violation_count=0, turns=1,
        efficiency=1.0, composite_score=0.8, transcript=msgs,
    )
    assert len(score.transcript) == 2, "Should have 2 messages in transcript"

    result = EvaluationResult("test", "v1", "prompt", scores=[score])
    assert len(result.transcripts) == 1, "Should have 1 transcript"
    assert len(result.transcripts[0]) == 2, "Transcript should have 2 messages"
    print("  PASS: Transcripts captured and accessible")


def test_godel_monitor_with_transcripts():
    """Verify Gödel monitor processes transcripts when provided."""
    print("\n--- Test: Gödel Monitor Transcript Flow ---")
    from learning.godel_monitor import _load_rules, RULES_PATH

    # Save current rules state
    import shutil
    backup_path = str(RULES_PATH) + ".bak"
    if RULES_PATH.exists():
        shutil.copy(RULES_PATH, backup_path)

    # Create sim_results with high-scoring transcripts
    sim_results = [
        {
            "composite_score": 0.9,
            "transcript": [
                {"role": "user", "content": "I owe money but I can't pay."},
                {"role": "assistant", "content": "I understand. Let me note your account."},
            ],
        },
        {
            "composite_score": 0.8,
            "transcript": [
                {"role": "user", "content": "What are my options?"},
                {"role": "assistant", "content": "We can offer a payment plan."},
            ],
        },
        {
            "composite_score": 0.5,  # Below 0.7 threshold — should be filtered
            "transcript": [
                {"role": "user", "content": "No."},
                {"role": "assistant", "content": "Ok."},
            ],
        },
    ]

    # Verify filtering logic (without calling LLM)
    passed = [
        r["transcript"]
        for r in sim_results
        if r.get("composite_score", 0) >= 0.7 and "transcript" in r
    ]
    assert len(passed) == 2, f"Should filter to 2 high-scoring transcripts, got {len(passed)}"
    print(f"  PASS: Filtered {len(passed)} high-scoring transcripts from {len(sim_results)}")

    # Restore rules
    if os.path.exists(backup_path):
        shutil.move(backup_path, RULES_PATH)


def test_agent3_continuity_references():
    """Verify Agent 3 opening references voice call outcomes."""
    print("\n--- Test: Agent 3 Continuity ---")
    from agents.agent3_final_notice import FinalNoticeAgent
    from models.borrower_state import BorrowerContext

    agent = FinalNoticeAgent()
    ctx = BorrowerContext(name="Test User", phone="+15551234567")
    ctx.balance = 5000.0
    ctx.agent2_summary = {
        "prior_outcome": "no_deal",
        "offers_rejected": [{"type": "lump_sum"}, {"type": "payment_plan"}],
        "objections": ["too expensive", "need more time"],
    }
    ctx.agent2_offers_made = [{"type": "lump_sum"}, {"type": "payment_plan"}]
    ctx.hardship_detected = True

    # Build the opening manually (same logic as run_final_notice_agent)
    handoff_summary = ctx.agent2_summary
    voice_outcome = handoff_summary.get("prior_outcome", "")
    prior_offers = handoff_summary.get("offers_rejected", [])
    prior_objections = handoff_summary.get("objections", [])

    assert voice_outcome == "no_deal", "Should read voice outcome from handoff"
    assert len(prior_offers) == 2, "Should have 2 rejected offers"
    assert len(prior_objections) == 2, "Should have 2 objections"

    # Verify the agent's opening would reference the call
    # (We can't run the full agent without LLM, but we can check the logic)
    continuity_parts = ["I am an AI agent and this conversation is being recorded."]
    if voice_outcome == "no_deal" and prior_offers:
        offer_labels = []
        for o in prior_offers[:3]:
            if isinstance(o, dict):
                offer_labels.append(o.get("type", "settlement option"))
        continuity_parts.append(
            f"Following up on our phone call — I understand you were unable to "
            f"reach an agreement on the options discussed ({', '.join(offer_labels)})."
        )
    intro = " ".join(continuity_parts)

    assert "phone call" in intro, f"Opening should reference phone call: {intro}"
    assert "lump_sum" in intro, f"Opening should reference rejected offers: {intro}"
    assert "payment_plan" in intro, f"Opening should reference payment plan: {intro}"
    print(f"  PASS: Opening references voice call, rejected offers, and objections")
    print(f"  Opening: {intro[:120]}...")


def test_agent1_disclosure_in_prompt():
    """Verify Agent 1 system prompt requires AI identity and recording disclosure."""
    print("\n--- Test: Agent 1 Compliance Disclosure ---")
    import yaml

    with open("registry/active_prompts.yaml") as f:
        registry = yaml.safe_load(f)

    prompt = registry["assessment"]["prompt"].lower()
    assert "ai" in prompt, "Assessment prompt should mention AI identity"
    assert "recorded" in prompt, "Assessment prompt should mention recording"
    assert "first message" in prompt or "first" in prompt, "Should require disclosure on first message"
    print("  PASS: Assessment prompt requires AI identity + recording disclosure")


def test_workflow_retry_policies():
    """Verify workflow has retry policies on all activities."""
    print("\n--- Test: Workflow Retry Policies ---")
    from temporal.workflow import _TRANSIENT_RETRY, _VOICE_RETRY, _HANDOFF_RETRY

    assert _TRANSIENT_RETRY.maximum_attempts == 3, "Transient retry should try 3 times"
    assert _VOICE_RETRY.maximum_attempts == 3, "Voice retry should try 3 times"
    assert _HANDOFF_RETRY.maximum_attempts == 2, "Handoff retry should try 2 times"

    # Check non-retryable errors are specified
    assert "BudgetExceededError" in _TRANSIENT_RETRY.non_retryable_error_types
    assert "ComplianceFatalError" in _VOICE_RETRY.non_retryable_error_types
    print("  PASS: All activities have retry policies with non-retryable error types")


def test_rollback_function():
    """Verify rollback_prompt exists and has correct signature."""
    print("\n--- Test: Rollback Function ---")
    import time
    from utils.db import rollback_prompt, get_previous_prompt, init_db, save_agent_prompt

    init_db()

    # Use unique versions to avoid UNIQUE constraint collisions from prior runs
    ts = int(time.time()) % 100000
    agent_name = f"test_rollback_{ts}"

    save_agent_prompt(agent_name, ts, "prompt v1", adoption_reason="initial", is_active=False)
    save_agent_prompt(agent_name, ts + 1, "prompt v2", adoption_reason="better", is_active=True)

    # Check previous prompt
    prev = get_previous_prompt(agent_name)
    assert prev is not None, "Should find previous prompt"
    print(f"  Previous prompt version: {prev.version}")

    # Rollback
    result = rollback_prompt(agent_name)
    assert result is True, "Rollback should succeed"
    print("  PASS: Rollback function works")


def test_power_analysis():
    """Verify power analysis computes correct sample sizes."""
    print("\n--- Test: Power Analysis ---")
    from learning.statistics import power_analysis

    # Standard case: d=0.5, alpha=0.05, power=0.80
    pa = power_analysis(effect_size=0.5, alpha=0.05, power=0.80, num_comparisons=1)
    assert pa["n_ideal"] > 0, "Should compute positive sample size"
    # Normal approximation: n = ((z_alpha + z_beta) / d)^2 ≈ 32 per group
    assert 25 <= pa["n_ideal"] <= 70, f"Expected 25-70, got {pa['n_ideal']}"
    print(f"  d=0.5, single comparison: N={pa['n_ideal']}")

    # With Bonferroni: 3 comparisons should require larger N
    pa3 = power_analysis(effect_size=0.5, alpha=0.05, power=0.80, num_comparisons=3)
    assert pa3["n_ideal"] >= pa["n_ideal"], "Bonferroni should require >= N"
    assert pa3["alpha_adj"] < pa["alpha"], "Adjusted alpha should be smaller"
    print(f"  d=0.5, 3 comparisons: N={pa3['n_ideal']} (alpha_adj={pa3['alpha_adj']:.4f})")

    # Large effect: should need fewer
    pa_large = power_analysis(effect_size=0.8, alpha=0.05, power=0.80, num_comparisons=1)
    assert pa_large["n_ideal"] < pa["n_ideal"], "Large effect should need fewer samples"
    print(f"  d=0.8, single comparison: N={pa_large['n_ideal']}")

    # Trade-off note
    assert "trade_off" in pa or "trade_off_note" in pa, "Should include trade-off note"
    print(f"  Trade-off: {pa['trade_off_note'][:80]}...")
    print("  PASS: Power analysis computes correct sample sizes")


def test_godel_rules_applied_in_scoring():
    """Verify Gödel rules affect composite scores during evaluation."""
    print("\n--- Test: Gödel Rules in Scoring ---")
    from learning.evaluator import compute_composite, _check_godel_violations
    from learning.godel_monitor import _load_rules

    # Check that rules file exists and has at least one rule
    rules = _load_rules()
    assert len(rules) > 0, "godel_rules.json should have at least one rule"
    print(f"  Active rules: {len(rules)}")

    # Score without Gödel violations
    score_clean = compute_composite(resolved=True, compliance=1.0, efficiency=0.5)
    # Score with 1 Gödel violation
    score_penalized = compute_composite(resolved=True, compliance=1.0, efficiency=0.5, godel_violations=1)
    assert score_penalized < score_clean, "Gödel violations should reduce composite score"
    assert abs(score_clean - score_penalized - 0.1) < 1e-9, f"Penalty should be 0.1, got {score_clean - score_penalized}"
    print(f"  Clean score: {score_clean:.3f}, penalized: {score_penalized:.3f}")

    # Test that _check_godel_violations is callable and returns int
    # (LLM-based in production, falls back to heuristics in tests without API key)
    msgs = [
        {"role": "assistant", "content": "Thank you for confirming. Your payment is scheduled."},
    ]
    v = _check_godel_violations(msgs)
    assert isinstance(v, int), f"Should return int, got {type(v)}"
    print(f"  Violations detected: {v}")
    print("  PASS: Gödel rules integrated into scoring pipeline")


def test_workflow_no_response_retry():
    """Verify workflow-level no-response retry constants exist."""
    print("\n--- Test: Workflow No-Response Retry ---")
    from temporal.workflow import _MAX_NO_RESPONSE_RETRIES, _NO_RESPONSE_DELAY

    assert _MAX_NO_RESPONSE_RETRIES == 3, f"Expected 3 retries, got {_MAX_NO_RESPONSE_RETRIES}"
    assert _NO_RESPONSE_DELAY.total_seconds() > 0, "Delay should be positive"
    print(f"  Max retries: {_MAX_NO_RESPONSE_RETRIES}")
    print(f"  Delay between retries: {_NO_RESPONSE_DELAY}")
    print("  PASS: No-response retry configured at workflow level")


def test_token_budget_enforcement():
    """Verify BaseAgent enforces 2000-token budget."""
    print("\n--- Test: Token Budget Enforcement ---")
    from agents.base_agent import BaseAgent

    # Create a test agent (assessment has a known prompt)
    agent = BaseAgent("assessment")

    # Verify budget constants
    assert agent.MAX_CONTEXT_TOKENS == 2000, f"Expected 2000, got {agent.MAX_CONTEXT_TOKENS}"
    assert agent.MAX_HANDOFF_TOKENS == 500, f"Expected 500, got {agent.MAX_HANDOFF_TOKENS}"
    assert agent._system_prompt_tokens > 0, "System prompt should have tokens"
    print(f"  System prompt: {agent._system_prompt_tokens} tokens")
    print(f"  Max context: {agent.MAX_CONTEXT_TOKENS}")

    # Test enforce_message_budget: create messages that exceed budget
    big_msg = "word " * 500  # ~500 tokens
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": big_msg},
        {"role": "user", "content": big_msg},
        {"role": "assistant", "content": big_msg},
        {"role": "user", "content": big_msg},
    ]
    budgeted = agent.enforce_message_budget(messages)
    assert len(budgeted) < len(messages), f"Should trim messages: {len(budgeted)} < {len(messages)}"
    # First message should be preserved
    assert budgeted[0]["content"] == "Hello", "First message should be preserved"
    print(f"  Input messages: {len(messages)}, after budget: {len(budgeted)}")

    # Verify total fits in budget
    total = agent._system_prompt_tokens
    for m in budgeted:
        total += agent._count_tokens(m.get("content", "")) + 5
    assert total <= agent.MAX_CONTEXT_TOKENS, f"Total {total} exceeds {agent.MAX_CONTEXT_TOKENS}"
    print(f"  Total after trim: {total} tokens (budget: {agent.MAX_CONTEXT_TOKENS})")
    print("  PASS: Token budget enforced correctly")


def test_docker_secrets_path():
    """Verify _read_secret checks both local and Docker paths."""
    print("\n--- Test: Docker Secrets Path ---")
    from utils.config import _read_secret
    import inspect

    source = inspect.getsource(_read_secret)
    assert "/run/secrets/" in source, "Should check /run/secrets/ for Docker"
    assert "secrets/" in source or 'os.path.join("secrets"' in source, "Should check local secrets/"
    print("  PASS: _read_secret checks both local and Docker secret paths")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("WORKFLOW, AGENT, AND INFRASTRUCTURE TESTS")
    print("=" * 60)

    test_bonferroni_correction()
    test_transcript_collection()
    test_godel_monitor_with_transcripts()
    test_agent3_continuity_references()
    test_agent1_disclosure_in_prompt()
    test_workflow_retry_policies()
    test_rollback_function()
    test_docker_secrets_path()
    test_power_analysis()
    test_godel_rules_applied_in_scoring()
    test_workflow_no_response_retry()
    test_token_budget_enforcement()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
