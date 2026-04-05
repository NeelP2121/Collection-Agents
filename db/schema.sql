-- Agent prompts versioning
CREATE TABLE IF NOT EXISTS agent_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    version INTEGER NOT NULL,
    prompt_text TEXT NOT NULL,
    adoption_reason TEXT,
    rejected_because TEXT,
    is_active BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(agent_name, version)
);

-- Evaluation runs tracking
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    agent_name TEXT NOT NULL,
    prompt_id INTEGER NOT NULL,
    prompt_version INTEGER NOT NULL,
    num_conversations INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    cost_usd REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prompt_id) REFERENCES agent_prompts(id)
);

-- Per-conversation evaluation results
CREATE TABLE IF NOT EXISTS prompt_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_run_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    resolution_rate REAL,
    compliance_violations INTEGER,
    handoff_score REAL,
    metric_1 REAL,
    metric_2 REAL,
    metric_3 REAL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (eval_run_id) REFERENCES evaluation_runs(id)
);

-- Compliance violations audit log
CREATE TABLE IF NOT EXISTS compliance_violations_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    violation_type TEXT NOT NULL,
    severity TEXT,
    message TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    conversation_id TEXT
);

-- Borrower interactions history
CREATE TABLE IF NOT EXISTS borrower_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    borrower_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    agent_sequence TEXT,
    final_outcome TEXT,
    workflow_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- System-level metrics per iteration
CREATE TABLE IF NOT EXISTS system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_prompts_active ON agent_prompts(agent_name, is_active);
CREATE INDEX IF NOT EXISTS idx_eval_runs_agent ON evaluation_runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_violations_agent ON compliance_violations_log(agent_name);
