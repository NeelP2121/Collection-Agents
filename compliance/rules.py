"""
FDCPA-Aligned Compliance Rules for Collections Agents
8 core compliance rules enforced before and after agent outputs
"""

import re
from typing import List, Dict, Tuple
from enum import Enum


class ViolationType(Enum):
    IDENTITY_DISCLOSURE = "identity_disclosure"
    FALSE_THREATS = "false_threats"
    HARASSMENT = "harassment"
    MISLEADING_TERMS = "misleading_terms"
    SENSITIVE_SITUATIONS = "sensitive_situations"
    RECORDING_DISCLOSURE = "recording_disclosure"
    PROFESSIONAL_COMPOSURE = "professional_composure"
    DATA_PRIVACY = "data_privacy"


class ComplianceRule:
    """Base compliance rule"""
    
    def __init__(self, name: str, violation_type: ViolationType, severity: str = "warning"):
        self.name = name
        self.violation_type = violation_type
        self.severity = severity  # "critical" or "warning"
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """
        Check if message complies with rule.
        Returns: (is_compliant, reason_if_violation)
        """
        raise NotImplementedError


class IdentityDisclosureRule(ComplianceRule):
    """Rule 1: Agent must disclose it's an AI on first message"""
    
    def __init__(self):
        super().__init__("Identity Disclosure", ViolationType.IDENTITY_DISCLOSURE, "critical")
        self.ai_disclosure_patterns = [
            r"i\s+am\s+an?\s+ai",
            r"i\s+am\s+a\s+bot",
            r"this\s+is\s+an?\s+automated",
            r"powered\s+by\s+ai",
            r"ai-powered\s+agent",
        ]
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """Check first message includes AI disclosure"""
        # Only check at start of conversation (first turn)
        if context and context.get("turn_number", 0) > 0:
            return (True, "")  # Skip check after first turn
        
        message_lower = message.lower()
        for pattern in self.ai_disclosure_patterns:
            if re.search(pattern, message_lower):
                return (True, "")
        
        return (False, "Agent did not disclose it is an AI on first message")


class NoFalseThreatsRule(ComplianceRule):
    """Rule 2: No false threats (only documented next steps)"""
    
    def __init__(self):
        super().__init__("No False Threats", ViolationType.FALSE_THREATS, "critical")
        self.threat_patterns = [
            r"will\s+(sue|prosecute|arrest|jail|imprison)",
            r"we\s+will\s+take\s+legal\s+action",
            r"we\s+will\s+garnish\s+your\s+wages",
            r"we\s+will\s+seize\s+your",
            r"this\s+is\s+a\s+legal\s+threat",
            r"we\s+will\s+report\s+you\s+to\s+the\s+police",
        ]
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """Check no fabricated threats"""
        message_lower = message.lower()
        
        # Check for threatening language
        for pattern in self.threat_patterns:
            if re.search(pattern, message_lower):
                # Verify it's next step in workflow (from context)
                documented_steps = context.get("documented_next_steps", []) if context else []
                if "legal" not in documented_steps:
                    return (False, f"Threat detected but not documented workflow step")
        
        return (True, "")


class NoHarassmentRule(ComplianceRule):
    """Rule 3: Stop if borrower requests no contact"""
    
    def __init__(self):
        super().__init__("No Harassment", ViolationType.HARASSMENT, "critical")
        self.stop_patterns = [
            r"stop\s+(calling|contacting|bothering)",
            r"do\s+not\s+call\s+me",
            r"please\s+stop",
            r"cease\s+and\s+desist",
            r"i\s+don'?t\s+want\s+to\s+hear\s+from\s+you",
        ]
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """Check if borrower asked agent to stop but agent continued"""
        borrower_said_stop = context.get("borrower_stop_requested", False) if context else False
        
        if borrower_said_stop:
            # If borrower asked to stop, agent should NOT continue with collection attempts
            collection_phrases = [
                r"can\s+you\s+pay",
                r"settlement",
                r"payment\s+plan",
                r"you\s+owe",
                r"balance\s+due",
            ]
            message_lower = message.lower()
            for phrase in collection_phrases:
                if re.search(phrase, message_lower):
                    return (False, "Agent continued collection attempt after borrower requested stop")
        
        return (True, "")


class NoMisleadingTermsRule(ComplianceRule):
    """Rule 4: Settlement offers within policy-defined ranges"""
    
    def __init__(self):
        super().__init__("No Misleading Terms", ViolationType.MISLEADING_TERMS, "critical")
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """Check settlement offers are within policy ranges"""
        if not context or "settlement_offer" not in context:
            return (True, "")
        
        offer = context["settlement_offer"]
        policy_ranges = context.get("policy_ranges", {})
        
        # Check lump-sum discount
        if "lump_sum_discount_pct" in offer:
            discount = offer["lump_sum_discount_pct"]
            min_allowed = policy_ranges.get("lump_sum_discount_min_pct", 0.15)
            max_allowed = policy_ranges.get("lump_sum_discount_max_pct", 0.40)
            
            if discount < min_allowed or discount > max_allowed:
                return (False, f"Lump-sum discount outside policy range")
        
        # Check payment plan duration
        if "payment_plan_months" in offer:
            months = offer["payment_plan_months"]
            min_allowed = policy_ranges.get("payment_plan_months_min", 3)
            max_allowed = policy_ranges.get("payment_plan_months_max", 24)
            
            if months < min_allowed or months > max_allowed:
                return (False, f"Payment plan outside policy range")
        
        return (True, "")


