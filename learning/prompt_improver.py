"""
Prompt improver: Generates optimized prompt variations based on evaluation results.
Uses meta-prompting to analyze failures and suggest improvements.
"""

import json
import logging
import uuid
from typing import Dict, List, Any
from datetime import datetime
from utils.llm import call_llm
from utils.config import get_model
from models.learning_state import PromptVariant, LearningInsight

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPT_ANALYSIS_SYSTEM = """You are an expert system designer analyzing debt collection AI agent performance.
Your task: Review evaluation results and suggest the most impactful prompt improvements.

Focus on:
1. Resolution Rate Impact: What changes would increase successful resolutions?
2. Compliance Violations: What language or approach causes FDCPA violations?
3. Borrower Response Patterns: What causes combative or evasive responses?
4. Negotiation Effectiveness: What settlement strategies work best?

Provide 5 specific, actionable prompt improvements, ranked by estimated impact.
"""

class PromptImprover:
    def __init__(self):
        self.model = get_model("evaluation")  # Use cheaper model for analysis
        
    def analyze_failures(self, evaluation_results: Dict[str, Any], agent_name: str, current_prompt: str) -> List[LearningInsight]:
        """
        Analyze why scenarios failed and extract insights.
        Returns list of LearningInsights with recommendations.
        """
        insights = []
        
        scenarios = evaluation_results.get("scenarios", {})
        
        for scenario_name, scenario_data in scenarios.items():
            if scenario_data.get("result") != "success":
                # Failed scenario - analyze why
                error = scenario_data.get("error", "Unknown error")
                
                # Determine scenario type (cooperative, combative, evasive, distressed)
                scenario_type = scenario_name.split("_")[0]
                
                insight = LearningInsight(
                    insight_id=str(uuid.uuid4()),
                    agent_name=agent_name,
                    pattern=f"Failed with {scenario_type} borrower",
                    impact="negative",
                    confidence=0.8,
                    failing_scenario=scenario_type,
                    extracted_at=datetime.utcnow()
                )
                
                # Determine recommendation based on scenario type
                if scenario_type == "combative":
                    insight.recommendation = "Reduce assertiveness, add empathy, focus on borrower control"
                elif scenario_type == "evasive":
                    insight.recommendation = "Add clarity and urgency, break down complex information"
                elif scenario_type == "distressed":
                    insight.recommendation = "Include hardship program references, offer flexibility"
                elif scenario_type == "cooperative":
                    insight.recommendation = "Streamline process, offer clear next steps"
                
                insights.append(insight)
        
        return insights
    
    def generate_prompt_variations(self, 
                                   agent_name: str, 
                                   current_prompt: str, 
                                   evaluation_results: Dict[str, Any],
                                   num_variations: int = 3) -> List[PromptVariant]:
        """
        Generate improved prompt variations using meta-prompting.
        Returns list of PromptVariant objects.
        """
        variations = []
        
        # Build analysis request
        analysis_request = f"""
CURRENT PROMPT:
{current_prompt}

EVALUATION RESULTS:
- Overall Resolution Rate: {evaluation_results.get('overall_resolution_rate', 0)}%
- Compliance Score: {evaluation_results.get('overall_compliance_score', 0)}%
- Total Test Scenarios: {len(evaluation_results.get('scenarios', {}))}
- Failed Scenarios: {sum(1 for s in evaluation_results.get('scenarios', {}).values() if s.get('result') != 'success')}

SCENARIO DETAILS:
{json.dumps(evaluation_results.get('scenarios', {}), indent=2)}

Generate {num_variations} specific prompt variations that address the failures above.
For each variation:
1. Identify what aspect of the current prompt needs improvement
2. Show exactly what text should change
3. Explain the improvement rationale
4. Estimate impact on resolution rate

Format as JSON array with objects: {{"variation_number": 1, "changes": "...", "new_prompt_section": "...", "rationale": "...", "estimated_impact": "..."}}
"""
        
        try:
            response = call_llm(
                system=PROMPT_ANALYSIS_SYSTEM,
                messages=[{"role": "user", "content": analysis_request}],
                model=self.model,
                max_tokens=2000,
                context_category="prompt_improvement",
            )
            
            # Parse response
            response_text = response if isinstance(response, str) else response.get("content", "")
            
            # Extract JSON from response
            try:
                json_str = response_text
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    json_str = response_text.split("```")[1].split("```")[0]
                
                variations_data = json.loads(json_str)
                
                # Create PromptVariant objects
                for i, var_data in enumerate(variations_data[:num_variations]):
                    variant = PromptVariant(
                        variant_id=f"{agent_name}_v{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_var{i+1}",
                        agent_name=agent_name,
                        prompt_version=int(datetime.utcnow().timestamp()),
                        prompt_text=self._create_modified_prompt(current_prompt, var_data),
                        base_prompt=current_prompt,
                        changes=var_data.get("rationale", "Improvement variant"),
                        evaluation_metrics={
                            "estimated_impact": var_data.get("estimated_impact", "unknown")
                        }
                    )
                    variations.append(variant)
                    logger.info(f"Generated prompt variant for {agent_name}: {variant.variant_id}")
            
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON variations: {e}. Using fallback variations.")
                variations = self._create_fallback_variations(agent_name, current_prompt, evaluation_results)
        
        except Exception as e:
            logger.error(f"Error generating prompt variations: {e}")
            variations = self._create_fallback_variations(agent_name, current_prompt, evaluation_results)
        
        return variations
    
    def _create_modified_prompt(self, base_prompt: str, variation_data: Dict[str, Any]) -> str:
        """Create modified prompt with suggested changes"""
        new_section = variation_data.get("new_prompt_section", "")
        if new_section:
            # Simple substitution - in production would be more sophisticated
            return base_prompt + "\n\nOPTIMIZED SECTION:\n" + new_section
        return base_prompt
    
    def _create_fallback_variations(self, agent_name: str, current_prompt: str, 
                                   evaluation_results: Dict[str, Any]) -> List[PromptVariant]:
        """Create fallback prompt variations if meta-prompting fails"""
        variations = []
        
        # Variation 1: Add empathy
        empathy_prompt = current_prompt.replace(
            "Professional, factual",
            "Professional but empathetic"
        ).replace(
            "final.",
            "final. We understand this is difficult."
        )
        
        variations.append(PromptVariant(
            variant_id=f"{agent_name}_empathy_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            agent_name=agent_name,
            prompt_version=1,
            prompt_text=empathy_prompt,
            base_prompt=current_prompt,
            changes="Added empathy and acknowledgment of borrower difficulty",
            evaluation_metrics={"type": "empathy_variant"}
        ))
        
        # Variation 2: Clarity focus
        clarity_prompt = current_prompt.replace(
            "Professional, factual, final.",
            "Clear, simple, urgent. Use short sentences and bullet points only."
        )
        
        variations.append(PromptVariant(
            variant_id=f"{agent_name}_clarity_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            agent_name=agent_name,
            prompt_version=1,
            prompt_text=clarity_prompt,
            base_prompt=current_prompt,
            changes="Simplified language for better comprehension",
            evaluation_metrics={"type": "clarity_variant"}
        ))
        
        # Variation 3: Offer flexibility
        flexibility_prompt = current_prompt + "\n\nIMPORTANT: Always present at least 2-3 settlement options with different timeframes and amounts. Be flexible."
        
        variations.append(PromptVariant(
            variant_id=f"{agent_name}_flexibility_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            agent_name=agent_name,
            prompt_version=1,
            prompt_text=flexibility_prompt,
            base_prompt=current_prompt,
            changes="Added emphasis on offering multiple flexible settlement options",
            evaluation_metrics={"type": "flexibility_variant"}
        ))
        
        return variations
    
    def generate_and_validate_variants(
        self,
        agent_name: str,
        current_prompt: str,
        evaluation_results: Dict[str, Any],
        num_variations: int = 3,
    ) -> List[PromptVariant]:
        """
        Generate variants and compliance-gate each prompt text before testing.
        Returns only variants that pass the compliance pre-flight.
        """
        from compliance.checker import verify_prompt_safety

        raw = self.generate_prompt_variations(
            agent_name, current_prompt, evaluation_results, num_variations
        )
        safe = []
        for v in raw:
            is_safe, violations = verify_prompt_safety(v.prompt_text)
            if is_safe:
                safe.append(v)
            else:
                logger.warning(f"Variant {v.variant_id} failed prompt compliance: {violations}")
        return safe
