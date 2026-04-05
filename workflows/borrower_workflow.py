from temporalio import workflow
from datetime import timedelta
from models.borrower_state import BorrowerContext

@workflow.defn
class BorrowerWorkflow:

    def __init__(self):
        self.voice_result = None

    @workflow.signal
    def voice_done(self, result: dict):
        self.voice_result = result

    @workflow.run
    async def run(self, borrower_data: dict):
        """
        Execute the three-agent debt collection workflow:
        1. Agent 1: Chat assessment (identity verification, financial assessment)
        2. Agent 2: Voice resolution (negotiation, settlement offers)
        3. Agent 3: Final notice (escalation, final collection attempt)
        """
        
        # Initialize borrower context
        borrower_context = BorrowerContext(
            name=borrower_data["name"],
            phone=borrower_data["phone"],
            workflow_id=workflow.info().workflow_id
        )
        
        # Phase 1: Agent 1 - Chat Assessment
        print(f"Starting Agent 1 assessment for {borrower_context.name}")
        agent1_result = await workflow.execute_activity(
            "run_assessment_agent",
            borrower_context,
            start_to_close_timeout=timedelta(minutes=5)
        )
        
        # Update context with Agent 1 results
        borrower_context.agent1_result = agent1_result.get("result", {})
        borrower_context.agent1_messages = agent1_result.get("messages", [])
        borrower_context.advance_stage("resolution")
        
        # Create Agent 1 → Agent 2 handoff summary (max 500 tokens)
        print("Creating Agent 1 → Agent 2 handoff summary")
        agent1_handoff = await workflow.execute_activity(
            "summarize_agent1_to_agent2",
            borrower_context.agent1_messages,
            borrower_context,
            start_to_close_timeout=timedelta(minutes=2)
        )
        
        borrower_context.agent1_summary = agent1_handoff
        
        # Phase 2: Agent 2 - Voice Resolution via WebRTC
        print(f"Starting Agent 2 voice resolution for {borrower_context.name}")
        vapi_trigger = await workflow.execute_activity(
            "run_voice_resolution_agent",
            args=[agent1_handoff, borrower_context],
            start_to_close_timeout=timedelta(minutes=5)
        )
        
        # Async Eventual-Consistency Bridge 
        # Suspend workflow until Webhook `.signal(...)` awakens it
        print("Suspending workflow pending WebRTC webhook confirmation...")
        await workflow.wait_condition(lambda: self.voice_result is not None)
        print("Resume triggered from Webhook! Continuing Phase 3 pipeline.")
        
        agent2_result = self.voice_result
        
        # Update context with Agent 2 results
        borrower_context.agent2_result = agent2_result
        borrower_context.agent2_transcript = agent2_result.get("transcript", "")
        borrower_context.agent2_offers_made = agent2_result.get("offers_made", [])
        
        # Check if resolved in voice phase
        if agent2_result.get("outcome") == "deal_agreed":
            borrower_context.final_outcome = "resolved_voice"
            borrower_context.advance_stage("completed")
            return {
                "status": "resolved_voice",
                "borrower_context": borrower_context.to_dict()
            }
        
        borrower_context.advance_stage("final_notice")
        
        # Create Agent 2 → Agent 3 handoff summary (max 500 tokens)
        print("Creating Agent 2 → Agent 3 handoff summary")
        agent2_handoff = await workflow.execute_activity(
            "summarize_agent2_to_agent3",
            agent1_handoff,
            borrower_context.agent2_transcript or [],
            borrower_context,
            start_to_close_timeout=timedelta(minutes=2)
        )
        
        borrower_context.agent2_summary = agent2_handoff
        
        # Phase 3: Agent 3 - Final Notice
        print(f"Starting Agent 3 final notice for {borrower_context.name}")
        agent3_result = await workflow.execute_activity(
            "run_final_notice_agent",
            agent2_handoff,
            borrower_context,
            start_to_close_timeout=timedelta(minutes=5)
        )
        
        # Update context with Agent 3 results
        borrower_context.agent3_result = agent3_result.get("result", {})
        borrower_context.agent3_messages = agent3_result.get("messages", [])
        borrower_context.final_outcome = agent3_result.get("outcome", "unresolved")
        borrower_context.advance_stage("completed")
        
        return {
            "status": borrower_context.final_outcome,
            "borrower_context": borrower_context.to_dict()
        }