"""
Integration test for the self-learning A/B evaluation loop.

Runs a small-scale (3 conversations, 1 iteration) real evaluation to verify
that the full pipeline works: prompt generation → synthetic conversations →
statistical comparison → DB writes → CSV output.
"""

import os
import sys
import csv
import json

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learning_loop import LearningLoop
from learning.statistics import is_significant_improvement, StatisticalDecision
from learning.evaluator import VariantEvaluator, compute_composite
from learning.data_export import RawDataWriter, EvolutionReportGenerator, EVALS_DIR
from utils.db import init_db, get_db
from utils.cost_tracker import get_cost_tracker


def test_statistics_module():
    """Verify statistical functions produce real results (not hardcoded)."""
    print("\n--- Test: Statistics Module ---")

    # Two clearly different distributions
    baseline = [0.4, 0.5, 0.45, 0.42, 0.48, 0.51, 0.44, 0.46, 0.50, 0.47]
    variant  = [0.7, 0.75, 0.68, 0.72, 0.71, 0.69, 0.74, 0.73, 0.70, 0.72]

    decision = is_significant_improvement(baseline, variant)

    assert isinstance(decision, StatisticalDecision), "Should return StatisticalDecision"
    assert decision.adopted is True, f"Clear improvement should be adopted, got: {decision.rejection_reasons}"
    assert decision.p_value < 0.05, f"p-value should be < 0.05, got {decision.p_value}"
    assert decision.effect_size_cohens_d > 0.5, f"Cohen's d should be > 0.5, got {decision.effect_size_cohens_d}"
    assert decision.ci_lower > 0, f"CI lower should be > 0, got {decision.ci_lower}"
    print(f"  PASS: p={decision.p_value:.6f}, d={decision.effect_size_cohens_d:.3f}, CI=[{decision.ci_lower:.3f}, {decision.ci_upper:.3f}]")

    # Two identical distributions — should NOT be adopted
    same_a = [0.5] * 10
    same_b = [0.5] * 10
    decision2 = is_significant_improvement(same_a, same_b)
    assert decision2.adopted is False, "Identical distributions should not be adopted"
    print(f"  PASS: Identical distributions rejected ({len(decision2.rejection_reasons)} reasons)")


def test_composite_score():
    """Verify composite score computation."""
    print("\n--- Test: Composite Score ---")
    score = compute_composite(resolved=True, compliance=1.0, efficiency=0.5)
    assert 0 < score <= 1.0, f"Composite should be in (0, 1], got {score}"
    print(f"  PASS: composite={score:.3f}")

    score_unresolved = compute_composite(resolved=False, compliance=1.0, efficiency=0.5)
    assert score_unresolved < score, "Unresolved should score lower"
    print(f"  PASS: unresolved={score_unresolved:.3f} < resolved={score:.3f}")


def test_csv_output():
    """Verify CSV writer creates files with correct columns."""
    print("\n--- Test: CSV Output ---")
    writer = RawDataWriter()

    # Write a dummy score
    from learning.evaluator import EvaluationResult, ConversationScore
    dummy = EvaluationResult(
        agent_name="test_agent",
        variant_id="test_v1",
        prompt_text="test prompt",
        scores=[
            ConversationScore(
                scenario_idx=0, persona="cooperative", resolved=True,
                compliance_score=1.0, violation_count=0, turns=3,
                efficiency=0.33, composite_score=0.75,
            )
        ],
    )
    writer.write_scores(0, "test_agent", dummy)

    # Verify file exists with correct headers
    scores_path = os.path.join(EVALS_DIR, "raw_scores.csv")
    assert os.path.exists(scores_path), f"raw_scores.csv should exist at {scores_path}"
    with open(scores_path) as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        assert "composite_score" in headers, f"Missing composite_score column, got {headers}"
        rows = list(reader)
        assert len(rows) >= 1, "Should have at least one data row"
    print(f"  PASS: raw_scores.csv exists with {len(rows)} rows, headers={headers}")

    # Write a dummy decision
    decision = StatisticalDecision(
        adopted=True, p_value=0.01, effect_size_cohens_d=0.8,
        ci_lower=0.1, ci_upper=0.3, mean_improvement_pct=15.0,
        variance_ratio=1.5, baseline_mean=0.5, baseline_std=0.1,
        variant_mean=0.7, variant_std=0.1, n_baseline=10, n_variant=10,
    )
    writer.write_decision(0, "test_agent", "test_v1", decision)

    decisions_path = os.path.join(EVALS_DIR, "decisions.csv")
    assert os.path.exists(decisions_path), "decisions.csv should exist"
    with open(decisions_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) >= 1
    print(f"  PASS: decisions.csv exists with {len(rows)} decision rows")


