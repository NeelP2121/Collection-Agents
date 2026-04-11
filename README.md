# Post-Default Debt Collection AI System

Three-agent debt collection pipeline with Temporal orchestration, VAPI voice integration, self-learning A/B evaluation, and Darwin-Godel meta-evaluation. Built with FDCPA compliance enforcement at every layer.

## Quick Start

### Option A: Docker (Recommended)

```bash
# 1. Configure secrets
cp .env.example .env   # Add your ANTHROPIC_API_KEY
# Or place keys in secrets/*.txt files

# 2. Start everything
docker compose up --build

# 3. Access
# Web Portal:     http://localhost:8000
# Temporal UI:    http://localhost:8080
# Voice Webhook:  http://localhost:8001
```

All services start in ~30 seconds. The worker waits for Temporal to be healthy before connecting.

### Option B: Local

```bash
# 1. Temporal dev server (separate terminal)
brew install temporal
temporal server start-dev

# 2. Python environment
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Web portal
PYTHONPATH=. python api/server.py          # http://localhost:8000

# 4. Temporal worker (separate terminal)
PYTHONPATH=. python -m workers.main

# 5. Self-learning loop
PYTHONPATH=. python run_learning_loop.py --iterations 3 --conversations 10 --seed 42
```

## Architecture

```
Borrower --> [Agent 1: Assessment/Chat] --> Handoff Ledger (500 tokens)
                                                |
                                                v
             [Agent 2: Resolution/Voice] --> Handoff Ledger (500 tokens)
                                                |
                                                v
             [Agent 3: Final Notice/Chat] --> Outcome
```

- Each agent: 2000-token context window, system prompt loaded from `registry/active_prompts.yaml`
- Temporal.io orchestrates the workflow with per-activity timeouts and crash recovery
- Voice (Agent 2) uses VAPI WebRTC with a Custom LLM endpoint (`/chat/completions`)
- Handoff ledgers are LLM-compressed structured JSON, truncated by `tiktoken` if over 500 tokens

## Self-Learning Loop

```bash
PYTHONPATH=. python run_learning_loop.py --iterations 5 --conversations 25 --seed 42
```

Real A/B evaluation pipeline:
1. Evaluate active prompt against synthetic borrower personas (cooperative, combative, evasive, confused, distressed, financially_capable)
2. Generate prompt variants via LLM meta-prompting
3. Compliance-gate each variant (negation-aware FDCPA check)
4. Evaluate variants against the same scenarios (deterministic seed)
5. Apply 5 statistical gates: Welch's t-test (p<0.05), Cohen's d (>=0.5), mean improvement (>=15%), variance ratio (<4.0), 95% CI lower bound (>0)
6. System-level cross-agent regression check after adoption
7. Darwin-Godel meta-evaluation for metric gaming detection

Output:
- `evals_output/raw_scores.csv` -- per-conversation scores
- `evals_output/decisions.csv` -- statistical decisions with p-values, effect sizes
- `evals_output/evolution_report.md` -- full report with distributions, prompt history, cost breakdown

## Darwin-Godel Demonstration

```bash
PYTHONPATH=. python demonstrate_darwin_godel.py
```

Demonstrates the meta-evaluator catching a flaw: efficiency over-weighting allows fast-but-bad agents to score competitively. The Godel layer detects this, proposes a weight correction, validates it against synthetic profiles, and widens the gap between good and bad agents by ~80%.

## Run a Borrower Workflow

```bash
PYTHONPATH=. python run_workflow.py --name "Jane Doe" --phone "+15551234567" --balance 6500
```

Triggers the full 3-agent Temporal workflow: Assessment (chat) -> Resolution (voice) -> Final Notice (chat).

## Project Structure

```
agents/                  # Agent implementations (BaseAgent + 3 specialized)
temporal/                # Temporal workflow and activities
voice/                   # VAPI voice integration (webhook, handler, transcript analyzer)
learning/                # Self-learning loop
  learning_loop.py       #   A/B evaluation orchestrator
  evaluator.py           #   Synthetic conversation evaluator
  statistics.py          #   Welch's t-test, Cohen's d, CI, variance ratio
  judge.py               #   Per-agent rubric scoring
  meta_evaluator.py      #   Darwin layer (weight introspection)
  godel_monitor.py       #   Godel layer (blind spot detection)
  prompt_improver.py     #   LLM-powered variant generation
  data_export.py         #   CSV writer + evolution report generator
compliance/              # FDCPA rule enforcement (8 rules from assignment spec)
utils/                   # LLM abstraction, cost tracking, database, config
api/                     # FastAPI web portal
frontend/                # Borrower-facing chat/voice UI
registry/                # active_prompts.yaml (agent system prompts)
evals_output/            # CSV data + evolution report (generated)
```

## Key Technical Decisions

| Decision | Why |
|----------|-----|
| Welch's t-test (not Student's) | Baseline and variant may have different variances |
| Cohen's d >= 0.5 threshold | Reject statistically significant but trivially small improvements |
| 5 independent adoption gates | Conservative: cost of bad prompt > cost of missing marginal gain |
| Per-agent judge rubrics | Assessment needs identity verification; Resolution needs offer quality |
| Negation-aware compliance check | "Do not threaten" should pass; "threaten the borrower" should fail |
| Rule registry (not source rewriting) | Godel rules stored in JSON, loaded at evaluation time, validated before commit |
| Deterministic seed | Same seed = same scenario order = reproducible results |

## Budget

$20 total LLM ceiling. Agent conversations use Haiku (~$0.005/conversation). Judge and meta-eval use Sonnet (~$0.025/call). Godel monitor uses Opus for highest reasoning quality. Thread-safe `CostTracker` singleton enforces the limit and stops the loop gracefully when budget is insufficient for the next iteration.
