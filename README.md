# CollectionAgents: Autonomous Debt Recovery Pipeline

A high-performance, autonomous debt collection system utilizing a multi-agent orchestration of LLMs (Claude/Gemini) and Temporal for long-running, stateful borrower workflows.

## 🚀 The System Architecture

The project is built on the **Darwin-Godel Mechanism (DGM)**, a self-optimizing loop that continuously evolves agent prompts based on successful resolutions and compliance audits.

### Core Components

1.  **Phase 1: Assessment Agent (Chat):** Cold, clinical, and precise. Verifies identity via last 4 of SSN/Zip and assesses the borrower's ability to pay or hardship status.
2.  **Phase 2: Resolution Agent (Voice):** A transactional dealmaker integrated with **VAPI**. Conducts real-time voice negotiations using custom-LLM endpoints and dynamic assistant overrides.
3.  **Phase 3: Final Notice Agent (Chat):** Consequence-driven and deadline-focused. Closes the loop by confirming agreements or stating legal/credit reporting consequences.

## 🛠 Engineering Principles

*   **Temporal Handoffs:** Uses `wait_condition` and Webhook signals to manage voice calls. This ensures the system is crash-proof; if the server dies, the call and the workflow state remain alive in Temporal.
*   **YAML DNA:** Agent personalities are stored in `registry/active_prompts.yaml`. The learning loop mutates this registry rather than code, ensuring zero syntax breaks during evolution.
*   **TikToken Gate:** Strict local enforcement of a 2000-token context window per agent using `cl100k_base` to prevent cost overruns and context hallucination.
*   **JSON Handoff Ledger:** Distills messy chat history into a structured <500 token JSON ledger for Agent-to-Agent communication, stripping out conversational noise.
*   **Cognitive Tiering:** Routes high-volume simulation/evaluation tasks to Flash models while reserving reasoning models (Sonnet/Pro) for "Godel" level audits and strategy.

## 🧠 Darwin-Godel Mechanism (DGM)

The system doesn't just evaluate agents; it audits the evaluation logic itself:
- **Godel Monitor:** Scans for "Prompt Gaming" where agents act polite solely to trick the rubric without achieving resolution.
- **Darwinian Evolution:** Shifts weights between *Empathy* and *Resolution Efficiency* based on success rates.
- **Regression Check:** Ensures that improving the Assessment Agent doesn't degrade the quality of data passed to the Resolution Agent.

## 🚦 Compliance & Safety

- **Hybrid Guardrails:** Combines LLM-based sentiment analysis with "Hard" Regex checks for forbidden terms (e.g., "Arrest", "Police", "Jail").
- **Time-Gated Activity:** Structurally prevents voice calls after 9 PM.
- **FDCPA Compliance:** Built-in disclosures (Mini-Miranda, AI disclosure) and mandatory "Stop Contact" handling.

## 📦 Setup & Usage

1.  **Configure Environment:** Copy `.env.example` to `.env` and provide your Anthropic/Google/VAPI keys.
2.  **Run the Web UI:** `python -m api.server` to launch the borrower portal on port 8000.
3.  **Start Temporal Worker:** `python -m workers.main` to process background workflows.
4.  **Launch Learning Loop:** `python run_learning_loop.py` to start the DGM evolution process.
