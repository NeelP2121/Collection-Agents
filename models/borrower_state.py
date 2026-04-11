from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BorrowerContext:
    """
    Persistent borrower state across all three agents.
    Serialized to dict for Temporal activity transport.
    """
    # Borrower identity
    name: str = "Unknown"
    phone: str = ""

    # Verification
    identity_verified: bool = False
    verification_attempts: int = 0

    # Financial situation (populated by Agent 1)
    balance: Optional[float] = None
    employment_status: Optional[str] = None   # employed | unemployed | retired | disabled
    income: Optional[float] = None
    ability_to_pay: Optional[str] = None      # full | partial | none | unknown
    hardship_detected: bool = False

    # Agent 1 (Assessment) outputs
    agent1_result: Dict[str, Any] = field(default_factory=dict)
    agent1_messages: List[Dict[str, str]] = field(default_factory=list)
    agent1_summary: Any = None   # Handoff ledger (dict from LLM JSON) — ≤500 tokens

    # Agent 2 (Resolution/Voice) outputs
    agent2_result: Dict[str, Any] = field(default_factory=dict)
    agent2_transcript: Optional[str] = None
    agent2_offers_made: List[Dict[str, Any]] = field(default_factory=list)
    agent2_summary: Any = None   # Handoff ledger (dict from LLM JSON) — ≤500 tokens

    # Agent 3 (Final Notice) outputs
    agent3_result: Dict[str, Any] = field(default_factory=dict)
    agent3_messages: List[Dict[str, str]] = field(default_factory=list)

    # Workflow metadata
    workflow_id: Optional[str] = None
    current_stage: str = "assessment"   # assessment | resolution | final_notice | completed
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    # Compliance tracking
    compliance_violations: List[Dict[str, Any]] = field(default_factory=list)
    stop_contact_requested: bool = False

    # Final outcome
    final_outcome: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def mark_identity_verified(self):
        self.identity_verified = True
        self.updated_at = _now_iso()

    def mark_hardship(self):
        self.hardship_detected = True
        self.updated_at = _now_iso()

    def mark_stop_contact(self):
        self.stop_contact_requested = True
        self.updated_at = _now_iso()

    def add_compliance_violation(self, violation_type: str, severity: str, message: str):
        self.compliance_violations.append({
            "type": violation_type,
            "severity": severity,
            "message": message,
            "timestamp": _now_iso(),
        })
        self.updated_at = _now_iso()

    def advance_stage(self, new_stage: str):
        self.current_stage = new_stage
        self.updated_at = _now_iso()

    def update_from_handoff(self, handoff_summary: Dict[str, Any]):
        """Update borrower context fields from a handoff ledger dict."""
        if not handoff_summary:
            return

        if "identity_verified" in handoff_summary:
            self.identity_verified = bool(handoff_summary["identity_verified"])

        if "hardship_detected" in handoff_summary:
            self.hardship_detected = bool(handoff_summary["hardship_detected"])
        elif "hardship_status" in handoff_summary:
            self.hardship_detected = str(handoff_summary["hardship_status"]).lower() in (
                "yes", "true", "detected",
            )

        if "employment_status" in handoff_summary:
            self.employment_status = handoff_summary["employment_status"]

        if "ability_to_pay" in handoff_summary:
            self.ability_to_pay = handoff_summary["ability_to_pay"]

        if "balance" in handoff_summary:
            try:
                self.balance = float(handoff_summary["balance"])
            except (TypeError, ValueError):
                pass

        if "settlement_offers" in handoff_summary:
            self.agent2_offers_made = handoff_summary["settlement_offers"]

        self.updated_at = _now_iso()
