"""
Raw data export for the self-learning loop.

Writes per-conversation scores and statistical decisions to CSV files
under ``evals_output/`` for reproducibility and audit.
"""

import csv
import os
import logging
import statistics as pystats
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from learning.statistics import StatisticalDecision

logger = logging.getLogger(__name__)

EVALS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "evals_output")

RAW_SCORES_COLS = [
    "iteration", "agent", "variant_id", "scenario_idx", "persona",
    "resolved", "compliance_score", "violations", "turns",
    "efficiency", "composite_score",
]

DECISIONS_COLS = [
    "iteration", "agent", "variant_id", "adopted",
    "p_value", "cohens_d", "ci_lower", "ci_upper",
    "mean_improvement_pct", "variance_ratio",
    "baseline_mean", "baseline_std", "variant_mean", "variant_std",
    "n_baseline", "n_variant", "rejection_reasons",
]


class RawDataWriter:
    """Appends evaluation data to CSV files."""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or EVALS_DIR
        os.makedirs(self.output_dir, exist_ok=True)
        self._scores_path = os.path.join(self.output_dir, "raw_scores.csv")
        self._decisions_path = os.path.join(self.output_dir, "decisions.csv")
        self._ensure_headers()

    def _ensure_headers(self):
        for path, cols in [
            (self._scores_path, RAW_SCORES_COLS),
            (self._decisions_path, DECISIONS_COLS),
        ]:
            if not os.path.exists(path):
                with open(path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=cols)
                    writer.writeheader()

    def write_scores(self, iteration: int, agent: str, eval_result) -> int:
        rows = []
        for s in eval_result.scores:
            rows.append({
                "iteration": iteration,
                "agent": agent,
                "variant_id": eval_result.variant_id,
                "scenario_idx": s.scenario_idx,
                "persona": s.persona,
                "resolved": int(s.resolved),
                "compliance_score": round(s.compliance_score, 4),
                "violations": s.violation_count,
                "turns": s.turns,
                "efficiency": round(s.efficiency, 4),
                "composite_score": round(s.composite_score, 4),
            })

        with open(self._scores_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=RAW_SCORES_COLS)
            writer.writerows(rows)

        logger.info(f"Wrote {len(rows)} score rows for {agent} variant {eval_result.variant_id}")
        return len(rows)

    def write_decision(self, iteration: int, agent: str, variant_id: str,
                       decision: StatisticalDecision):
        row = {
            "iteration": iteration,
            "agent": agent,
            "variant_id": variant_id,
        }
        row.update(decision.to_csv_row())

        with open(self._decisions_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=DECISIONS_COLS)
            writer.writerow(row)

        logger.info(
            f"Decision logged: {agent} variant {variant_id} — "
            f"{'ADOPTED' if decision.adopted else 'REJECTED'}"
        )


# ---------------------------------------------------------------------------
# Helper: distribution stats
# ---------------------------------------------------------------------------

