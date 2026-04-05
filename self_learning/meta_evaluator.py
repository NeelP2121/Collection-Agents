"""
Meta-evaluator: Compares prompt performance and selects best performers.
Determines which prompts should advance and which should be archived.
"""

import logging
from typing import Dict, List, Any, Tuple
from datetime import datetime
from models.learning_state import PromptVariant, EvaluationRound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MetaEvaluator:
    """
    Evaluates and ranks prompt variants based on test performance.
    Determines which prompts are "winners" and should be promoted.
    """
    
    def __init__(self):
        # Weights for different metrics
        self.weights = {
            "resolution_rate": 0.40,      # Most important: did it resolve?
            "compliance_score": 0.35,     # Critical: FDCPA violations?
            "conversation_efficiency": 0.15,  # Fewer turns better
            "borrower_satisfaction": 0.10    # Feedback sentiment
        }
        self.evolution_history = []
        
    def introspect_evaluation_methodology(self, evaluation_results: Dict[str, Any], insights: list) -> bool:
        """
        Darwin Godel Machine core: The system evaluates its own evaluation formula.
        Uses an LLM to analyze if its metric weights are correctly rewarding good behavior.
        """
        import json
        import re
        from utils.llm import call_llm
        from utils.config import LLM_MODELS
        
        system_prompt = f"""You are the Meta-Evaluator (Darwin Godel Machine) for an AI debt collector system.
Your job is to introspect the current evaluation metric weights and suggest adjustments if the metrics are flawed, misleading, or have blind spots.

CURRENT WEIGHTS:
{json.dumps(self.weights, indent=2)}

EVALUATION RESULTS FROM RECENT RUN:
Overall Resolution: {evaluation_results.get('overall_resolution_rate', 0)}%
Overall Compliance: {evaluation_results.get('overall_compliance_score', 0)}%

RECENT INSIGHTS IDENTIFIED:
{[insight.pattern for insight in insights[-5:]] if insights else 'None'}

INSTRUCTIONS:
1. Analyze if the current weights are producing false positives (e.g. high resolution but low compliance/aggressive tone) or false negatives.
2. Formulate an adjusted weight distribution (must sum to 1.0). For example, if compliance issues are pervasive, boost "compliance_score" and lower others.
3. Provide a clear reasoning for the adjustment. 
4. Return ONLY a JSON matching the format: {{"new_weights": {{"resolution_rate": float, "compliance_score": float, "conversation_efficiency": float, "borrower_satisfaction": float}}, "reasoning": "string"}}
"""
        try:
            response_text = call_llm(
                system=system_prompt,
                messages=[{"role": "user", "content": "Analyze the evaluation framework flaws and propose updated weights in JSON format."}],
                model=LLM_MODELS.get("evaluation", "claude-3-5-haiku-20241022"),
                max_tokens=400,
                context_category="meta_evaluation_introspection"
            )
            
            # Extract JSON block organically
            json_match = re.search(r'(\{.*new_weights.*\})', response_text, re.DOTALL | re.IGNORECASE)
            
            if json_match:
                data = json.loads(json_match.group(1))
                new_weights = data.get("new_weights", self.weights)
                
                # Sanitize and normalize weights to prevent gaming attacks from throwing NaNs
                total = sum(new_weights.values())
                if total > 0:
                    normalized = {k: v/total for k, v in new_weights.items()}
                    
                    # Store exact change in audit trail
                    self.evolution_history.append({
                        "timestamp": datetime.utcnow().isoformat(),
                        "old_weights": dict(self.weights),
                        "new_weights": normalized,
                        "reasoning": data.get("reasoning", "No string provided")
                    })
                    
                    self.weights = normalized
                    logger.info(f"Darwin Godel mechanism updated metric weights: {json.dumps(self.weights)}")
                    return True
        except Exception as e:
            logger.error(f"Meta-evaluator introspection failed: {e}")
            
        return False
    
    def compare_variants(self, 
                        base_variant: PromptVariant,
                        test_variants: List[PromptVariant],
                        evaluation_results: Dict[str, Any]) -> List[Tuple[PromptVariant, float, Dict[str, Any]]]:
        """
        Compare variants and return ranked list with scores.
        Returns: [(variant, score, metrics), ...]
        """
        comparison_results = []
        
        # Score base variant
        base_score, base_metrics = self._calculate_variant_score(
            base_variant, evaluation_results, is_base=True
        )
        comparison_results.append((base_variant, base_score, base_metrics))
        
        # Score test variants
        for variant in test_variants:
            score, metrics = self._calculate_variant_score(
                variant, evaluation_results, is_base=False
            )
            comparison_results.append((variant, score, metrics))
        
        # Sort by score descending
        comparison_results.sort(key=lambda x: x[1], reverse=True)
        
        return comparison_results
    
    def _calculate_variant_score(self, 
                                variant: PromptVariant,
                                evaluation_results: Dict[str, Any],
                                is_base: bool = False) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate composite score for a prompt variant.
        Returns: (score, metrics_dict)
        """
        metrics = {}
        
        # Extract metrics from evaluation results
        resolution_rate = evaluation_results.get("overall_resolution_rate", 0) / 100.0
        metrics["resolution_rate"] = resolution_rate
        
        compliance_score = evaluation_results.get("overall_compliance_score", 0) / 100.0
        metrics["compliance_score"] = compliance_score
        
        # Conversation efficiency (fewer turns is better)
        avg_turns = evaluation_results.get("average_turns_per_scenario", 3)
        efficiency = max(0, 1.0 - (avg_turns / 10.0))  # Normalize to 0-1
        metrics["conversation_efficiency"] = efficiency
        
        # Borrower satisfaction (inferred from resolution rate and compliance)
        satisfaction = (resolution_rate * 0.6 + compliance_score * 0.4)
        metrics["borrower_satisfaction"] = satisfaction
        
        # Calculate weighted score
        weighted_score = sum(
            metrics.get(metric_name, 0) * weight
            for metric_name, weight in self.weights.items()
        )
        
        # Add variant performance metrics if available
        if variant.evaluation_metrics:
            variant.performance_score = weighted_score
        else:
            # Base score if no specific metrics
            variant.performance_score = weighted_score * (0.9 if is_base else 1.0)
        
        metrics["weighted_score"] = weighted_score
        metrics["is_base"] = is_base
        
        return weighted_score, metrics
    
    def identify_winners(self, 
                        comparison_results: List[Tuple[PromptVariant, float, Dict[str, Any]]],
                        min_improvement: float = 0.02) -> List[PromptVariant]:
        """
        Identify prompt variants that significantly outperform the baseline.
        min_improvement: minimum score improvement to be considered a winner (default 2%)
        """
        winners = []
        
        if not comparison_results:
            return winners
        
        # Find base variant score
        base_score = None
        for variant, score, metrics in comparison_results:
            if metrics.get("is_base"):
                base_score = score
                break
        
        if base_score is None:
            return winners
        
        # Find variants that beat baseline
        for variant, score, metrics in comparison_results:
            if not metrics.get("is_base"):
                improvement = (score - base_score) / base_score if base_score > 0 else 0
                if improvement >= min_improvement:
                    logger.info(f"Winner identified: {variant.variant_id} (improvement: {improvement*100:.1f}%)")
                    winners.append(variant)
        
        return winners
    
    def select_best_prompt(self, comparison_results: List[Tuple[PromptVariant, float, Dict[str, Any]]]) -> PromptVariant:
        """Select the single best performing prompt variant"""
        if not comparison_results:
            return None
        
        best_variant, best_score, best_metrics = comparison_results[0]
        logger.info(f"Best prompt selected: {best_variant.variant_id} (score: {best_score:.3f})")
        return best_variant
    
    def generate_recommendations(self, comparison_results: List[Tuple[PromptVariant, float, Dict[str, Any]]],
                                winners: List[PromptVariant]) -> List[str]:
        """Generate actionable recommendations based on comparison"""
        recommendations = []
        
        if not comparison_results:
            return recommendations
        
        best_variant, best_score, best_metrics = comparison_results[0]
        
        # Check resolution rate
        if best_metrics["resolution_rate"] < 0.70:
            recommendations.append("Resolution rate below 70% target - review negotiation strategy")
        
        # Check compliance
        if best_metrics["compliance_score"] < 0.90:
            recommendations.append("Compliance score below 90% target - ensure FDCPA adherence")
        
        # Check efficiency
        if best_metrics["conversation_efficiency"] < 0.60:
            recommendations.append("Conversations too long - simplify prompts or add early exit conditions")
        
        # Check if any winners found
        if len(winners) == 0:
            recommendations.append("No variants showed significant improvement - try more aggressive changes")
        else:
            recommendations.append(f"Promoted {len(winners)} variant(s) that improved performance")
        
        return recommendations
    
    def should_continue_learning(self, evaluation_round: EvaluationRound, 
                                previous_best: EvaluationRound = None) -> bool:
        """
        Determine if learning loop should continue for more iterations.
        """
        # Continue if we haven't met targets
        if evaluation_round.overall_resolution_rate < 70:
            return True
        if evaluation_round.overall_compliance_score < 90:
            return True
        
        # Continue if we see improvement from previous round
        if previous_best:
            improvement = (evaluation_round.overall_resolution_rate - previous_best.overall_resolution_rate)
            if improvement > 1:  # At least 1% improvement
                return True
        
        return False
