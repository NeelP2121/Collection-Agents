# Post-Default Debt Collection AI System

This repository implements the complete self-learning ecosystem for omnichannel debt collection.

## 🚀 Two Ways to Run

You can run the entire system either natively on your local machine (Mac/Linux) or fully containerized via Docker. **Docker is strongly recommended** as it supplies the Temporal backend cluster out-of-the-box.

---

### Option A: Fully Containerized via Docker (Recommended)
This approach boots the Temporal Cluster, Temporal UI, the Python Worker, the Voice Webhooks, and the Frontend Web Portal simultaneously.

1. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Open .env and add your ANTHROPIC_API_KEY
   ```
2. **Start the Cluster:**
   ```bash
   docker-compose up --build
   ```
3. **Access the Interfaces:**
   - **Borrower Omnichannel Portal:** [http://localhost:8000](http://localhost:8000)
   - **Temporal Flow UI:** [http://localhost:8080](http://localhost:8080)
   - **Voice Webhook (VAPI):** [http://localhost:8001](http://localhost:8001)

---

### Option B: Native Local Execution
If you prefer running the Python scripts locally on your machine, you must manually install and boot the Temporal development server.

1. **Install and Boot Temporal Server (Mac):**
   ```bash
   brew install temporal
   temporal server start-dev
   ```
   *(Leave this running in a background terminal. You can view the UI at `localhost:8233`)*

2. **Configure Python Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   *Make sure you create your `.env` with your `ANTHROPIC_API_KEY`.*

3. **Start the Frontend Web Portal:**
   ```bash
   # In a new terminal window:
   PYTHONPATH=. venv/bin/python api/server.py
   # View at http://localhost:8000
   ```

4. **Start the Temporal Worker (Optional):**
   ```bash
   # In a new terminal window:
   PYTHONPATH=. venv/bin/python -m workers.main
   ```

5. **Run the Self-Learning Machine (Darwin Godel Loop):**
   ```bash
   # In a new terminal window:
   PYTHONPATH=. venv/bin/python run_system_cycle.py
   ```

---

## Technical Features Implemented
- **Darwin Gödel Meta-Evaluator:** Synthetically grades prompt tests iteratively, actively catching false-positives and autonomously evolving its own weighting parameters natively via LLM interception.
- **True Synthetic Conversation Engine:** Generates active multi-turn LLM versus LLM tests enforcing real failure modes (Evading, Combative, etc.).
- **Global API Cost Enforcement:** Dedicated thread-safe singleton actively throttling loops guaranteeing a strict $20 LLM budget ceiling.
- **Asynchronous WebRTC Suspend:** Temporal `wait_condition` logic mapping cleanly over a FastAPI VAPI receiver allowing stateless webhook telephony handoffs.
