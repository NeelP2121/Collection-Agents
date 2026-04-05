"""
Learning state model for storing prompt improvements and evaluation history.
Tracks which prompts work best for different borrower types and scenarios.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Any, Optional
import json

@dataclass
class PromptVariant:
    """A specific version of a prompt for testing"""
    variant_id: str
    agent_name: str  # "agent1", "agent2", "agent3"
    prompt_version: int
    prompt_text: str
    base_prompt: str  # Reference to original prompt
    changes: str  # Description of what changed
    created_at: datetime = field(default_factory=datetime.utcnow)
    evaluation_metrics: Dict[str, float] = field(default_factory=dict)
    performance_score: float = 0.0

@dataclass
class LearningInsight:
    """Extracted learning from evaluation results"""
    insight_id: str
    agent_name: str
    pattern: str  # Description of pattern identified
    impact: str  # "positive", "negative", "neutral"
    confidence: float  # 0.0-1.0
    failing_scenario: Optional[str] = None  # Type of borrower or scenario that failed
    success_scenario: Optional[str] = None  # Type that succeeded
    recommendation: Optional[str] = None  # Suggested change
    extracted_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class EvaluationRound:
    """Complete evaluation round with results"""
    round_id: str
    evaluation_date: datetime
    evaluation_results: Dict[str, Any]  # Results from test_phase3_evaluation.py
    agents_tested: List[str]
    scenarios_tested: List[str]
    overall_resolution_rate: float
    overall_compliance_score: float
    recommendations: List[str]
    insights_generated: List[LearningInsight] = field(default_factory=list)

@dataclass
class LearningState:
    """Complete learning state for the system"""
    learning_id: str
    agent_names: List[str] = field(default_factory=lambda: ["agent1", "agent2", "agent3"])
    
    # Prompt evolution
    prompt_history: Dict[str, List[PromptVariant]] = field(default_factory=dict)
    current_best_prompts: Dict[str, str] = field(default_factory=dict)
    
    # Learning insights
    insights: List[LearningInsight] = field(default_factory=list)
    scenario_patterns: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # Patterns by scenario type
    
    # Evaluation history
    evaluation_history: List[EvaluationRound] = field(default_factory=list)
    total_evaluations: int = 0
    best_evaluation: Optional[EvaluationRound] = None
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    learning_iterations: int = 0
    
    def add_variant(self, variant: PromptVariant):
        """Add a new prompt variant for an agent"""
        agent = variant.agent_name
        if agent not in self.prompt_history:
            self.prompt_history[agent] = []
        self.prompt_history[agent].append(variant)
        self.updated_at = datetime.utcnow()
    
    def update_best_prompt(self, agent_name: str, prompt_text: str):
        """Update the best prompt for an agent"""
        self.current_best_prompts[agent_name] = prompt_text
        self.updated_at = datetime.utcnow()
    
    def add_insight(self, insight: LearningInsight):
        """Record a learning insight"""
        self.insights.append(insight)
        
        # Group by scenario
        scenario = insight.failing_scenario or insight.success_scenario or "general"
        if scenario not in self.scenario_patterns:
            self.scenario_patterns[scenario] = {
                "agent_patterns": {},
                "successful_changes": [],
                "failed_changes": []
            }
        
        self.updated_at = datetime.utcnow()
    
    def add_evaluation(self, evaluation: EvaluationRound):
        """Record an evaluation round"""
        self.evaluation_history.append(evaluation)
        self.total_evaluations += 1
        
        # Update best evaluation
        if not self.best_evaluation or evaluation.overall_resolution_rate > self.best_evaluation.overall_resolution_rate:
            self.best_evaluation = evaluation
        
        self.updated_at = datetime.utcnow()
    
    def record_learning_iteration(self):
        """Record completion of a learning iteration"""
        self.learning_iterations += 1
        self.updated_at = datetime.utcnow()
    
    def get_agent_prompts(self, agent_name: str) -> List[PromptVariant]:
        """Get all prompt variants for an agent"""
        return self.prompt_history.get(agent_name, [])
    
    def get_top_prompts(self, agent_name: str, top_n: int = 3) -> List[PromptVariant]:
        """Get top performing prompts for an agent"""
        variants = self.get_agent_prompts(agent_name)
        return sorted(variants, key=lambda v: v.performance_score, reverse=True)[:top_n]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        # Handle datetime serialization
        data['created_at'] = self.created_at.isoformat()
        data['updated_at'] = self.updated_at.isoformat()
        if self.best_evaluation:
            data['best_evaluation']['evaluation_date'] = self.best_evaluation.evaluation_date.isoformat()
        return data
