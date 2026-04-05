# Phase 4: Self-Learning System Implementation

## Overview

Phase 4 implements autonomous prompt improvement and self-learning capabilities. The system analyzes evaluation results from Phase 3, extracts patterns, generates improved prompts, evaluates variants, and selects winners to deploy.

## Architecture

### Core Components

#### 1. **LearningState Model** (`models/learning_state.py`)
Persistent state management for learning system:
- `PromptVariant`: Individual prompt versions with performance metrics
- `LearningInsight`: Extracted patterns and recommendations
- `EvaluationRound`: Complete evaluation cycle with results
- `LearningState`: Central state holder tracking all learning history

**Key Features:**
- Maintains complete prompt history per agent
- Tracks top-performing prompts by agent
- Groups insights by scenario type
- Stores evaluation history for trend analysis

#### 2. **Prompt Improver** (`self_learning/prompt_improver.py`)
Generates optimized prompt variations using meta-prompting:

**Core Methods:**
- `analyze_failures()`: Analyzes why scenarios failed
- `generate_prompt_variations()`: Creates 3+ improved variations per agent
- `rank_prompts()`: Ranks variants by estimated performance
- `create_fallback_variations()`: Fallback when meta-prompting fails

**Improvement Strategies:**
```
For Combative Scenarios:
→ Reduce assertiveness, add empathy, focus on borrower control

For Evasive Scenarios:
→ Add clarity and urgency, break down complex information

For Distressed Scenarios:
→ Include hardship program references, offer flexibility

For Cooperative Scenarios:
→ Streamline process, offer clear next steps
```

#### 3. **Meta-Evaluator** (`self_learning/meta_evaluator.py`)
Compares prompt variants and selects winners:

**Scoring Components:**
- Resolution Rate (40% weight)
- Compliance Score (35% weight)
- Conversation Efficiency (15% weight)
- Borrower Satisfaction (10% weight)

**Key Methods:**
- `compare_variants()`: Rank variants with composite scores
- `identify_winners()`: Find variants beating baseline by 2%+
- `select_best_prompt()`: Single best performer
- `should_continue_learning()`: Determine iteration necessity

#### 4. **Feedback Aggregator** (`self_learning/feedback_aggregator.py`)
Learns patterns from evaluation results:

**Pattern Analysis:**
- Success patterns (what works for each scenario type)
- Failure patterns (what doesn't work)
- Cross-agent patterns
- Theme-based grouping

**Recommendation Generation:**
- Scenario-specific recommendations
- Tone and language adjustments
- Clarify strategies
- Negotiation approaches

#### 5. **Learning Loop** (`self_learning/learning_loop.py`)
Orchestrates the complete learning cycle:

**Cycle Steps:**
1. Load previous learning state (if exists)
2. Record new evaluation results
3. **For each iteration (up to max_iterations):**
   - Extract insights from failures
   - Generate improved prompt variations
   - Meta-evaluate variants
   - Select and promote winners
   - Record learning iteration
   - Save updated learning state
4. Generate final recommendations
5. Save complete learning history

## Workflow: Phase 3 → Phase 4

### Sequence

```
Phase 3: Evaluation Results
├─ Overall Resolution Rate: 45%
├─ Overall Compliance Score: 82%
└─ Scenario Breakdown:
   ├─ Cooperative: 100% (2/2)
   ├─ Combative: 0% (0/2)
   ├─ Evasive: 33% (1/3)
   └─ Distressed: 50% (1/2)

        ↓

Phase 4: Self-Learning
├─ Step 1: Extract Insights
│  ├─ Poor performance with combative/evasive
│  ├─ Strong performance with cooperative
│  └─ Insufficient hardship accommodation
├─ Step 2: Analyze Failure Patterns
│  ├─ Combative: Perceived as too aggressive
│  ├─ Evasive: Too many options cause confusion
│  └─ Distressed: Need more flexibility
├─ Step 3: Generate Prompt Variations
│  ├─ Empathy variant (for combative)
│  ├─ Clarity variant (for evasive)
│  └─ Flexibility variant (for distressed)
├─ Step 4: Meta-Evaluate Variants
│  └─ Compare each variant's composite score
├─ Step 5: Select and Promote Winners
│  └─ Replace baseline prompts with best performers
└─ Output: Learning State + Recommendations

        ↓

Next Phase: Re-run Phase 3 with Improved Prompts
```

## Learning Insights Structure

### Example Insight: Combative Scenario Failure

```python
insight = LearningInsight(
    insight_id="failure_agent1_combative",
    agent_name="agent1",
    pattern="Poor performance with combative borrowers (0% success)",
    impact="negative",
    confidence=0.95,
    failing_scenario="combative",
    recommendation="Reduce assertiveness, add empathy, emphasize borrower choice"
)
```

### Insight Types

**Positive Insights (Impact: positive)**
- Strong performance patterns that should be maintained
- High confidence in success scenarios
- Recommended: "Maintain current approach"

**Negative Insights (Impact: negative)**
- Failure patterns requiring prompt changes
- Low success rates in specific scenarios
- Recommended: Specific improvements

**Scenario-Specific**
- `cooperative`: Quick resolution, good faith
- `combative`: Defensive, tone sensitivity
- `evasive`: Clarity and urgency needed
- `distressed`: Hardship accommodation needed

## Prompt Variation Strategies

### Strategy 1: Empathy Addition
```python
# For combative scenarios
"Professional, factual"
    ↓
"Professional but empathetic"
+ "We understand this is difficult."
```

### Strategy 2: Clarity Focus
```python
# For evasive scenarios
"Professional, factual, final."
    ↓
"Clear, simple, urgent. Use short sentences and bullet points only."
```

### Strategy 3: Offer Flexibility
```python
# For distressed scenarios
+ "Always present 2-3 settlement options with different timeframes."
+ "Be flexible on payment terms."
```

## Performance Metrics

### Scoring Components

**1. Resolution Rate (40% weight)**
- Percentage of scenarios that reached settlement
- Target: 70%+
- Impact: Directly affects revenue/outcomes

**2. Compliance Score (35% weight)**
- FDCPA compliance adherence
- Target: 90%+
- Impact: Legal/regulatory risk

**3. Conversation Efficiency (15% weight)**
- Average turns per scenario
- Target: <4 turns
- Impact: Cost per successful resolution

**4. Borrower Satisfaction (10% weight)**
- Inferred from resolution + compliance
- Calculated: (resolution_rate × 0.6 + compliance_score × 0.4)

### Winner Selection Criteria
- Minimum improvement: 2% over baseline
- If no improvements found: Consider aggressive changes
- If baseline strong: Consider incremental refinements

## Integration Points

### Phase 2 → Phase 3
- Workflow produces borrower contexts
- Evaluation tests agents with synthetic personas
- Results capture resolution rates and compliance

### Phase 3 → Phase 4
- Evaluation results → Learning Loop
- Failures trigger prompt analysis
- Success patterns inform recommendations
- Improved prompts ready for next evaluation

### Phase 4 → Phase 3 (Iteration)
- Learning state persisted to disk
- New prompts deployed to agents
- Re-run Phase 3 evaluation
- Compare metrics against previous round
- Continue if improvements possible

## Usage Examples

### Running Phase 4 Learning

```python
from self_learning.learning_loop import LearningLoop

learning_loop = LearningLoop()

# Get evaluation results from Phase 3
evaluation_results = {
    "overall_resolution_rate": 45.0,
    "overall_compliance_score": 82.0,
    "scenarios": {...}
}

# Run learning cycle (1-3 iterations)
summary = learning_loop.run(evaluation_results, max_iterations=2)

# Results include:
# - learning_iterations_completed
# - total_insights_generated
# - best_prompts_identified
# - final_recommendations
```

### Analyzing Specific Scenario Performance

```python
from self_learning.feedback_aggregator import FeedbackAggregator

aggregator = FeedbackAggregator()

# Extract patterns for specific agent
insights = aggregator.extract_patterns(evaluation_results, "agent1")

# Group by theme
themes = aggregator.group_insights_by_theme(insights)

# Get scenario success rates
success_rates = aggregator.track_scenario_success_rates(insights)
# Output: {"cooperative": 1.0, "combative": 0.0, ...}
```

### Evaluating Prompt Variants

```python
from self_learning.meta_evaluator import MetaEvaluator

evaluator = MetaEvaluator()

# Compare variants against baseline
results = evaluator.compare_variants(
    base_variant=original_prompt,
    test_variants=[variant1, variant2, variant3],
    evaluation_results=eval_results
)

# Get winners showing 2%+ improvement
winners = evaluator.identify_winners(results, min_improvement=0.02)

# Get best single prompt
best = evaluator.select_best_prompt(results)
```

## Performance Targets

| Metric | Target | Current (Phase 3) |
|--------|--------|-------------------|
| Resolution Rate | 70% | ~45% |
| Compliance Score | 90% | ~82% |
| Avg Turns/Scenario | <4 | 4.2 |
| Successful Prompts Promoted | 1-2 per agent | TBD |

## Success Criteria

Phase 4 is successful when:
1. ✓ Learning insights accurately identify failure patterns
2. ✓ Prompt variations show measurable performance improvements
3. ✓ Meta-evaluation correctly selects best performers
4. ✓ Learning state properly persists for iterative improvement
5. ✓ System suggests next improvements for continued learning

## Common Patterns by Scenario

### Combative Borrowers
- **Problem**: Perceived aggressive tone
- **Solution**: Add empathy, reduce urgency, offer choice
- **Estimated Impact**: +15-20% resolution rate

### Evasive Borrowers
- **Problem**: Too many options overwhelm
- **Solution**: Simplify to 1-2 clear choices, add urgency
- **Estimated Impact**: +10-15% resolution rate

### Distressed Borrowers
- **Problem**: Insufficient hardship accommodation
- **Solution**: Lead with flexibility, add hardship program refs
- **Estimated Impact**: +15-20% resolution rate

### Cooperative Borrowers
- **Problem**: Usually none (already high success)
- **Solution**: Maintain current approach, optimize efficiency
- **Estimated Impact**: +5% efficiency improvement

## Future Enhancements

1. **A/B Testing Infrastructure**
   - Systematic variant comparison with real borrowers
   - Statistical significance testing
   - Gradual rollout of winners

2. **Advanced Meta-Prompting**
   - Multi-turn improvement loops
   - Composite prompt generation
   - Scenario-aware prompt specialization

3. **Reinforcement Learning Integration**
   - Use real borrower feedback as training signal
   - Build preference models
   - Adapt prompts in real-time

4. **Cross-Agent Optimization**
   - Optimize handoff context
   - Reduce information loss between agents
   - Specialized prompts for each transition

5. **Cost Optimization**
   - Token counting for efficiency
   - Cheaper model use for meta-evaluation
   - Batch processing for variants

## Files

- `models/learning_state.py` - Learning state data structures
- `self_learning/prompt_improver.py` - Prompt variation generation
- `self_learning/meta_evaluator.py` - Variant comparison & selection
- `self_learning/feedback_aggregator.py` - Pattern extraction
- `self_learning/learning_loop.py` - Main orchestrator
- `tests/test_phase4_learning.py` - Standalone Phase 4 test
- `run_system_cycle.py` - Complete system integration demo
- `learning_state.json` - Persisted learning history (created at runtime)

## Testing

Run Phase 4 standalone test:
```bash
PYTHONPATH=. python tests/test_phase4_learning.py
```

Run complete system cycle:
```bash
PYTHONPATH=. python run_system_cycle.py
```

## Token Budget Impact

Phase 4 operates within the $20 LLM spend limit by:
1. Using cheaper Haiku model for analysis
2. Generating variants once per iteration (not per scenario)
3. Reusing previous evaluation results
4. Efficient meta-prompting for variant generation
5. Caching learned insights for future iterations

Estimated Phase 4 Cost: $2-3 per learning cycle (meta-prompting + analysis)