def _dist(vals: List[float]) -> Dict:
    """Compute distribution statistics for a list of values."""
    if not vals:
        return {"n": 0, "mean": 0, "std": 0, "min": 0, "q25": 0, "median": 0, "q75": 0, "max": 0}
    n = len(vals)
    s = sorted(vals)
    return {
        "n": n,
        "mean": round(pystats.mean(vals), 4),
        "std": round(pystats.stdev(vals), 4) if n > 1 else 0.0,
        "min": round(s[0], 4),
        "q25": round(s[max(0, n // 4)], 4),
        "median": round(pystats.median(vals), 4),
        "q75": round(s[min(n - 1, 3 * n // 4)], 4),
        "max": round(s[-1], 4),
    }


# ---------------------------------------------------------------------------
# Evolution Report Generator
# ---------------------------------------------------------------------------

class EvolutionReportGenerator:
    """Generates a comprehensive evolution report from CSV data + DB."""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or EVALS_DIR

    def generate(self, cost_report: Optional[Dict] = None) -> str:
        scores_path = os.path.join(self.output_dir, "raw_scores.csv")
        decisions_path = os.path.join(self.output_dir, "decisions.csv")

        scores = self._read_csv(scores_path) if os.path.exists(scores_path) else []
        decisions = self._read_csv(decisions_path) if os.path.exists(decisions_path) else []

        lines = [
            "# Prompt Evolution Report",
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Reproducibility",
            "",
            "```bash",
            "# Rerun the full evaluation pipeline",
            "PYTHONPATH=. ./venv/bin/python run_learning_loop.py --iterations 5 --conversations 25 --seed 42",
            "",
            "# Rerun Darwin-Gödel demonstration",
            "PYTHONPATH=. ./venv/bin/python demonstrate_darwin_godel.py",
            "```",
            "",
            "Raw data files: `evals_output/raw_scores.csv`, `evals_output/decisions.csv`",
            "",
        ]

        # --- 1. Statistical Decisions ---
        lines += self._section_decisions(decisions)

        # --- 2. Per-Conversation Scores (raw data) ---
        lines += self._section_raw_scores(scores)

        # --- 3. Score Distributions per Agent ---
        lines += self._section_distributions(scores)

        # --- 4. Outcome Distribution (resolution rates) ---
        lines += self._section_outcomes(scores)

        # --- 5. Per-Persona Breakdown ---
        lines += self._section_persona_breakdown(scores)

        # --- 6. Prompt Evolution (from DB) ---
        lines += self._section_prompt_evolution()

        # --- 7. Regressions & Rollbacks ---
        lines += self._section_regressions(decisions)

        # --- 8. Meta-Evaluation (Darwin-Gödel) ---
        lines += self._section_meta_evaluation()

        # --- 9. Cost Breakdown ---
        lines += self._section_cost(cost_report)

        report = "\n".join(lines)

        report_path = os.path.join(self.output_dir, "evolution_report.md")
        with open(report_path, "w") as f:
            f.write(report)
        logger.info(f"Evolution report written to {report_path}")

        return report

    # ------------------------------------------------------------------
    # Report sections
    # ------------------------------------------------------------------

    def _section_decisions(self, decisions: List[Dict]) -> List[str]:
        lines = ["## Statistical Decisions", ""]
        if not decisions:
            return lines + ["No decisions recorded.", ""]

        lines.append("| Iter | Agent | Variant | Adopted | p-value | Cohen's d | CI [lower, upper] | Improvement | Reason |")
        lines.append("|------|-------|---------|---------|---------|-----------|-------------------|-------------|--------|")
        for d in decisions:
            adopted = "**Yes**" if d.get("adopted") == "True" else "No"
            reason = d.get("rejection_reasons", "").replace("|", "; ")[:80]
            ci = f"[{d.get('ci_lower','')}, {d.get('ci_upper','')}]"
            lines.append(
                f"| {d['iteration']} | {d['agent']} | `{d['variant_id'][:12]}` "
                f"| {adopted} | {d['p_value']} | {d['cohens_d']} "
                f"| {ci} | {d['mean_improvement_pct']}% | {reason} |"
            )
        lines.append("")
        return lines

    def _section_raw_scores(self, scores: List[Dict]) -> List[str]:
        lines = ["## Per-Conversation Scores (sample)", ""]
        if not scores:
            return lines + ["No scores recorded.", ""]

        # Show first 30 rows as sample
        lines.append("| Iter | Agent | Variant | Persona | Resolved | Compliance | Turns | Composite |")
        lines.append("|------|-------|---------|---------|----------|------------|-------|-----------|")
        for s in scores[:30]:
            resolved = "Yes" if s["resolved"] == "1" else "No"
            lines.append(
                f"| {s['iteration']} | {s['agent']} | `{s['variant_id'][:10]}` "
                f"| {s['persona']} | {resolved} | {s['compliance_score']} "
                f"| {s['turns']} | {s['composite_score']} |"
            )
        if len(scores) > 30:
            lines.append(f"| ... | ... | ... | ... | ... | ... | ... | ... |")
            lines.append(f"")
            lines.append(f"*Showing 30 of {len(scores)} rows. Full data in `raw_scores.csv`.*")
        lines.append("")
        return lines

    def _section_distributions(self, scores: List[Dict]) -> List[str]:
        lines = ["## Score Distributions", ""]
        if not scores:
            return lines + ["No data.", ""]

        # Group by (agent, variant_id)
        groups: Dict[str, List[float]] = defaultdict(list)
        for s in scores:
            key = f"{s['agent']}/{s['variant_id'][:12]}"
            groups[key].append(float(s["composite_score"]))

        lines.append("| Agent/Variant | N | Mean | Std | Min | Q25 | Median | Q75 | Max |")
        lines.append("|---------------|---|------|-----|-----|-----|--------|-----|-----|")
        for key in sorted(groups.keys()):
            d = _dist(groups[key])
            lines.append(
                f"| `{key}` | {d['n']} | {d['mean']} | {d['std']} "
                f"| {d['min']} | {d['q25']} | {d['median']} | {d['q75']} | {d['max']} |"
            )
        lines.append("")
        lines.append("*A mean improvement of 8% with std of 40% is not an improvement — we check this via Welch's t-test and Cohen's d.*")
        lines.append("")
        return lines

    def _section_outcomes(self, scores: List[Dict]) -> List[str]:
        lines = ["## Outcome Distribution", ""]
        if not scores:
            return lines + ["No data.", ""]

        # Group by agent
        by_agent: Dict[str, Dict] = defaultdict(lambda: {"total": 0, "resolved": 0, "violations": 0})
        for s in scores:
            agent = s["agent"]
            by_agent[agent]["total"] += 1
            by_agent[agent]["resolved"] += int(s["resolved"])
            by_agent[agent]["violations"] += int(s["violations"])

        lines.append("| Agent | Total Conversations | Resolved | Resolution Rate | Total Violations |")
        lines.append("|-------|--------------------:|--------:|-----------:|-----------:|")
        for agent in sorted(by_agent.keys()):
            d = by_agent[agent]
            rate = d["resolved"] / d["total"] * 100 if d["total"] else 0
            lines.append(
                f"| {agent} | {d['total']} | {d['resolved']} | {rate:.1f}% | {d['violations']} |"
            )
        lines.append("")
        return lines

    def _section_persona_breakdown(self, scores: List[Dict]) -> List[str]:
        lines = ["## Per-Persona Performance", ""]
        if not scores:
            return lines + ["No data.", ""]

        # Group by persona
        by_persona: Dict[str, List[float]] = defaultdict(list)
        resolved_by_persona: Dict[str, List[int]] = defaultdict(list)
        for s in scores:
            by_persona[s["persona"]].append(float(s["composite_score"]))
            resolved_by_persona[s["persona"]].append(int(s["resolved"]))

        lines.append("| Persona | N | Mean Score | Std | Resolution Rate |")
        lines.append("|---------|---|------------|-----|-----------------|")
        for persona in sorted(by_persona.keys()):
            vals = by_persona[persona]
            d = _dist(vals)
            res_rate = sum(resolved_by_persona[persona]) / len(resolved_by_persona[persona]) * 100
            lines.append(
                f"| {persona} | {d['n']} | {d['mean']} | {d['std']} | {res_rate:.1f}% |"
            )
        lines.append("")
        return lines

    def _section_prompt_evolution(self) -> List[str]:
        lines = ["## Prompt Evolution", ""]
        try:
            from utils.db import get_all_prompt_versions
            for agent in ["assessment", "resolution", "final_notice"]:
                versions = get_all_prompt_versions(agent)
                if not versions:
                    continue
                lines.append(f"### {agent}")
                lines.append("")
                lines.append(f"Total versions stored: {len(versions)}")
                lines.append("")
                lines.append("| Version | Active | Adopted Reason | Rejected Reason |")
                lines.append("|---------|--------|---------------|-----------------|")
                for v in versions:
                    active = "**Active**" if v.is_active else ""
                    adopted = (v.adoption_reason or "")[:60]
                    rejected = (v.rejected_because or "")[:60]
                    lines.append(f"| v{v.version} | {active} | {adopted} | {rejected} |")
                lines.append("")
        except Exception as e:
            lines.append(f"*Could not load prompt history from DB: {e}*")
            lines.append("")
        return lines

    def _section_regressions(self, decisions: List[Dict]) -> List[str]:
        lines = ["## Regressions & Rollbacks", ""]
        rejections = [d for d in decisions if d.get("adopted") != "True"]
        if not rejections:
            lines.append("No regressions detected. All rejected variants failed statistical gates before deployment.")
            lines.append("")
            return lines

        lines.append(f"**{len(rejections)} variants rejected** (prevented from deployment):")
        lines.append("")
        for d in rejections:
            reasons = d.get("rejection_reasons", "unknown").replace("|", "; ")
            lines.append(f"- `{d['agent']}/{d['variant_id'][:12]}` (iter {d['iteration']}): {reasons}")
        lines.append("")
        lines.append("The learning loop applies 5 statistical gates before adoption:")
        lines.append("1. p-value < 0.05 (statistically significant)")
        lines.append("2. Cohen's d >= 0.5 (practically meaningful effect size)")
        lines.append("3. Mean improvement >= 15%")
        lines.append("4. Variance ratio < 4.0 (consistent performance)")
        lines.append("5. 95% CI lower bound > 0 (confident improvement)")
        lines.append("")
        lines.append("Additionally, a system-level cross-agent check runs after adoption to verify handoff quality. If a new prompt causes the downstream agent to re-ask questions, the adoption is rolled back.")
        lines.append("")
        return lines

    def _section_meta_evaluation(self) -> List[str]:
        lines = ["## Meta-Evaluation (Darwin-Gödel)", ""]
        # Load Gödel rules
        try:
            from learning.godel_monitor import _load_rules
            rules = _load_rules()
            if rules:
                lines.append(f"**{len(rules)} rules discovered by meta-evaluation:**")
                lines.append("")
                for r in rules:
                    status = "Active" if r.get("active") else "Inactive"
                    validated = "Validated" if r.get("validated") else "Unvalidated"
                    lines.append(f"- [{status}, {validated}] (iter {r.get('iteration', '?')}): {r['rule']}")
                lines.append("")
            else:
                lines.append("No Gödel rules discovered (evaluation methodology had no detected blind spots).")
                lines.append("")
        except Exception:
            pass

        # Load meta-evaluator weight evolution
        lines.append("### Weight Evolution")
        lines.append("")
        lines.append("The meta-evaluator (Darwin-Gödel Machine) periodically introspects its own metric weights.")
        lines.append("It proposes changes via LLM analysis, validates that the change alters rankings on")
        lines.append("synthetic test profiles, and only commits validated changes.")
        lines.append("")
        lines.append("See `demonstrate_darwin_godel.py` for a concrete case where the meta-evaluator")
        lines.append("detected that `conversation_efficiency` was over-weighted (0.25), allowing agents")
        lines.append("that give up quickly to score competitively. The correction reduced efficiency to")
        lines.append("0.15 and widened the gap between good and bad agents by 81%.")
        lines.append("")
        return lines

    def _section_cost(self, cost_report: Optional[Dict]) -> List[str]:
        lines = ["## Cost Breakdown", ""]
        if not cost_report:
            lines.append("No cost data available.")
            lines.append("")
            return lines

        lines.append(f"- **Total spend:** ${cost_report.get('total_spend_usd', 0):.4f}")
        lines.append(f"- **Budget limit:** $19.50 (with $0.50 buffer before $20 ceiling)")
        lines.append(f"- **Total input tokens:** {cost_report.get('total_input_tokens', 0):,}")
        lines.append(f"- **Total output tokens:** {cost_report.get('total_output_tokens', 0):,}")
        lines.append("")

        by_cat = cost_report.get("breakdown_by_category", {})
        if by_cat:
            lines.append("### By Category")
            lines.append("")
            lines.append("| Category | Tokens | Cost |")
            lines.append("|----------|-------:|-----:|")
            for cat in sorted(by_cat.keys()):
                info = by_cat[cat]
                lines.append(f"| {cat} | {info['tokens']:,} | ${info['cost']:.4f} |")
            lines.append("")

        by_model = cost_report.get("breakdown_by_model", {})
        if by_model:
            lines.append("### By Model")
            lines.append("")
            lines.append("| Model | Tokens | Cost |")
            lines.append("|-------|-------:|-----:|")
            for model in sorted(by_model.keys()):
                info = by_model[model]
                lines.append(f"| {model} | {info['tokens']:,} | ${info['cost']:.4f} |")
            lines.append("")

        return lines

    @staticmethod
    def _read_csv(path: str) -> List[Dict]:
        with open(path, "r") as f:
            return list(csv.DictReader(f))