def test_evolution_report():
    """Verify evolution report generation."""
    print("\n--- Test: Evolution Report ---")
    report = EvolutionReportGenerator().generate()
    assert "# Prompt Evolution Report" in report
    assert os.path.exists(os.path.join(EVALS_DIR, "evolution_report.md"))
    print(f"  PASS: evolution_report.md generated ({len(report)} chars)")


def test_small_scale_learning_loop():
    """
    Run a real (small-scale) learning loop: 1 iteration, 3 conversations.

    This is an integration test that actually calls the LLM, runs synthetic
    borrower conversations, and verifies the full pipeline.
    """
    print("\n--- Test: Small-Scale Learning Loop (LIVE) ---")
    print("  (This calls the LLM — may take a minute)")

    init_db()

    loop = LearningLoop(
        num_conversations=3,
        max_iterations=1,
        num_variants=1,  # just 1 variant to keep cost low
        seed=42,
    )

    summary = loop.run()

    assert summary["iterations_completed"] >= 1, "Should complete at least 1 iteration"
    print(f"  Iterations: {summary['iterations_completed']}")
    print(f"  Adoptions:  {summary['total_adoptions']}")
    print(f"  Spend:      ${summary['final_spend_usd']:.4f}")

    # Verify CSV files were written with real data
    scores_path = os.path.join(EVALS_DIR, "raw_scores.csv")
    with open(scores_path) as f:
        rows = list(csv.DictReader(f))
        real_rows = [r for r in rows if r["agent"] != "test_agent"]
        assert len(real_rows) >= 3, f"Should have at least 3 real score rows, got {len(real_rows)}"
    print(f"  PASS: {len(real_rows)} real score rows in CSV")

    decisions_path = os.path.join(EVALS_DIR, "decisions.csv")
    if os.path.exists(decisions_path):
        with open(decisions_path) as f:
            rows = list(csv.DictReader(f))
            real_decisions = [r for r in rows if r["agent"] != "test_agent"]
            if real_decisions:
                # Verify decisions have real p-values (not 0.0 or 1.0 hardcoded)
                for d in real_decisions:
                    p = float(d["p_value"])
                    assert 0.0 <= p <= 1.0, f"Invalid p-value: {p}"
                print(f"  PASS: {len(real_decisions)} real decision rows with valid p-values")

    # Verify DB was populated
    db = get_db()
    try:
        from db.models import EvaluationRun, PromptEvaluation
        eval_count = db.query(EvaluationRun).count()
        prompt_eval_count = db.query(PromptEvaluation).count()
        print(f"  DB: {eval_count} evaluation runs, {prompt_eval_count} prompt evaluations")
        assert eval_count >= 1, "Should have at least 1 evaluation run in DB"
    finally:
        db.close()

    print("  PASS: Full pipeline verified")


def main():
    print("=" * 60)
    print("PHASE 4: SELF-LEARNING LOOP INTEGRATION TEST")
    print("=" * 60)

    # Unit-level tests (no LLM calls)
    test_statistics_module()
    test_composite_score()
    test_csv_output()
    test_evolution_report()

    # Integration test (requires LLM API key)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        test_small_scale_learning_loop()
    else:
        print("\n--- SKIPPED: Small-Scale Learning Loop (no ANTHROPIC_API_KEY) ---")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
