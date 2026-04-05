from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import json

Base = declarative_base()

class AgentPrompt(Base):
    __tablename__ = 'agent_prompts'
    
    id = Column(Integer, primary_key=True)
    agent_name = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    adoption_reason = Column(Text)
    rejected_because = Column(Text)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    evaluations = relationship("EvaluationRun", back_populates="prompt")
    
    __table_args__ = (UniqueConstraint('agent_name', 'version', name='unique_agent_version'),)

class EvaluationRun(Base):
    __tablename__ = 'evaluation_runs'
    
    id = Column(Integer, primary_key=True)
    run_id = Column(String, unique=True, nullable=False)
    agent_name = Column(String, nullable=False)
    prompt_id = Column(Integer, ForeignKey('agent_prompts.id'), nullable=False)
    prompt_version = Column(Integer, nullable=False)  # Keep for backward compatibility
    num_conversations = Column(Integer, nullable=False)
    metrics_json = Column(Text, nullable=False)  # JSON string
    cost_usd = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    prompt = relationship("AgentPrompt", back_populates="evaluations")
    evaluations = relationship("PromptEvaluation", back_populates="run")
    
    def get_metrics(self):
        """Parse metrics JSON"""
        return json.loads(self.metrics_json) if self.metrics_json else {}
    
    def set_metrics(self, metrics_dict):
        """Store metrics as JSON"""
        self.metrics_json = json.dumps(metrics_dict)

class PromptEvaluation(Base):
    __tablename__ = 'prompt_evaluations'
    
    id = Column(Integer, primary_key=True)
    eval_run_id = Column(Integer, ForeignKey('evaluation_runs.id'), nullable=False)
    conversation_id = Column(String, nullable=False)
    resolution_rate = Column(Float)
    compliance_violations = Column(Integer)
    handoff_score = Column(Float)
    metric_1 = Column(Float)
    metric_2 = Column(Float)
    metric_3 = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    run = relationship("EvaluationRun", back_populates="evaluations")

class ComplianceViolation(Base):
    __tablename__ = 'compliance_violations_log'
    
    id = Column(Integer, primary_key=True)
    agent_name = Column(String, nullable=False)
    violation_type = Column(String, nullable=False)
    severity = Column(String)  # "critical", "warning"
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    conversation_id = Column(String)

class BorrowerInteraction(Base):
    __tablename__ = 'borrower_interactions'
    
    id = Column(Integer, primary_key=True)
    borrower_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    agent_sequence = Column(String)  # "1,2,3" or "1,2"
    final_outcome = Column(String)  # "resolved_voice", "unresolved", etc.
    workflow_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SystemMetric(Base):
    __tablename__ = 'system_metrics'
    
    id = Column(Integer, primary_key=True)
    iteration = Column(Integer, nullable=False)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
