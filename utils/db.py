import os
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from db.models import Base, AgentPrompt, EvaluationRun, PromptEvaluation, ComplianceViolation, BorrowerInteraction, SystemMetric

DB_PATH = os.getenv("DB_PATH", "./collections_agents.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initialize database schema"""
    Base.metadata.create_all(bind=engine)
    print(f"Database initialized at {DB_PATH}")

def get_db() -> Session:
    """Get database session"""
    return SessionLocal()

def save_agent_prompt(agent_name: str, version: int, prompt_text: str, adoption_reason: str = None, rejected_because: str = None, is_active: bool = False):
    """Save a new agent prompt version"""
    db = get_db()
    try:
        # Deactivate previous active version for this agent
        if is_active:
            previous_active = db.query(AgentPrompt).filter(
                AgentPrompt.agent_name == agent_name,
                AgentPrompt.is_active == True
            ).first()
            if previous_active:
                previous_active.is_active = False
        
        new_prompt = AgentPrompt(
            agent_name=agent_name,
            version=version,
            prompt_text=prompt_text,
            adoption_reason=adoption_reason,
            rejected_because=rejected_because,
            is_active=is_active
        )
        db.add(new_prompt)
        db.commit()
        return new_prompt
    finally:
        db.close()

def get_active_prompt(agent_name: str) -> AgentPrompt:
    """Retrieve active prompt for an agent"""
    db = get_db()
    try:
        return db.query(AgentPrompt).filter(
            AgentPrompt.agent_name == agent_name,
            AgentPrompt.is_active == True
        ).first()
    finally:
        db.close()

def get_prompt_version(agent_name: str, version: int) -> AgentPrompt:
    """Retrieve specific prompt version"""
    db = get_db()
    try:
        return db.query(AgentPrompt).filter(
            AgentPrompt.agent_name == agent_name,
            AgentPrompt.version == version
        ).first()
    finally:
        db.close()

def save_evaluation_run(run_id: str, agent_name: str, prompt_version: int, num_conversations: int, metrics_dict: dict, cost_usd: float = None):
    """Save evaluation run results"""
    db = get_db()
    try:
        # Get the prompt to get its ID
        prompt = db.query(AgentPrompt).filter(
            AgentPrompt.agent_name == agent_name,
            AgentPrompt.version == prompt_version
        ).first()
        if not prompt:
            raise ValueError(f"Prompt not found: {agent_name} v{prompt_version}")
        
        eval_run = EvaluationRun(
            run_id=run_id,
            agent_name=agent_name,
            prompt_id=prompt.id,
            prompt_version=prompt_version,  # Keep for backward compatibility
            num_conversations=num_conversations,
            metrics_json=json.dumps(metrics_dict),
            cost_usd=cost_usd
        )
        db.add(eval_run)
        db.commit()
        db.refresh(eval_run)
        return eval_run
    finally:
        db.close()

def get_evaluation_run(run_id: str) -> EvaluationRun:
    """Retrieve evaluation run"""
    db = get_db()
    try:
        return db.query(EvaluationRun).filter(EvaluationRun.run_id == run_id).first()
    finally:
        db.close()

def get_baseline_metrics(agent_name: str) -> EvaluationRun:
    """Get baseline evaluation run for an agent (first version=1)"""
    db = get_db()
    try:
        return db.query(EvaluationRun).filter(
            EvaluationRun.agent_name == agent_name,
            EvaluationRun.prompt_version == 1
        ).order_by(EvaluationRun.created_at.asc()).first()
    finally:
        db.close()

def save_prompt_evaluation(eval_run_id: int, conversation_id: str, resolution_rate: float = None, 
                          compliance_violations: int = None, handoff_score: float = None, notes: str = None):
    """Save individual conversation evaluation"""
    db = get_db()
    try:
        eval = PromptEvaluation(
            eval_run_id=eval_run_id,
            conversation_id=conversation_id,
            resolution_rate=resolution_rate,
            compliance_violations=compliance_violations,
            handoff_score=handoff_score,
            notes=notes
        )
        db.add(eval)
        db.commit()
        return eval
    finally:
        db.close()

def log_compliance_violation(agent_name: str, violation_type: str, severity: str = "warning", message: str = None, conversation_id: str = None):
    """Log a compliance violation"""
    db = get_db()
    try:
        violation = ComplianceViolation(
            agent_name=agent_name,
            violation_type=violation_type,
            severity=severity,
            message=message,
            conversation_id=conversation_id
        )
        db.add(violation)
        db.commit()
        return violation
    finally:
        db.close()

def record_borrower_interaction(borrower_name: str, phone: str, agent_sequence: str, final_outcome: str, workflow_id: str):
    """Record a borrower's full interaction"""
    db = get_db()
    try:
        interaction = BorrowerInteraction(
            borrower_name=borrower_name,
            phone=phone,
            agent_sequence=agent_sequence,
            final_outcome=final_outcome,
            workflow_id=workflow_id
        )
        db.add(interaction)
        db.commit()
        return interaction
    finally:
        db.close()

def get_all_prompt_versions(agent_name: str):
    """Get all versions of a prompt (for evolution report)"""
    db = get_db()
    try:
        return db.query(AgentPrompt).filter(
            AgentPrompt.agent_name == agent_name
        ).order_by(AgentPrompt.version.asc()).all()
    finally:
        db.close()

def get_violations_by_agent(agent_name: str, limit: int = 100):
    """Get recent compliance violations for an agent"""
    db = get_db()
    try:
        return db.query(ComplianceViolation).filter(
            ComplianceViolation.agent_name == agent_name
        ).order_by(ComplianceViolation.timestamp.desc()).limit(limit).all()
    finally:
        db.close()


def rollback_prompt(agent_name: str) -> bool:
    """
    Rollback to the previous active prompt version.

    Deactivates the current active prompt and reactivates the most recent
    previously-active version. Returns True if rollback succeeded.
    """
    db = get_db()
    try:
        # Find current active
        current = db.query(AgentPrompt).filter(
            AgentPrompt.agent_name == agent_name,
            AgentPrompt.is_active == True,
        ).first()

        if not current:
            return False

        # Find the most recent non-active adopted prompt (has adoption_reason)
        previous = (
            db.query(AgentPrompt)
            .filter(
                AgentPrompt.agent_name == agent_name,
                AgentPrompt.is_active == False,
                AgentPrompt.id < current.id,
                AgentPrompt.adoption_reason != None,
            )
            .order_by(AgentPrompt.id.desc())
            .first()
        )

        if not previous:
            return False

        current.is_active = False
        current.rejected_because = "Rolled back due to regression"
        previous.is_active = True
        db.commit()

        return True
    finally:
        db.close()


def get_previous_prompt(agent_name: str):
    """Get the most recent non-active adopted prompt for rollback preview."""
    db = get_db()
    try:
        active = db.query(AgentPrompt).filter(
            AgentPrompt.agent_name == agent_name,
            AgentPrompt.is_active == True,
        ).first()
        if not active:
            return None
        return (
            db.query(AgentPrompt)
            .filter(
                AgentPrompt.agent_name == agent_name,
                AgentPrompt.is_active == False,
                AgentPrompt.id < active.id,
                AgentPrompt.adoption_reason != None,
            )
            .order_by(AgentPrompt.id.desc())
            .first()
        )
    finally:
        db.close()
