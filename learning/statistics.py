"""
Statistical significance testing for the self-learning loop.

Provides rigorous comparison between baseline and variant prompt performance
using Welch's t-test, Cohen's d effect size, confidence intervals, and
variance ratio checks. All thresholds come from LEARNING_CONFIG in utils/config.py.
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from scipy import stats
import numpy as np

from utils.config import LEARNING_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class TTestResult:
    t_statistic: float
    p_value: float
    degrees_of_freedom: float


@dataclass
class StatisticalDecision:
    """Full quantitative justification for adopting or rejecting a variant."""
    adopted: bool
    p_value: float
    effect_size_cohens_d: float
    ci_lower: float
    ci_upper: float
    mean_improvement_pct: float
    variance_ratio: float
    baseline_mean: float
    baseline_std: float
    variant_mean: float
    variant_std: float
    n_baseline: int
    n_variant: int
    rejection_reasons: List[str] = field(default_factory=list)

    def to_justification_string(self) -> str:
        """Human-readable justification for adoption."""
        return (
            f"Adopted: mean {self.baseline_mean:.3f} → {self.variant_mean:.3f} "
            f"(+{self.mean_improvement_pct:.1f}%), "
            f"p={self.p_value:.4f}, d={self.effect_size_cohens_d:.3f}, "
            f"95% CI [{self.ci_lower:.3f}, {self.ci_upper:.3f}], "
            f"n={self.n_baseline}/{self.n_variant}"
        )

    def to_rejection_string(self) -> str:
        """Human-readable justification for rejection."""
        reasons = "; ".join(self.rejection_reasons) if self.rejection_reasons else "unknown"
        return (
            f"Rejected ({reasons}): mean {self.baseline_mean:.3f} → {self.variant_mean:.3f} "
            f"({self.mean_improvement_pct:+.1f}%), "
            f"p={self.p_value:.4f}, d={self.effect_size_cohens_d:.3f}, "
            f"n={self.n_baseline}/{self.n_variant}"
        )

    def to_csv_row(self) -> dict:
        return {
            "adopted": self.adopted,
            "p_value": round(self.p_value, 6),
            "cohens_d": round(self.effect_size_cohens_d, 4),
            "ci_lower": round(self.ci_lower, 4),
            "ci_upper": round(self.ci_upper, 4),
            "mean_improvement_pct": round(self.mean_improvement_pct, 2),
            "variance_ratio": round(self.variance_ratio, 4),
            "baseline_mean": round(self.baseline_mean, 4),
            "baseline_std": round(self.baseline_std, 4),
            "variant_mean": round(self.variant_mean, 4),
            "variant_std": round(self.variant_std, 4),
            "n_baseline": self.n_baseline,
            "n_variant": self.n_variant,
            "rejection_reasons": "|".join(self.rejection_reasons),
        }


def welchs_t_test(scores_a: List[float], scores_b: List[float]) -> TTestResult:
    """
    Welch's t-test for unequal variances.
    Tests H0: mean(a) == mean(b) vs H1: mean(a) != mean(b).
    """
    a = np.array(scores_a, dtype=float)
    b = np.array(scores_b, dtype=float)

    if len(a) < 2 or len(b) < 2:
        return TTestResult(t_statistic=0.0, p_value=1.0, degrees_of_freedom=0.0)

    # If both arrays are constant (zero variance), no test is meaningful
    if np.std(a) == 0 and np.std(b) == 0:
        if np.mean(a) == np.mean(b):
            return TTestResult(t_statistic=0.0, p_value=1.0, degrees_of_freedom=len(a) + len(b) - 2)
        else:
            # Means differ but no variance — treat as significant
            return TTestResult(t_statistic=float('inf'), p_value=0.0, degrees_of_freedom=len(a) + len(b) - 2)

    t_stat, p_val = stats.ttest_ind(a, b, equal_var=False)
    # Welch-Satterthwaite degrees of freedom
    df = _welch_df(a, b)
    return TTestResult(t_statistic=float(t_stat), p_value=float(p_val), degrees_of_freedom=df)


def cohens_d(scores_a: List[float], scores_b: List[float]) -> float:
    """
    Cohen's d effect size using pooled standard deviation.
    Positive d means scores_b > scores_a (improvement).
    """
    a = np.array(scores_a, dtype=float)
    b = np.array(scores_b, dtype=float)

    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return 0.0

    s1, s2 = np.std(a, ddof=1), np.std(b, ddof=1)
    pooled_sd = math.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))

    if pooled_sd == 0:
        return 0.0 if np.mean(a) == np.mean(b) else float('inf')

    return float((np.mean(b) - np.mean(a)) / pooled_sd)


def confidence_interval(
    scores_a: List[float], scores_b: List[float], alpha: float = 0.05
) -> Tuple[float, float]:
    """
    95% confidence interval on the difference of means (b - a).
    Uses Welch's approximation for degrees of freedom.
    """
    a = np.array(scores_a, dtype=float)
    b = np.array(scores_b, dtype=float)

    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return (0.0, 0.0)

    mean_diff = float(np.mean(b) - np.mean(a))
    se = math.sqrt(np.var(a, ddof=1) / n1 + np.var(b, ddof=1) / n2)

    if se == 0:
        return (mean_diff, mean_diff)

    df = _welch_df(a, b)
    t_crit = stats.t.ppf(1 - alpha / 2, df)

    return (mean_diff - t_crit * se, mean_diff + t_crit * se)


def variance_ratio(scores_a: List[float], scores_b: List[float]) -> float:
    """
    Ratio of max variance to min variance.
    High ratio (>4) suggests heterogeneous performance.
    """
    a = np.array(scores_a, dtype=float)
    b = np.array(scores_b, dtype=float)

    if len(a) < 2 or len(b) < 2:
        return 0.0

    var_a = float(np.var(a, ddof=1))
    var_b = float(np.var(b, ddof=1))

    if var_a == 0 and var_b == 0:
        return 1.0

    max_var = max(var_a, var_b)
    min_var = min(var_a, var_b)

    if min_var == 0:
        return float('inf')

    return max_var / min_var


def is_significant_improvement(
    baseline_scores: List[float],
    variant_scores: List[float],
    effect_size_threshold: float = None,
    improvement_threshold_pct: float = None,
    max_var_ratio: float = None,
    alpha: float = 0.05,
    num_comparisons: int = 1,
) -> StatisticalDecision:
    """
    Composite statistical decision: should we adopt this variant?

    A variant is adopted only if ALL of:
      1. p-value < alpha/num_comparisons (Bonferroni-corrected significance)
      2. Cohen's d >= effect_size_threshold (practically meaningful)
      3. Mean improvement >= improvement_threshold_pct (magnitude check)
      4. Variance ratio < max_var_ratio (consistent performance)
      5. CI lower bound > 0 (confident the improvement is positive)

    Thresholds default to LEARNING_CONFIG values.  When testing K variants
    against one baseline, pass ``num_comparisons=K`` to apply Bonferroni
    correction (alpha_adj = alpha / K).
    """
    cfg = LEARNING_CONFIG
    effect_size_threshold = effect_size_threshold or cfg["effect_size_threshold"]
    improvement_threshold_pct = improvement_threshold_pct or cfg["improvement_threshold_pct"]
    max_var_ratio = max_var_ratio or cfg["max_variance_ratio"]

    # Bonferroni correction: adjust alpha for multiple comparisons
    alpha_adj = alpha / max(num_comparisons, 1)

    b = np.array(baseline_scores, dtype=float)
    v = np.array(variant_scores, dtype=float)

    b_mean, b_std = float(np.mean(b)), float(np.std(b, ddof=1)) if len(b) > 1 else 0.0
    v_mean, v_std = float(np.mean(v)), float(np.std(v, ddof=1)) if len(v) > 1 else 0.0

    # Compute metrics
    t_result = welchs_t_test(baseline_scores, variant_scores)
    d = cohens_d(baseline_scores, variant_scores)
    ci = confidence_interval(baseline_scores, variant_scores, alpha)
    vr = variance_ratio(baseline_scores, variant_scores)

    improvement_pct = ((v_mean - b_mean) / b_mean * 100) if b_mean > 0 else 0.0

    # Decision logic
    rejection_reasons = []

    if t_result.p_value >= alpha_adj:
        if num_comparisons > 1:
            rejection_reasons.append(
                f"p={t_result.p_value:.4f} >= {alpha_adj:.4f} "
                f"(Bonferroni-adjusted alpha: {alpha}/{num_comparisons})"
            )
        else:
            rejection_reasons.append(f"p={t_result.p_value:.4f} >= {alpha} (not significant)")

    if d < effect_size_threshold:
        rejection_reasons.append(f"d={d:.3f} < {effect_size_threshold} (effect too small)")

    if improvement_pct < improvement_threshold_pct * 100:
        rejection_reasons.append(
            f"improvement={improvement_pct:.1f}% < {improvement_threshold_pct*100:.0f}%"
        )

    if vr > 1.0 / max_var_ratio:  # max_variance_ratio=0.25 means max ratio of 4.0
        rejection_reasons.append(f"variance_ratio={vr:.2f} too high (inconsistent)")

    if ci[0] <= 0:
        rejection_reasons.append(f"CI lower={ci[0]:.4f} <= 0 (improvement not confident)")

    adopted = len(rejection_reasons) == 0

    decision = StatisticalDecision(
        adopted=adopted,
        p_value=t_result.p_value,
        effect_size_cohens_d=d,
        ci_lower=ci[0],
        ci_upper=ci[1],
        mean_improvement_pct=improvement_pct,
        variance_ratio=vr,
        baseline_mean=b_mean,
        baseline_std=b_std,
        variant_mean=v_mean,
        variant_std=v_std,
        n_baseline=len(baseline_scores),
        n_variant=len(variant_scores),
        rejection_reasons=rejection_reasons,
    )

    action = "ADOPT" if adopted else "REJECT"
    logger.info(
        f"Statistical decision: {action} | "
        f"p={t_result.p_value:.4f}, d={d:.3f}, "
        f"Δ={improvement_pct:+.1f}%, CI=[{ci[0]:.3f},{ci[1]:.3f}]"
    )
    return decision


def power_analysis(
    effect_size: float = 0.5,
    alpha: float = 0.05,
    power: float = 0.80,
    num_comparisons: int = 1,
) -> Dict:
    """
    Compute the required sample size per group for a two-sample t-test.

    Uses the normal approximation:
        n = ((z_alpha + z_beta) / d)^2  per group

    With Bonferroni correction: alpha_adj = alpha / num_comparisons.

    Returns a dict with:
      - n_ideal: sample size for the given power
      - n_used: the N we actually use (from LEARNING_CONFIG or caller)
      - alpha_adj: Bonferroni-adjusted alpha
      - effect_size, power: inputs echoed back
      - trade_off_note: explanation of any shortfall
    """
    from scipy.stats import norm

    alpha_adj = alpha / max(num_comparisons, 1)

    z_alpha = norm.ppf(1 - alpha_adj / 2)
    z_beta = norm.ppf(power)

    n_ideal = math.ceil(((z_alpha + z_beta) / effect_size) ** 2)

    n_used = LEARNING_CONFIG.get("conversations_per_variant", 25)

    if n_used >= n_ideal:
        note = f"N={n_used} >= ideal N={n_ideal}. Sufficient statistical power."
    else:
        # Compute achieved power at n_used
        achieved_z = effect_size * math.sqrt(n_used) - z_alpha
        achieved_power = norm.cdf(achieved_z)
        note = (
            f"N={n_used} < ideal N={n_ideal}. Achieved power ≈ {achieved_power:.0%} "
            f"(target {power:.0%}). Trade-off: budget constraint limits sample size. "
            f"At $0.005/conversation (Haiku), ideal N={n_ideal} × 4 variants × 3 agents "
            f"= {n_ideal * 4 * 3} conversations ≈ ${n_ideal * 4 * 3 * 0.005:.2f}/iteration."
        )

    return {
        "n_ideal": n_ideal,
        "n_used": n_used,
        "alpha": alpha,
        "alpha_adj": round(alpha_adj, 6),
        "effect_size": effect_size,
        "power": power,
        "num_comparisons": num_comparisons,
        "trade_off_note": note,
    }


def _welch_df(a: np.ndarray, b: np.ndarray) -> float:
    """Welch-Satterthwaite degrees of freedom."""
    n1, n2 = len(a), len(b)
    v1, v2 = np.var(a, ddof=1), np.var(b, ddof=1)

    num = (v1 / n1 + v2 / n2) ** 2
    denom = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)

    if denom == 0:
        return float(n1 + n2 - 2)

    return float(num / denom)
