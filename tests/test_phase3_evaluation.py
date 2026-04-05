"""
Phase 3: Self-Learning Test Harness
Creates synthetic borrower personas and evaluates agent performance.
"""

import json
import random
from datetime import datetime
from models.borrower_state import BorrowerContext
from agents.agent1_assessment import AssessmentAgent
from agents.agent2_resolution import ResolutionAgent
from agents.agent3_final_notice import FinalNoticeAgent
from summarizer.summarizer import Summarizer
from utils.config import TOKEN_BUDGET_CONFIG

class SyntheticBorrower:
    """Synthetic borrower persona for testing"""

    def __init__(self, persona_type: str):
        self.persona_type = persona_type
        self.setup_persona()
        self.conversation_history = []

    def setup_persona(self):
        """Configure borrower behavior based on persona type"""
        personas = {
            "cooperative": {
                "name": "Sarah Johnson",
                "phone": "555-0101",
                "employment": "employed",
                "income": "medium",
                "willingness": "high",
                "hardship": False,
                "response_style": "cooperative"
            },
            "combative": {
                "name": "Mike Rodriguez",
                "phone": "555-0102",
                "employment": "employed",
                "income": "high",
                "willingness": "low",
                "hardship": False,
                "response_style": "combative"
            },
            "evasive": {
                "name": "Jennifer Chen",
                "phone": "555-0103",
                "employment": "unemployed",
                "income": "low",
                "willingness": "medium",
                "hardship": True,
                "response_style": "evasive"
            },
            "distressed": {
                "name": "Robert Williams",
                "phone": "555-0104",
                "employment": "disabled",
                "income": "very_low",
                "willingness": "low",
                "hardship": True,
                "response_style": "distressed"
            }
        }

        config = personas[self.persona_type]
        self.name = config["name"]
        self.phone = config["phone"]
        self.employment = config["employment"]
        self.income = config["income"]
        self.willingness = config["willingness"]
        self.hardship = config["hardship"]
        self.response_style = config["response_style"]

    def get_response(self, turn: int, agent_message: str, context: dict) -> str:
        """Generate synthetic borrower response dynamically using LLM"""
        from utils.llm import call_llm
        from utils.config import get_model
        
        # We record the agent's message as "user" from the LLM's perspective
        self.conversation_history.append({"role": "user", "content": agent_message})
        
        system_prompt = f"""You are {self.name}, an individual who owes a debt but is currently acting {self.response_style}.
Your current employment is: {self.employment}.
Your approximate income is: ${self._income_to_amount()}.
Are you experiencing hardship? {'Yes' if self.hardship else 'No'}.

INSTRUCTIONS:
- Keep your responses under 3 sentences.
- Speak exactly as a real person talking to a debt collector would.
- Your persona style is: {self.response_style}.
- Do NOT break character as a borrower. Do NOT say 'as an AI'.
- The user is the debt collector."""

        try:
            response_text = call_llm(
                system=system_prompt,
                messages=self.conversation_history,
                model=get_model("evaluation"),
                max_tokens=150,
                context_category="synthetic_borrower"
            )
            # Record our own response as "assistant"
            self.conversation_history.append({"role": "assistant", "content": response_text})
            return response_text
        except Exception as e:
            print(f"Error generating synthetic response: {e}")
            return "I need more time to think about this."

    def _income_to_amount(self) -> str:
        """Convert income level to approximate amount"""
        amounts = {
            "very_low": "800/month",
            "low": "1500/month",
            "medium": "3000/month",
            "high": "5000/month"
        }
        return amounts.get(self.income, "2000/month")

