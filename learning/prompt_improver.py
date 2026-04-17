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

PROMPT_ANALYSIS_SYSTEM = """You are an expert system designer optimizing debt collection AI agent prompts.
Your task: Analyze evaluation results and produce COMPLETE rewritten prompts that improve performance.

Focus on:
1. Resolution Rate: What phrasing, tone, or strategy changes increase successful resolutions?
2. Compliance: What language causes FDCPA violations? Ensure AI disclosure, no false threats.
3. Borrower Handling: How should the agent adapt to combative, evasive, or distressed borrowers?
4. Negotiation: What settlement presentation strategies work best?

CRITICAL: Each variation must be a COMPLETE, standalone system prompt — not a patch or appendix.
Keep prompts concise (under 800 tokens). Make surgical, targeted changes — don't rewrite everything.
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
        
        # Summarize scenario failures concisely to avoid bloating the prompt
        scenario_summary = []
        for name, data in evaluation_results.get("scenarios", {}).items():
            status = data.get("result", "unknown")
            score = data.get("composite_score", "?")
            scenario_summary.append(f"  {name}: {status} (score={score})")
        scenario_text = "\n".join(scenario_summary[:15]) if scenario_summary else "  No scenario data available."

        # Format dimension scores if available
        dim_scores = evaluation_results.get("dimension_scores", {})
        if dim_scores:
            dim_text = "\n".join(f"  {dim}: {val:.2f}/1.00" for dim, val in sorted(dim_scores.items(), key=lambda x: x[1]))
            dim_section = f"\nDIMENSION SCORES (lowest = biggest opportunity):\n{dim_text}\n"
        else:
            dim_section = ""

        analysis_request = f"""
AGENT: {agent_name}

CURRENT PROMPT:
{current_prompt}

EVALUATION RESULTS:
- Resolution Rate: {evaluation_results.get('overall_resolution_rate', 0):.0f}%
- Compliance Score: {evaluation_results.get('overall_compliance_score', 0):.0f}%
- Mean Composite: {evaluation_results.get('mean_composite', 0):.3f}
{dim_section}
SCENARIO BREAKDOWN:
{scenario_text}

Generate {num_variations} COMPLETE rewritten system prompts. Each must be a standalone replacement
for the current prompt — not a patch or appendix. Target the LOWEST scoring dimensions above.

Format as JSON array:
[
  {{
    "variation_number": 1,
    "full_prompt": "The complete rewritten system prompt...",
    "change_description": "What was changed and why",
    "rationale": "Expected impact on scores"
  }}
]
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
                    # Prefer full_prompt (complete rewrite) over new_prompt_section (append)
                    prompt_text = var_data.get("full_prompt") or self._create_modified_prompt(current_prompt, var_data)
                    variant = PromptVariant(
                        variant_id=f"{agent_name}_v{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_var{i+1}",
                        agent_name=agent_name,
                        prompt_version=int(datetime.utcnow().timestamp()),
                        prompt_text=prompt_text,
                        base_prompt=current_prompt,
                        changes=var_data.get("change_description", var_data.get("rationale", "Improvement variant")),
                        evaluation_metrics={
                            "estimated_impact": var_data.get("rationale", "unknown")
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
