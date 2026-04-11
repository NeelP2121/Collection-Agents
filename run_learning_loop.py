#!/usr/bin/env python3
"""
Run the self-learning A/B evaluation loop.

Usage:
  python run_learning_loop.py                                # defaults
  python run_learning_loop.py --iterations 3 --conversations 10 --seed 42
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)

from learning.learning_loop import LearningLoop
from learning.statistics import power_analysis
from utils.cost_tracker import get_cost_tracker


def main():
    parser = argparse.ArgumentParser(description="Self-learning A/B loop")
    parser.add_argument("--iterations", type=int, default=5, help="Max learning iterations")
    parser.add_argument("--conversations", type=int, default=25, help="Conversations per variant")
    parser.add_argument("--variants", type=int, default=3, help="Variants per agent per iteration")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for deterministic scenarios")
    args = parser.parse_args()

    print("=" * 60)
    print("SELF-LEARNING A/B EVALUATION LOOP")
    print("=" * 60)
    print(f"  Iterations:    {args.iterations}")
    print(f"  Conversations: {args.conversations}")
    print(f"  Variants:      {args.variants}")
    print(f"  Seed:          {args.seed}")
    print()

    # Power analysis: justify sample size choice
    pa = power_analysis(
        effect_size=0.5,  # Cohen's d = 0.5 (medium effect)
        alpha=0.05,
        power=0.80,
        num_comparisons=args.variants,
    )
    print("POWER ANALYSIS")
    print(f"  Target effect size (Cohen's d): {pa['effect_size']}")
    print(f"  Alpha (Bonferroni-adjusted):    {pa['alpha_adj']}")
    print(f"  Target power:                   {pa['power']:.0%}")
    print(f"  Ideal N per group:              {pa['n_ideal']}")
    print(f"  Actual N per group:             {args.conversations}")
    print(f"  {pa['trade_off_note']}")
    print()

    # Enforce minimum N — running with <10 conversations produces unreliable
    # statistics (p-values will be meaningless, Cohen's d will be noisy).
    MIN_CONVERSATIONS = 10
    if args.conversations < MIN_CONVERSATIONS:
        print(f"WARNING: --conversations {args.conversations} is below minimum {MIN_CONVERSATIONS}.")
        print(f"  Power analysis requires N≥{pa['n_ideal']} for d=0.5 at 80% power.")
        print(f"  Forcing N={MIN_CONVERSATIONS} to avoid meaningless statistics.")
        args.conversations = MIN_CONVERSATIONS
        print()

    loop = LearningLoop(
        num_conversations=args.conversations,
        max_iterations=args.iterations,
        num_variants=args.variants,
        seed=args.seed,
    )

    summary = loop.run()

    print()
    print("=" * 60)
    print("LEARNING LOOP COMPLETE")
    print("=" * 60)
    print(f"  Iterations completed: {summary['iterations_completed']}")
    print(f"  Total adoptions:      {summary['total_adoptions']}")
    print(f"  Total spend:          ${summary['final_spend_usd']:.4f}")
    print()
    print("  Output files:")
    print("    evals_output/raw_scores.csv")
    print("    evals_output/decisions.csv")
    print("    evals_output/evolution_report.md")

    # Show cost breakdown
    report = get_cost_tracker().get_spend_report()
    if report.get("breakdown_by_category"):
        print()
        print("  Cost breakdown:")
        for cat, info in sorted(report["breakdown_by_category"].items()):
            print(f"    {cat:30s} ${info['cost']:.4f}  ({info['tokens']:,} tokens)")


if __name__ == "__main__":
    main()
