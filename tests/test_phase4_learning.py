"""
Comprehensive test for Phase 3 → Phase 4 workflow.
Runs evaluation, extracts insights, and demonstrates self-learning cycle.
"""

import os
import json
import sys
from datetime import datetime

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.borrower_state import BorrowerContext
from self_learning.learning_loop import LearningLoop
from self_learning.feedback_aggregator import FeedbackAggregator
from self_learning.meta_evaluator import MetaEvaluator

# Mock evaluation results (would come from test_phase3_evaluation.py)
MOCK_EVALUATION_RESULTS = {
    "overall_resolution_rate": 45.0,  # 45% - below target of 70%
    "overall_compliance_score": 82.0,  # 82% - below target of 90%
    "average_turns_per_scenario": 4.2,
    "scenarios": {
        "cooperative_1": {
            "result": "success",
            "resolution_rate": 100,
            "compliance_score": 95,
            "turns": 3,
            "notes": "Smooth interaction, good offer acceptance"
        },
        "cooperative_2": {
            "result": "success",
            "resolution_rate": 100,
            "compliance_score": 92,
            "turns": 3,
            "notes": "Quick resolution with settlement"
        },
        "combative_1": {
            "result": "failure",
            "resolution_rate": 0,
            "compliance_score": 65,
            "turns": 8,
            "error": "Too assertive, borrower became defensive",
            "notes": "Escalated tension rather than calming"
        },
        "combative_2": {
            "result": "failure",
            "resolution_rate": 0,
            "compliance_score": 70,
            "turns": 7,
            "error": "Threats perceived as aggressive",
            "notes": "Violated borrower's comfort zone"
        },
        "evasive_1": {
            "result": "partial",
            "resolution_rate": 25,
            "compliance_score": 88,
            "turns": 6,
            "notes": "Borrower remained guarded, partial commitment"
        },
        "evasive_2": {
            "result": "failure",
            "resolution_rate": 0,
            "compliance_score": 85,
            "turns": 8,
            "error": "Message clarity insufficient for evasive borrower",
            "notes": "Too many options confused borrower"
        },
        "distressed_1": {
            "result": "success",
            "resolution_rate": 100,
            "compliance_score": 90,
            "turns": 5,
            "notes": "Recognized hardship, offered flexibility"
        },
        "distressed_2": {
            "result": "failure",
            "resolution_rate": 0,
            "compliance_score": 72,
            "turns": 9,
            "error": "Insufficient empathy, felt pressured despite hardship",
            "notes": "Needed more hardship program references"
        }
    },
    "recommendations": [
        "Improve negotiation strategies - resolution rate below 70%",
        "Address compliance violations - score below 90%",
        "Reduce conversation length - too many turns per scenario"
    ]
}