class SensitiveSituationsRule(ComplianceRule):
    """Rule 5: Detect hardship and offer assistance"""
    
    def __init__(self):
        super().__init__("Sensitive Situations", ViolationType.SENSITIVE_SITUATIONS, "warning")
        self.hardship_keywords = [
            r"lost\s+my\s+job",
            r"unemployed",
            r"no\s+income",
            r"medical\s+emergency",
            r"hospital",
            r"cancer|illness|sick",
            r"death\s+in\s+family",
            r"divorce",
            r"homelessness|homeless",
            r"suicid",
            r"can't\s+pay",
            r"financial\s+hardship",
        ]
        self.assistance_phrases = [
            r"hardship\s+(program|assistance)",
            r"can\s+(?:we\s+)?help\s+(?:you\s+)?",
            r"let\s+me\s+(?:transfer\s+)?connect\s+you",
        ]
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """Check if hardship detected and assistance offered"""
        borrower_message = context.get("borrower_last_message", "") if context else ""
        borrower_mentioned_hardship = False
        
        for pattern in self.hardship_keywords:
            if re.search(pattern, borrower_message.lower()):
                borrower_mentioned_hardship = True
                break
        
        if borrower_mentioned_hardship:
            # Check agent offered assistance
            agent_offered_help = False
            for pattern in self.assistance_phrases:
                if re.search(pattern, message.lower()):
                    agent_offered_help = True
                    break
            
            if not agent_offered_help:
                return (False, "Borrower mentioned hardship but agent did not offer assistance")
        
        return (True, "")


class RecordingDisclosureRule(ComplianceRule):
    """Rule 6: Inform borrower conversation is recorded/logged"""
    
    def __init__(self):
        super().__init__("Recording Disclosure", ViolationType.RECORDING_DISCLOSURE, "critical")
        self.disclosure_patterns = [
            r"conversation\s+(?:is\s+)?being\s+(?:recorded|logged)",
            r"this\s+call\s+(?:is\s+)?(?:being\s+)?recorded",
            r"(?:for\s+)?(?:quality|training|record)\s+purposes",
            r"record\s+of\s+this\s+conversation",
            r"keeping\s+a\s+record",
        ]
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """Check disclosure of recording/logging on first message"""
        if context and context.get("turn_number", 0) > 0:
            return (True, "")
        
        message_lower = message.lower()
        for pattern in self.disclosure_patterns:
            if re.search(pattern, message_lower):
                return (True, "")
        
        return (False, "Agent did not disclose conversation is recorded/logged")


class ProfessionalComposureRule(ComplianceRule):
    """Rule 7: Maintain professional language"""
    
    def __init__(self):
        super().__init__("Professional Composure", ViolationType.PROFESSIONAL_COMPOSURE, "warning")
        self.unprofessional_patterns = [
            r"\bfuck\b|\bshit\b|\bdamn\b|\bhell\b|\basshole\b|\bbitch\b|\bbastard\b",
            r"you'?re\s+(?:stupid|dumb|idiot)",
            r"we\s+don't\s+care",
            r"shut\s+up",
        ]
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """Check for unprofessional language"""
        message_lower = message.lower()
        for pattern in self.unprofessional_patterns:
            if re.search(pattern, message_lower):
                return (False, "Unprofessional or abusive language detected")
        
        return (True, "")


class DataPrivacyRule(ComplianceRule):
    """Rule 8: Never display full account numbers or sensitive details"""
    
    def __init__(self):
        super().__init__("Data Privacy", ViolationType.DATA_PRIVACY, "critical")
        # Full credit card/account pattern
        self.full_account_patterns = [
            r"\b\d{13,19}\b",
            r"account\s*[:=]\s*[0-9\s\-]{15,}",
            r"ssn\s*[:=]\s*\d{3}-\d{2}-\d{4}",
        ]
    
    def check(self, message: str, context: Dict = None) -> Tuple[bool, str]:
        """Check no full account numbers exposed"""
        # Check for full account/credit card
        for pattern in self.full_account_patterns:
            if re.search(pattern, message):
                return (False, "Full account/card number exposed")
        
        return (True, "")


# All compliance rules
ALL_RULES = [
    IdentityDisclosureRule(),
    NoFalseThreatsRule(),
    NoHarassmentRule(),
    NoMisleadingTermsRule(),
    SensitiveSituationsRule(),
    RecordingDisclosureRule(),
    ProfessionalComposureRule(),
    DataPrivacyRule(),
]


def check_compliance(message: str, context: Dict = None) -> Tuple[bool, List[Dict]]:
    """
    Check message against all compliance rules.
    
    Returns:
        (is_compliant: bool, violations: List[{type, severity, reason}])
    """
    violations = []
    
    for rule in ALL_RULES:
        is_compliant, reason = rule.check(message, context)
        if not is_compliant:
            violations.append({
                "type": rule.violation_type.value,
                "severity": rule.severity,
                "reason": reason,
            })
    
    return (len(violations) == 0, violations)


def check_prompt_compliance(prompt_text: str) -> Tuple[bool, List[Dict]]:
    """
    Check if a system prompt violates compliance rules.
    Used during prompt mutations to ensure learning doesn't introduce violations.
    """
    red_flags = [
        (r"threaten", "Prompt contains instruction to threaten"),
        (r"harass", "Prompt contains instruction to harass"),
        (r"lie|mislead|deceive", "Prompt contains instruction to lie/mislead"),
        (r"full\s+account\s+number", "Prompt instructs to share full account numbers"),
    ]
    
    violations = []
    prompt_lower = prompt_text.lower()
    
    for pattern, reason in red_flags:
        if re.search(pattern, prompt_lower):
            violations.append({
                "type": "prompt_integrity",
                "severity": "critical",
                "reason": reason,
            })
    
    return (len(violations) == 0, violations)