class Phase3Evaluator:
    """Evaluates agent performance across synthetic scenarios"""

    def __init__(self):
        self.summarizer = Summarizer()
        self.personas = ["cooperative", "combative", "evasive", "distressed"]

    def run_evaluation_scenario(self, persona_type: str) -> dict:
        """Run complete 3-agent workflow with synthetic borrower"""
        print(f"\n=== Running {persona_type} scenario ===")

        # Create synthetic borrower
        borrower = SyntheticBorrower(persona_type)

        # Initialize borrower context
        borrower_context = BorrowerContext(
            name=borrower.name,
            phone=borrower.phone
        )

        # Add synthetic response function
        borrower_context.test_borrower_response_fn = borrower.get_response

        try:
            # Phase 1: Agent 1
            print("Running Agent 1...")
            agent1_result = AssessmentAgent().run_assessment_agent(borrower_context)

            # Phase 2: Summarize and Agent 2
            print("Summarizing Agent 1 → Agent 2...")
            agent1_handoff = self.summarizer.summarize_agent1_to_agent2(
                agent1_result["messages"],
                borrower_context.to_dict()
            )

            print("Running Agent 2...")
            borrower_context.update_from_handoff(agent1_handoff)
            agent2_result = ResolutionAgent().run_resolution_agent(borrower_context)

            # Check if resolved in Phase 2
            if agent2_result["outcome"] == "deal_agreed":
                final_outcome = "resolved_voice"
            else:
                # Phase 3: Summarize and Agent 3
                print("Summarizing Agent 2 → Agent 3...")
                agent2_handoff = self.summarizer.summarize_agent2_to_agent3(
                    {"agent1_handoff": agent1_handoff, "agent2_conversation": borrower_context.agent2_transcript or []},
                    borrower_context.to_dict()
                )

                print("Running Agent 3...")
                borrower_context.update_from_handoff(agent2_handoff)
                agent3_result = FinalNoticeAgent().run_final_notice_agent(borrower_context)

                final_outcome = agent3_result["outcome"]

            # Calculate metrics
            metrics = self.calculate_metrics(borrower_context, persona_type)

            return {
                "persona": persona_type,
                "outcome": final_outcome,
                "metrics": metrics,
                "borrower_context": borrower_context.to_dict(),
                "compliance_violations": len(borrower_context.compliance_violations),
                "total_turns": len(borrower_context.agent1_messages) + (borrower_context.agent2_transcript.count('\n') if borrower_context.agent2_transcript else 0) + len(borrower_context.agent3_messages)
            }

        except Exception as e:
            print(f"Error in {persona_type} scenario: {e}")
            return {
                "persona": persona_type,
                "outcome": "error",
                "error": str(e),
                "metrics": {},
                "compliance_violations": 0,
                "total_turns": 0
            }

    def calculate_metrics(self, borrower_context: BorrowerContext, persona_type: str) -> dict:
        """Calculate performance metrics for the scenario"""
        outcome = borrower_context.final_outcome

        # Base metrics
        metrics = {
            "resolution_rate": 1.0 if outcome in ["resolved_voice", "resolved"] else 0.0,
            "compliance_score": max(0, 1.0 - (len(borrower_context.compliance_violations) * 0.1)),
            "efficiency_score": min(1.0, 1.0 / max(1, len(borrower_context.agent1_messages) // 5)),  # Fewer turns = better
            "hardship_handling": 1.0 if borrower_context.hardship_detected and outcome != "unresolved" else 0.5,
        }

        # Persona-specific adjustments
        if persona_type == "cooperative":
            metrics["persona_satisfaction"] = 0.9 if outcome in ["resolved_voice", "resolved"] else 0.3
        elif persona_type == "combative":
            metrics["de_escalation"] = 0.8 if len(borrower_context.compliance_violations) == 0 else 0.4
        elif persona_type == "evasive":
            metrics["clarity_score"] = 0.7  # Assume good for now
        elif persona_type == "distressed":
            metrics["empathy_score"] = 0.8 if borrower_context.hardship_detected else 0.5

        # Overall score
        metrics["overall_score"] = sum(metrics.values()) / len(metrics)

        return metrics

    def run_full_evaluation(self) -> dict:
        """Run evaluation across all personas"""
        print("Starting Phase 3: True Synthetic Evaluation")
        print("=" * 50)

        results = {}
        for persona in self.personas:
            result = self.run_evaluation_scenario(persona)
            results[persona] = result

        # Aggregate results
        summary = self.generate_summary(results)

        # Reformulate into the format expected by Phase 4 learning loop
        formatted_eval = {
            "overall_resolution_rate": summary["resolution_rate"] * 100,
            "overall_compliance_score": summary["metrics"].get("avg_compliance_score", 0) * 100,
            "average_turns_per_scenario": summary["average_turns"],
            "scenarios": {},
            "recommendations": summary["recommendations"]
        }

        for k, v in results.items():
            formatted_eval["scenarios"][k] = {
                "result": "success" if v["outcome"] in ["resolved_voice", "resolved"] else "failure",
                "resolution_rate": 100 if v["outcome"] in ["resolved_voice", "resolved"] else 0,
                "compliance_score": v.get("metrics", {}).get("compliance_score", 0) * 100,
                "turns": v["total_turns"],
                "error": v.get("error")
            }

        return formatted_eval

    def generate_summary(self, results: dict) -> dict:
        """Generate summary statistics across all scenarios"""
        total_scenarios = len(results)
        resolved_count = sum(1 for r in results.values() if r["outcome"] in ["resolved_voice", "resolved"])
        compliance_violations = sum(r["compliance_violations"] for r in results.values())
        avg_turns = sum(r["total_turns"] for r in results.values()) / total_scenarios

        # Average metrics
        metric_keys = ["resolution_rate", "compliance_score", "efficiency_score", "overall_score"]
        avg_metrics = {}
        for key in metric_keys:
            values = [r["metrics"].get(key, 0) for r in results.values()]
            avg_metrics[f"avg_{key}"] = sum(values) / len(values)

        return {
            "total_scenarios": total_scenarios,
            "resolution_rate": resolved_count / total_scenarios,
            "total_compliance_violations": compliance_violations,
            "average_turns": avg_turns,
            "metrics": avg_metrics,
            "recommendations": self.generate_recommendations(avg_metrics)
        }

    def generate_recommendations(self, avg_metrics: dict) -> list:
        """Generate improvement recommendations based on metrics"""
        recommendations = []

        if avg_metrics.get("avg_resolution_rate", 0) < 0.7:
            recommendations.append("Improve negotiation strategies - resolution rate below 70%")

        if avg_metrics.get("avg_compliance_score", 0) < 0.9:
            recommendations.append("Address compliance violations - score below 90%")

        if avg_metrics.get("avg_efficiency_score", 0) < 0.6:
            recommendations.append("Optimize conversation length - too many turns per scenario")

        if avg_metrics.get("avg_overall_score", 0) < 0.75:
            recommendations.append("Overall performance needs improvement - consider prompt tuning")

        if not recommendations:
            recommendations.append("Performance is strong - consider advanced optimization")

        return recommendations

def run_phase3_evaluation():
    """Main entry point for Phase 3 evaluation"""
    evaluator = Phase3Evaluator()
    formatted_eval = evaluator.run_full_evaluation()

    # Save results
    with open("phase3_evaluation_results.json", "w") as f:
        json.dump(formatted_eval, f, indent=2, default=str)

    print("\n" + "=" * 50)
    print("PHASE 3 EVALUATION COMPLETE")
    print("=" * 50)
    print(f"Results saved to: phase3_evaluation_results.json")
    print(f"Overall Resolution Rate: {formatted_eval['overall_resolution_rate']:.1f}%")
    print(f"Average Compliance Score: {formatted_eval['overall_compliance_score']:.1f}%")

    print("\nRecommendations:")
    for rec in formatted_eval['recommendations']:
        print(f"• {rec}")

    return formatted_eval

if __name__ == "__main__":
    run_phase3_evaluation()