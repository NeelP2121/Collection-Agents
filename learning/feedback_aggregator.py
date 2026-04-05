"""
Feedback aggregator: Learns patterns from evaluation results across scenarios and personas.
Identifies which approaches work for which borrower types.
"""

import logging
from typing import Dict, List, Any
from models.learning_state import LearningInsight

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FeedbackAggregator:
    """
    Analyzes feedback patterns across evaluation rounds.
    Builds knowledge about what works for different scenarios.
    """
    
    def __init__(self):
        self.scenario_types = ["cooperative", "combative", "evasive", "distressed"]
        self.agent_names = ["agent1", "agent2", "agent3"]
    
    def extract_patterns(self, evaluation_results: Dict[str, Any], 
                        agent_name: str) -> List[LearningInsight]:
        """
        Analyze evaluation results and extract learning patterns.
        """
        insights = []
        scenarios = evaluation_results.get("scenarios", {})
        
        # Analyze success patterns
        successful_scenarios = {}
        failed_scenarios = {}
        
        for scenario_name, scenario_data in scenarios.items():
            scenario_type = scenario_name.split("_")[0]
            
            if scenario_type not in successful_scenarios:
                successful_scenarios[scenario_type] = []
                failed_scenarios[scenario_type] = []
            
            if scenario_data.get("result") == "success":
                successful_scenarios[scenario_type].append(scenario_data)
            else:
                failed_scenarios[scenario_type].append(scenario_data)
        
        # Generate insights for each scenario type
        for scenario_type in self.scenario_types:
            success_count = len(successful_scenarios.get(scenario_type, []))
            fail_count = len(failed_scenarios.get(scenario_type, []))
            total = success_count + fail_count
            
            if total == 0:
                continue
            
            success_rate = success_count / total
            
            if success_rate > 0.75:
                # Strong performance - what's working?
                insight = LearningInsight(
                    insight_id=f"success_{agent_name}_{scenario_type}",
                    agent_name=agent_name,
                    pattern=f"Strong performance with {scenario_type} borrowers ({success_rate*100:.0f}% success)",
                    impact="positive",
                    confidence=min(0.95, 0.6 + (success_count * 0.1)),
                    success_scenario=scenario_type,
                    recommendation="Maintain current approach for this scenario type"
                )
                insights.append(insight)
                logger.info(f"Pattern found: {agent_name} succeeds with {scenario_type} (success rate: {success_rate*100:.0f}%)")
            
            elif success_rate < 0.25:
                # Poor performance - what needs to change?
                insight = LearningInsight(
                    insight_id=f"failure_{agent_name}_{scenario_type}",
                    agent_name=agent_name,
                    pattern=f"Poor performance with {scenario_type} borrowers ({success_rate*100:.0f}% success)",
                    impact="negative",
                    confidence=min(0.95, 0.6 + (fail_count * 0.1)),
                    failing_scenario=scenario_type,
                    recommendation=self._get_scenario_recommendation(scenario_type, agent_name)
                )
                insights.append(insight)
                logger.info(f"Problem found: {agent_name} struggles with {scenario_type} (success rate: {success_rate*100:.0f}%)")
        
        # Identify cross-agent patterns
        cross_agent_insights = self._analyze_cross_agent_patterns(evaluation_results)
        insights.extend(cross_agent_insights)
        
        return insights
        
    def _analyze_cross_agent_patterns(self, evaluation_results: Dict[str, Any]) -> List[LearningInsight]:
        """Analyze patterns across agents (placeholder for advanced logic)."""
        return []
    
    def _get_scenario_recommendation(self, scenario_type: str, agent_name: str) -> str:
        """Get tailored recommendation for a failing scenario"""
        recommendations = {
            "cooperative": "Already cooperative - streamline process, add efficiency gains",
            "combative": "Tone down pressure, add empathy, emphasize borrower choice and control",
            "evasive": "Use clearer language, shorter sentences, explicit consequences, urgency",
            "distressed": "Acknowledge hardship, offer flexible options, include hardship program references"
        }
        
        return recommendations.get(scenario_type, "Investigate specific failure reasons")
    
    def group_insights_by_theme(self, insights: List[LearningInsight]) -> Dict[str, List[LearningInsight]]:
        """Group insights by common themes for easier analysis"""
        themes = {
            "tone_and_approach": [],
            "clarity_and_language": [],
            "offer_and_negotiation": [],
            "compliance_and_ethics": [],
            "scenario_specific": [],
            "efficiency": []
        }
        
        for insight in insights:
            theme = self._classify_insight_theme(insight)
            themes[theme].append(insight)
        
        return themes
    
    def _classify_insight_theme(self, insight: LearningInsight) -> str:
        """Classify an insight into a theme"""
        pattern_lower = insight.pattern.lower()
        
        if any(word in pattern_lower for word in ["tone", "empathy", "pressure", "approach"]):
            return "tone_and_approach"
        elif any(word in pattern_lower for word in ["clarity", "language", "clear", "simple"]):
            return "clarity_and_language"
        elif any(word in pattern_lower for word in ["offer", "settle", "negotiat"]):
            return "offer_and_negotiation"
        elif any(word in pattern_lower for word in ["compliance", "violation", "fdcpa"]):
            return "compliance_and_ethics"
        elif any(word in pattern_lower for word in ["turn", "efficient", "long", "short"]):
            return "efficiency"
        else:
            return "scenario_specific"
    
    def synthesize_recommendations(self, insights: List[LearningInsight]) -> Dict[str, str]:
        """Create synthesized recommendations from all insights"""
        recommendations = {
            "agent1_focus": "Continue identity verification focus",
            "agent2_focus": "Focus on negotiation effectiveness",
            "agent3_focus": "Emphasize finality and consequences",
        }
        
        # Count by theme
        themes = self.group_insights_by_theme(insights)
        
        # Identify strongest patterns
        strongest_patterns = {
            theme: sorted(insight_list, key=lambda i: i.confidence, reverse=True)
            for theme, insight_list in themes.items()
        }
        
        # Generate synthesized recommendations
        if strongest_patterns["tone_and_approach"]:
            top_insight = strongest_patterns["tone_and_approach"][0]
            recommendations["tone_strategy"] = top_insight.recommendation or "Adjust tone based on scenario type"
        
        if strongest_patterns["clarity_and_language"]:
            top_insight = strongest_patterns["clarity_and_language"][0]
            recommendations["clarity_strategy"] = top_insight.recommendation or "Simplify language"
        
        if strongest_patterns["offer_and_negotiation"]:
            top_insight = strongest_patterns["offer_and_negotiation"][0]
            recommendations["negotiation_strategy"] = top_insight.recommendation or "Optimize settlement offers"
        
        return recommendations
    
    def track_scenario_success_rates(self, insights: List[LearningInsight]) -> Dict[str, float]:
        """Calculate success rates by scenario type from insights"""
        scenario_success = {}
        scenario_totals = {}
        
        for insight in insights:
            if insight.success_scenario:
                scenario = insight.success_scenario
                if scenario not in scenario_success:
                    scenario_success[scenario] = 0
                    scenario_totals[scenario] = 0
                
                scenario_success[scenario] += 1 if insight.impact == "positive" else 0
                scenario_totals[scenario] += 1
        
        # Calculate rates
        success_rates = {
            scenario: (scenario_success.get(scenario, 0) / total if total > 0 else 0)
            for scenario, total in scenario_totals.items()
        }
        
        return success_rates
