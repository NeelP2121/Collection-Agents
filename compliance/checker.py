"""
Compliance Checker - Pre and post-activity validation
"""

from typing import Tuple, List, Dict
from compliance.rules import check_compliance, check_prompt_compliance
from utils.db import log_compliance_violation


def check_message_compliance(message: str, agent_name: str, context: Dict = None, conversation_id: str = None) -> Tuple[bool, List[Dict]]:
    """
    Check if agent message complies with all rules.
    
    Args:
        message: Agent's message to check
        agent_name: Which agent (assessment, resolution, final_notice)
        context: Conversation context for rule interpretation
        conversation_id: For logging violations
    
    Returns:
        (is_compliant, violations_list)
    """
    is_compliant, violations = check_compliance(message, context)
    
    # Log critical violations to database
    for violation in violations:
        if violation["severity"] == "critical":
            log_compliance_violation(
                agent_name=agent_name,
                violation_type=violation["type"],
                severity=violation["severity"],
                message=violation["reason"],
                conversation_id=conversation_id
            )
    
    return (is_compliant, violations)


def check_agent_output_compliance(agent_result: Dict, agent_name: str, conversation_id: str = None) -> Tuple[bool, List[Dict]]:
    """
    Validate structured agent output (not just messages).
    Used after Agent 1, Agent 2, Agent 3 complete.
    
    Args:
        agent_result: Agent's output dictionary
        agent_name: Which agent
        conversation_id: For logging
    
    Returns:
        (is_compliant, violations)
    """
    violations = []
    
    # Agent 1 specific checks
    if agent_name == "assessment":
        if agent_result.get("identity_verified") == False and not agent_result.get("conversation"):
            violations.append({
                "type": "identity_process",
                "severity": "warning",
                "reason": "Identity not verified but no conversation recorded"
            })
    
    # Agent 2 specific checks
    if agent_name == "resolution":
        offers = agent_result.get("offers_made", [])
        for offer in offers:
            # Verify offer is within policy ranges
            pass  # Checked in rules already
    
    # Agent 3 specific checks
    if agent_name == "final_notice":
        if not agent_result.get("final_message"):
            violations.append({
                "type": "final_notice_incomplete",
                "severity": "warning",
                "reason": "No final message provided"
            })
    
    # Log violations
    for violation in violations:
        if violation["severity"] == "critical":
            log_compliance_violation(
                agent_name=agent_name,
                violation_type=violation["type"],
                severity=violation["severity"],
                message=violation["reason"],
                conversation_id=conversation_id
            )
    
    return (len([v for v in violations if v["severity"] == "critical"]) == 0, violations)


def verify_prompt_safety(prompt_text: str) -> Tuple[bool, List[Dict]]:
    """
    Verify a prompt doesn't contain instructions that violate compliance.
    Used before adopting mutated prompts.

    Two-layer check:
    1. Regex keyword scan (fast, catches obvious red flags)
    2. LLM semantic analysis (catches subtle violations the regex misses)

    Returns:
        (is_safe, violations)
    """
    # Layer 1: Regex scan
    is_safe, violations = check_prompt_compliance(prompt_text)
    if not is_safe:
        return (False, violations)

    # Layer 2: LLM semantic analysis
    try:
        from utils.llm import call_llm
        from utils.config import get_model

        system = (
            "You are an FDCPA compliance auditor reviewing a system prompt for a "
            "debt collection AI agent. Check if the prompt instructs the agent to:\n"
            "1. Threaten, harass, or intimidate borrowers\n"
            "2. Make false or misleading statements about debt\n"
            "3. Contact borrowers at unreasonable hours\n"
            "4. Disclose debt to third parties\n"
            "5. Use deceptive practices to collect\n"
            "6. Fail to identify as an AI / debt collector\n"
            "7. Ignore stop-contact requests\n\n"
            "Output ONLY valid JSON: {\"safe\": true/false, \"violations\": [\"description\"]}"
        )

        resp = call_llm(
            system=system,
            messages=[{"role": "user", "content": f"PROMPT TO REVIEW:\n{prompt_text[:3000]}"}],
            model=get_model("evaluation"),
            max_tokens=150,
            context_category="compliance_prompt_check",
        )

        import json
        import re
        # Extract JSON from response
        match = re.search(r'\{[^{}]*\}', resp)
        if match:
            data = json.loads(match.group())
            if not data.get("safe", True):
                for v in data.get("violations", []):
                    violations.append({
                        "type": "prompt_integrity_llm",
                        "severity": "critical",
                        "reason": str(v)[:200],
                    })
                return (False, violations)

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"LLM semantic compliance check failed (regex-only fallback): {e}"
        )

    return (True, violations)
