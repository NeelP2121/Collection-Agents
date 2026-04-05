from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any

@dataclass
class BorrowerContext:
    """
    Persistent borrower state across all three agents.
    Single context object that passes through entire workflow.
    """
    # Borrower identity
    name: str
    phone: str
    
    # Verification
    identity_verified: bool = False
    verification_attempts: int = 0
    
    # Financial situation (populated by Agent 1)
    balance: Optional[float] = None
    employment_status: Optional[str] = None  # "employed", "unemployed", "unknown"
    income: Optional[float] = None
    ability_to_pay: Optional[str] = None  # "full", "partial", "none", "unknown"
    hardship_detected: bool = False
    
    # Agent 1 (Assessment) outputs
    agent1_result: Dict[str, Any] = field(default_factory=dict)
    agent1_messages: List[Dict[str, str]] = field(default_factory=list)
    agent1_summary: Optional[str] = None  # 500-token max summary for handoff to Agent 2
    
    # Agent 2 (Resolution/Voice) outputs
    agent2_result: Dict[str, Any] = field(default_factory=dict)
    agent2_transcript: Optional[str] = None
    agent2_offers_made: List[Dict[str, Any]] = field(default_factory=list)
    agent2_summary: Optional[str] = None  # 500-token max summary for handoff to Agent 3
    
    # Agent 3 (Final Notice) outputs
    agent3_result: Dict[str, Any] = field(default_factory=dict)
    agent3_messages: List[Dict[str, str]] = field(default_factory=list)
    
    # Workflow metadata
    workflow_id: Optional[str] = None
    current_stage: str = "assessment"  # "assessment", "resolution", "final_notice"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Compliance tracking
    compliance_violations: List[Dict[str, Any]] = field(default_factory=list)
    stop_contact_requested: bool = False
    
    # Final outcome
    final_outcome: Optional[str] = None  # "resolved_voice", "unresolved", "failed_verification", etc.
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return asdict(self)
    
    def mark_identity_verified(self):
        """Mark identity as verified"""
        self.identity_verified = True
        self.updated_at = datetime.utcnow()
    
    def mark_hardship(self):
        """Mark borrower as in hardship"""
        self.hardship_detected = True
        self.updated_at = datetime.utcnow()
    
    def mark_stop_contact(self):
        """Mark that borrower requested no further contact"""
        self.stop_contact_requested = True
        self.updated_at = datetime.utcnow()
    
    def add_compliance_violation(self, violation_type: str, severity: str, message: str):
        """Log a compliance violation"""
        self.compliance_violations.append({
            "type": violation_type,
            "severity": severity,
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        })
        self.updated_at = datetime.utcnow()
    
    def advance_stage(self, new_stage: str):
        """Move to next workflow stage"""
        self.current_stage = new_stage
        self.updated_at = datetime.utcnow()