def run_phase4_test():
    """Run Phase 4 self-learning evaluation demonstration"""
    
    print("\n" + "=" * 70)
    print("PHASE 4: SELF-LEARNING EVALUATION")
    print("=" * 70)
    print()
    
    # Initialize learning loop
    learning_loop = LearningLoop()
    
    # Initialize aggregator for standalone analysis
    aggregator = FeedbackAggregator()
    evaluator = MetaEvaluator()
    
    print("STEP 1: ANALYZE EVALUATION RESULTS")
    print("-" * 70)
    print(f"Resolution Rate: {MOCK_EVALUATION_RESULTS['overall_resolution_rate']:.1f}%")
    print(f"Compliance Score: {MOCK_EVALUATION_RESULTS['overall_compliance_score']:.1f}%")
    print(f"Scenarios Evaluated: {len(MOCK_EVALUATION_RESULTS['scenarios'])}")
    
    success_count = sum(1 for s in MOCK_EVALUATION_RESULTS['scenarios'].values() if s['result'] == 'success')
    print(f"Successful Scenarios: {success_count}/{len(MOCK_EVALUATION_RESULTS['scenarios'])}")
    print()
    
    # Extract insights per agent
    print("STEP 2: EXTRACT LEARNING INSIGHTS")
    print("-" * 70)
    
    for agent_name in ["agent1", "agent2", "agent3"]:
        insights = aggregator.extract_patterns(MOCK_EVALUATION_RESULTS, agent_name)
        print(f"\n{agent_name.upper()} - {len(insights)} insights extracted:")
        for insight in insights:
            confidence_pct = int(insight.confidence * 100)
            print(f"  • Pattern: {insight.pattern}")
            print(f"    Impact: {insight.impact} | Confidence: {confidence_pct}%")
            if insight.recommendation:
                print(f"    → {insight.recommendation}")
    
    print()
    print("STEP 3: ANALYZE SCENARIO PERFORMANCE")
    print("-" * 70)
    
    # Break down by scenario type
    scenario_types = ["cooperative", "combative", "evasive", "distressed"]
    scenario_performance = {}
    
    for scenario_type in scenario_types:
        matching_scenarios = {k: v for k, v in MOCK_EVALUATION_RESULTS['scenarios'].items() 
                             if k.startswith(scenario_type)}
        
        if matching_scenarios:
            success_count = sum(1 for s in matching_scenarios.values() if s['result'] == 'success')
            total = len(matching_scenarios)
            success_rate = (success_count / total) * 100 if total > 0 else 0
            scenario_performance[scenario_type] = success_rate
            
            status = "✓ Strong" if success_rate >= 75 else "⚠ Needs Work" if success_rate >= 50 else "✗ Critical"
            print(f"\n{scenario_type.upper()}: {success_rate:.0f}% success {status}")
            print(f"  Scenarios: {total} | Successful: {success_count}")
            
            # Show specific failures
            failures = [k for k, v in matching_scenarios.items() if v['result'] == 'failure']
            if failures:
                for fail_key in failures:
                    error = matching_scenarios[fail_key].get('error', 'Unknown error')
                    print(f"  ✗ {fail_key}: {error}")
    
    print()
    print("STEP 4: IDENTIFY IMPROVEMENT PRIORITIES")
    print("-" * 70)
    
    # Rank scenarios by performance gap
    target_rate = 70  # 70% resolution target
    gaps = [(stype, target_rate - rate) for stype, rate in scenario_performance.items()]
    gaps.sort(key=lambda x: x[1], reverse=True)
    
    print("\nPriority Improvements (by performance gap):")
    for stype, gap in gaps:
        if gap > 0:
            print(f"  1. {stype.upper()}: +{gap:.0f}% needed to reach 70% target")
    
    print()
    print("STEP 5: RECOMMENDED PROMPT IMPROVEMENTS")
    print("-" * 70)
    
    improvement_map = {
        "combative": {
            "issue": "Perceived as too aggressive",
            "changes": [
                "Reduce threatening language",
                "Add empathy statements",
                "Offer borrower choice/control",
                "Use softer phrasing for consequences"
            ]
        },
        "evasive": {
            "issue": "Too many options causes confusion",
            "changes": [
                "Simplify to 1-2 clear options",
                "Use shorter sentences",
                "Add explicit decision deadline",
                "Remove complex qualification language"
            ]
        },
        "distressed": {
            "issue": "Insufficient hardship accommodation",
            "changes": [
                "Lead with hardship program availability",
                "Use warmer, more supportive tone",
                "Emphasize flexibility and options",
                "Include hardship specialist contact"
            ]
        }
    }
    
    for scenario_type, rate in sorted(scenario_performance.items(), key=lambda x: x[1]):
        if rate < 70 and scenario_type in improvement_map:
            print(f"\n{scenario_type.upper()} ({rate:.0f}% → target 70%):")
            print(f"Issue: {improvement_map[scenario_type]['issue']}")
            print("Recommended changes:")
            for change in improvement_map[scenario_type]['changes']:
                print(f"  • {change}")
    
    print()
    print("STEP 6: LEARNING LOOP EXECUTION")
    print("-" * 70)
    
    # Run learning loop (demonstrates full cycle)
    try:
        summary = learning_loop.run(MOCK_EVALUATION_RESULTS, max_iterations=1)
        
        print("\nLearning Cycle Complete:")
        print(f"  Iterations: {summary['learning_iterations_completed']}")
        print(f"  Insights Generated: {summary['total_insights_generated']}")
        print(f"  Best Prompts Identified: {summary['best_prompts_identified']}")
    except Exception as e:
        print(f"Learning loop execution: {e}")
        print("(Note: Requires full agent implementation and API access)")
    
    print()
    print("=" * 70)
    print("PHASE 4 ANALYSIS COMPLETE")
    print("=" * 70)
    print()
    print("NEXT STEPS:")
    print("1. Implement identified prompt improvements")
    print("2. A/B test improved prompts against baseline")
    print("3. Re-run Phase 3 evaluation with updated prompts")
    print("4. Compare metrics and validate improvements")
    print("5. Iterate until resolution rate reaches 70% + compliance at 90%")
    print()
    
    # Save analysis report
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "evaluation_results": MOCK_EVALUATION_RESULTS,
        "scenario_performance": scenario_performance,
        "improvement_priorities": [{"scenario": s, "gap": g} for s, g in gaps],
        "recommendations": improvement_map,
        "learning_summary": summary if 'summary' in locals() else None
    }
    
    report_path = "phase4_learning_analysis.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"Analysis report saved to: {report_path}")

if __name__ == "__main__":
    run_phase4_test()
