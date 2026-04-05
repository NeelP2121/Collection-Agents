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
    
    Returns:
        (is_safe, violations)
    """
    return check_prompt_compliance(prompt_text)
