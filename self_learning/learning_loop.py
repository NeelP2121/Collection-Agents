"""
Self-learning loop: Orchestrates the complete learning cycle.
Runs evaluation → analyzes failures → generates improved prompts → tests them → extracts insights.
"""

import logging
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from models.learning_state import LearningState, EvaluationRound
from self_learning.prompt_improver import PromptImprover
from self_learning.meta_evaluator import MetaEvaluator
from self_learning.feedback_aggregator import FeedbackAggregator
from agents.agent1_assessment import run_assessment_agent
from agents.agent2_resolution import run_resolution_agent
from agents.agent3_final_notice import run_final_notice_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LearningLoop:
    """
    Main orchestrator for the self-learning system.
    Manages iterative improvement of agent prompts.
    """
    
    def __init__(self, learning_state_path: str = "learning_state.json"):
        self.learning_state_path = learning_state_path
        self.learning_state = self._load_learning_state()
        
        self.prompt_improver = PromptImprover()
        self.meta_evaluator = MetaEvaluator()
        self.feedback_aggregator = FeedbackAggregator()
        
        # Current prompts for each agent
        self.current_prompts = {
            "agent1": None,  # Will be loaded from agents
            "agent2": None,
            "agent3": None
        }
    
    def _load_learning_state(self) -> LearningState:
        """Load learning state from disk or create new"""
        try:
            with open(self.learning_state_path, 'r') as f:
                data = json.load(f)
                # Reconstruct LearningState from dict
                learning_id = data.get("learning_id", str(uuid.uuid4()))
                return LearningState(learning_id=learning_id)
        except FileNotFoundError:
            return LearningState(learning_id=str(uuid.uuid4()))
    
    def _save_learning_state(self):
        """Save learning state to disk"""
        try:
            with open(self.learning_state_path, 'w') as f:
                json.dump(self.learning_state.to_dict(), f, indent=2, default=str)
                logger.info(f"Learning state saved to {self.learning_state_path}")
        except Exception as e:
            logger.error(f"Failed to save learning state: {e}")
    
    def run(self, 
            evaluation_results: Dict[str, Any],
            max_iterations: int = 3) -> Dict[str, Any]:
        """
        Main learning loop orchestrator.
        
        Args:
            evaluation_results: Results from Phase 3 evaluation
            max_iterations: Maximum improvement iterations to run
            
        Returns:
            Summary of learning outcomes
        """
        logger.info("=" * 60)
        logger.info("PHASE 4: SELF-LEARNING CYCLE")
        logger.info("=" * 60)
        
        # Record evaluation round
        evaluation_round = EvaluationRound(
            round_id=f"eval_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            evaluation_date=datetime.utcnow(),
            evaluation_results=evaluation_results,
            agents_tested=["agent1", "agent2", "agent3"],
            scenarios_tested=list(evaluation_results.get("scenarios", {}).keys()),
            overall_resolution_rate=evaluation_results.get("overall_resolution_rate", 0),
            overall_compliance_score=evaluation_results.get("overall_compliance_score", 0),
            recommendations=evaluation_results.get("recommendations", [])
        )
        
        self.learning_state.add_evaluation(evaluation_round)
        logger.info(f"Evaluation Round {self.learning_state.total_evaluations}: Resolution={evaluation_round.overall_resolution_rate:.1f}%, Compliance={evaluation_round.overall_compliance_score:.1f}%")
        
        # Learning iterations
        iteration = 0
        while iteration < max_iterations and self.meta_evaluator.should_continue_learning(
            evaluation_round, self.learning_state.best_evaluation
        ):
            iteration += 1
            logger.info(f"\n--- Learning Iteration {iteration} ---")
            
            # Step 1: Analyze failures and extract insights
            insights = self._extract_insights(evaluation_results)
            for insight in insights:
                self.learning_state.add_insight(insight)
            
            # Step 2: Generate prompt variations for each agent
            prompt_improvements = self._generate_prompt_improvements(
                evaluation_results, len(insights)
            )
            
            # Step 3: Meta-evaluate prompts (compare variants)
            winner_summary = self._evaluate_and_select_prompts(prompt_improvements)
            
            # Step 4: Apply winners to learning state
            for agent_name, winning_prompt in winner_summary.items():
                if winning_prompt:
                    self.learning_state.update_best_prompt(agent_name, winning_prompt.prompt_text)
                    logger.info(f"Promoted new best prompt for {agent_name}: {winning_prompt.variant_id}")
            
            # Record learning iteration
            self.learning_state.record_learning_iteration()
            
            # Step 5: Darwin Godel Machine Introspection - Evaluate our own evaluation methodology!
            self.meta_evaluator.introspect_evaluation_methodology(evaluation_results, self.learning_state.insights)
            
            self._save_learning_state()
            
            logger.info(f"Iteration {iteration} complete. Saved learning state.")
        
        # Generate final recommendations
        final_recommendations = self._synthesize_final_recommendations()
        
        summary = {
            "learning_iterations_completed": self.learning_state.learning_iterations,
            "total_evaluations": self.learning_state.total_evaluations,
            "final_resolution_rate": evaluation_round.overall_resolution_rate,
            "final_compliance_score": evaluation_round.overall_compliance_score,
            "total_insights_generated": len(self.learning_state.insights),
            "best_prompts_identified": len(self.learning_state.current_best_prompts),
            "final_recommendations": final_recommendations
        }
        
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 4 COMPLETE")
        logger.info(f"Learning iterations: {summary['learning_iterations_completed']}")
        logger.info(f"Insights generated: {summary['total_insights_generated']}")
        logger.info("=" * 60)
        
        return summary
    
    def _extract_insights(self, evaluation_results: Dict[str, Any]) -> list:
        """Extract insights from evaluation results"""
        all_insights = []
        
        for agent_name in ["agent1", "agent2", "agent3"]:
            insights = self.feedback_aggregator.extract_patterns(
                evaluation_results, agent_name
            )
            all_insights.extend(insights)
            logger.info(f"Extracted {len(insights)} insights for {agent_name}")
        
        return all_insights
    
    def _generate_prompt_improvements(self, evaluation_results: Dict[str, Any], 
                                     num_variations: int = 3) -> Dict[str, list]:
        """Generate improved prompt variations for each agent"""
        improvements = {}
        
        for agent_name in ["agent1", "agent2", "agent3"]:
            base_prompt = self.learning_state.current_best_prompts.get(agent_name, "")
            if not base_prompt:
                logger.warning(f"No base prompt found for {agent_name}, skipping variations")
                continue
            
            base_rate = evaluation_results.get("overall_resolution_rate", 0) / 100.0
            
            variations = self.prompt_improver.generate_prompt_variations(
                agent_name=agent_name,
                current_prompt=base_prompt,
                evaluation_results=evaluation_results,
                num_variations=num_variations
            )
            
            ranked_variations = self.prompt_improver.rank_prompts(variations, base_rate)
            improvements[agent_name] = ranked_variations
            
            logger.info(f"Generated {len(variations)} prompt variations for {agent_name}")
        
        return improvements
    
    def _evaluate_and_select_prompts(self, prompt_improvements: Dict[str, list]) -> Dict[str, Any]:
        """Meta-evaluate prompts and select winners for each agent"""
        winners = {}
        
        # For now, select top-ranked variant for each agent
        # In production, would A/B test these variants
        for agent_name, variants in prompt_improvements.items():
            if variants:
                best_variant = variants[0]  # Already ranked
                winners[agent_name] = best_variant
                logger.info(f"Selected best variant for {agent_name}: {best_variant.variant_id}")
        
        return winners
    
    def _synthesize_final_recommendations(self) -> list:
        """Generate final actionable recommendations from all insights"""
        recommendations = []
        
        # Group insights by theme
        theme_groups = self.feedback_aggregator.group_insights_by_theme(self.learning_state.insights)
        
        # Generate theme-based recommendations
        for theme, insights in theme_groups.items():
            if insights:
                top_insight = sorted(insights, key=lambda i: i.confidence, reverse=True)[0]
                if top_insight.recommendation:
                    recommendations.append(f"[{theme.upper()}] {top_insight.recommendation}")
        
        # Add scenario-specific recommendations
        success_rates = self.feedback_aggregator.track_scenario_success_rates(self.learning_state.insights)
        for scenario, rate in success_rates.items():
            if rate < 0.70:
                recommendations.append(f"Improve {scenario} scenario handling (current: {rate*100:.0f}%)")
        
        return recommendations
