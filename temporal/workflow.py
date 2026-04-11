import asyncio  # only for asyncio.TimeoutError in wait_condition
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from datetime import timedelta
from models.borrower_state import BorrowerContext


# Retry policies — separate transient (LLM API flakes) from permanent errors
_TRANSIENT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ComplianceFatalError", "BudgetExceededError"],
)

_VOICE_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ComplianceFatalError"],
)

_HANDOFF_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=3),
)

# Workflow-level retry config for borrower no-response
_MAX_NO_RESPONSE_RETRIES = 3
_NO_RESPONSE_DELAY = timedelta(hours=24)  # Wait 24h between retry attempts


@workflow.defn
class BorrowerWorkflow:

    def __init__(self):
        self.voice_result = None
        self.no_response_attempts = 0

    @workflow.signal
    def voice_done(self, result: dict):
        """Signal received from VAPI webhook when voice call ends."""
        self.voice_result = result

    @workflow.run
    async def run(self, borrower_data: dict):
        """
        Three-agent debt collection pipeline:
          1. Assessment Agent (Chat) — verify identity, gather financial info
          2. Resolution Agent (Voice) — negotiate settlement via phone call
          3. Final Notice Agent (Chat) — last offer with consequences

        Outcome-based transitions:
          - deal_agreed in Phase 2 → EXIT (resolved_voice)
          - stop_contact in Phase 2 → EXIT (stop_contact)
          - hardship_referral in Phase 2 → EXIT (hardship_referral)
          - no_deal in Phase 2 → Phase 3
          - resolved in Phase 3 → EXIT (resolved_final_notice)
          - unresolved in Phase 3 → EXIT (flag for legal/write-off)
        """
        borrower_context = BorrowerContext(
            name=borrower_data.get("name", "Unknown"),
            phone=borrower_data.get("phone", ""),
            balance=borrower_data.get("balance", 4200.0),
            workflow_id=workflow.info().workflow_id,
        )

        # ── Phase 1: Assessment (Chat) ──────────────────────────
        workflow.logger.info(f"Phase 1: Assessment for {borrower_context.name}")

        try:
            agent1_result = await workflow.execute_activity(
                "run_assessment_agent",
                borrower_context.to_dict(),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_TRANSIENT_RETRY,
            )
        except ActivityError as e:
            workflow.logger.error(f"Assessment activity failed after retries: {e}")
            borrower_context.final_outcome = "activity_failure"
            borrower_context.advance_stage("completed")
            return {"status": "activity_failure", "phase": "assessment",
                    "error": str(e),
                    "borrower_context": borrower_context.to_dict()}

        # Merge activity results back into workflow-local context
        borrower_context.agent1_result = agent1_result.get("result", {})
        borrower_context.agent1_messages = agent1_result.get("messages", [])
        borrower_context.identity_verified = agent1_result.get("result", {}).get(
            "identity_verified", False
        )
        borrower_context.balance = agent1_result.get("result", {}).get(
            "balance", borrower_context.balance
        )
        borrower_context.employment_status = agent1_result.get("result", {}).get(
            "employment_status", borrower_context.employment_status
        )
        borrower_context.hardship_detected = agent1_result.get("result", {}).get(
            "hardship_detected", borrower_context.hardship_detected
        )
        borrower_context.ability_to_pay = agent1_result.get("result", {}).get(
            "ability_to_pay", borrower_context.ability_to_pay
        )

        # Check for early exit: stop contact or failed verification
        a1_outcome = agent1_result.get("outcome", "completed")
        if a1_outcome == "stop_requested":
            borrower_context.mark_stop_contact()
            borrower_context.final_outcome = "stop_contact"
            borrower_context.advance_stage("completed")
            return {"status": "stop_contact", "phase": "assessment",
                    "borrower_context": borrower_context.to_dict()}

        if a1_outcome == "failed_verification":
            borrower_context.final_outcome = "failed_verification"
            borrower_context.advance_stage("completed")
            return {"status": "failed_verification", "phase": "assessment",
                    "borrower_context": borrower_context.to_dict()}

        borrower_context.advance_stage("resolution")

        # Generate Agent 1 → Agent 2 handoff ledger (≤500 tokens)
        workflow.logger.info("Generating Agent 1 → 2 handoff ledger")
        try:
            agent1_handoff = await workflow.execute_activity(
                "generate_handoff_ledger",
                borrower_context.agent1_messages,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_HANDOFF_RETRY,
            )
        except ActivityError as e:
            workflow.logger.error(f"Handoff generation failed: {e}")
            # Fallback: pass minimal context
            agent1_handoff = {
                "identity_verified": borrower_context.identity_verified,
                "balance": borrower_context.balance,
                "hardship_detected": borrower_context.hardship_detected,
                "summary": "Handoff generation failed — minimal context available.",
            }

        borrower_context.agent1_summary = agent1_handoff  # dict

        # ── Phase 2: Resolution (Voice via VAPI) ────────────────
        workflow.logger.info(f"Phase 2: Voice resolution for {borrower_context.name}")

        try:
            vapi_trigger = await workflow.execute_activity(
                "run_voice_resolution_agent",
                args=[agent1_handoff, borrower_context.to_dict()],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_VOICE_RETRY,
            )
        except ActivityError as e:
            workflow.logger.error(f"Voice activity failed after retries: {e}")
            # Voice failure is not fatal — fall through to Final Notice
            vapi_trigger = {
                "status": "completed",
                "outcome": "no_deal",
                "transcript": "",
                "offers_made": [],
                "outcome_reasoning": f"Voice activity failed: {e}",
            }

        call_id = vapi_trigger.get("call_id")
        workflow.logger.info(f"VAPI call initiated: {call_id}")

        # If this was a simulation (VAPI unavailable), we already have results
        if vapi_trigger.get("status") == "completed":
            agent2_result = vapi_trigger
        else:
            # Suspend workflow until VAPI webhook signals voice_done
            workflow.logger.info("Suspended — waiting for voice call to complete...")
            try:
                await workflow.wait_condition(
                    lambda: self.voice_result is not None,
                    timeout=timedelta(minutes=10),
                )
                workflow.logger.info("Voice call completed — resuming workflow")
                agent2_result = self.voice_result or {}
            except asyncio.TimeoutError:
                workflow.logger.warning("Voice call timed out after 10 minutes")
                agent2_result = {
                    "outcome": "no_deal",
                    "transcript": "",
                    "offers_made": [],
                    "outcome_reasoning": "Voice call timed out — no response from VAPI",
                }

        # Update context with voice results
        borrower_context.agent2_result = agent2_result
        borrower_context.agent2_transcript = agent2_result.get("transcript", "")
        borrower_context.agent2_offers_made = agent2_result.get("offers_made", [])

        # Check voice outcome for early exits
        voice_outcome = agent2_result.get("outcome", "no_deal")

        borrower_state = agent2_result.get("borrower_state", {})
        if borrower_state.get("stop_contact_requested") or voice_outcome == "stop_contact":
            borrower_context.mark_stop_contact()
            borrower_context.final_outcome = "stop_contact"
            borrower_context.advance_stage("completed")
            return {"status": "stop_contact", "phase": "resolution",
                    "borrower_context": borrower_context.to_dict()}

        if voice_outcome == "hardship_referral":
            borrower_context.final_outcome = "hardship_referral"
            borrower_context.advance_stage("completed")
            return {"status": "hardship_referral", "phase": "resolution",
                    "borrower_context": borrower_context.to_dict()}

        # ── Workflow-level no-response retry ────────────────────
        # (Retry logic remains same, but if it eventually gets a deal_agreed, it will fall through to Phase 3)
        # If voice outcome is "no_response" (borrower didn't pick up),
        # retry up to 3 times with a delay between attempts.
        if voice_outcome == "no_response" and self.no_response_attempts < _MAX_NO_RESPONSE_RETRIES:
            self.no_response_attempts += 1
            workflow.logger.info(
                f"No response from borrower — retry {self.no_response_attempts}/"
                f"{_MAX_NO_RESPONSE_RETRIES}. Waiting {_NO_RESPONSE_DELAY}."
            )
            await workflow.sleep(_NO_RESPONSE_DELAY.total_seconds())

            # Reset voice result for next attempt
            self.voice_result = None
            try:
                vapi_trigger = await workflow.execute_activity(
                    "run_voice_resolution_agent",
                    args=[agent1_handoff, borrower_context.to_dict()],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=_VOICE_RETRY,
                )
            except ActivityError:
                vapi_trigger = {"status": "completed", "outcome": "no_deal",
                                "transcript": "", "offers_made": []}

            call_id = vapi_trigger.get("call_id")
            if vapi_trigger.get("status") == "completed":
                agent2_result = vapi_trigger
            else:
                try:
                    await workflow.wait_condition(
                        lambda: self.voice_result is not None,
                        timeout=timedelta(minutes=10),
                    )
                    agent2_result = self.voice_result or {}
                except asyncio.TimeoutError:
                    agent2_result = {"outcome": "no_response", "transcript": "",
                                     "offers_made": []}

            voice_outcome = agent2_result.get("outcome", "no_deal")
            borrower_context.agent2_result = agent2_result
            borrower_context.agent2_transcript = agent2_result.get("transcript", "")
            borrower_context.agent2_offers_made = agent2_result.get("offers_made", [])

            # Re-check ALL early exits after retry (not just deal_agreed)
            retry_borrower_state = agent2_result.get("borrower_state", {})
            if retry_borrower_state.get("stop_contact_requested") or voice_outcome == "stop_contact":
                borrower_context.mark_stop_contact()
                borrower_context.final_outcome = "stop_contact"
                borrower_context.advance_stage("completed")
                return {"status": "stop_contact", "phase": "resolution",
                        "borrower_context": borrower_context.to_dict()}

            if voice_outcome == "hardship_referral":
                borrower_context.final_outcome = "hardship_referral"
                borrower_context.advance_stage("completed")
                return {"status": "hardship_referral", "phase": "resolution",
                        "borrower_context": borrower_context.to_dict()}

        if voice_outcome == "no_response" and self.no_response_attempts >= _MAX_NO_RESPONSE_RETRIES:
            workflow.logger.warning(
                f"Borrower unreachable after {_MAX_NO_RESPONSE_RETRIES} attempts."
            )

        borrower_context.advance_stage("final_notice")

        # ── Phase 3: Final Notice (Chat) ────────────────────────
        workflow.logger.info("Generating Agent 2 → 3 handoff ledger")

        combined_history = [{"source": "agent1_chat", "ledger": agent1_handoff}]
        if borrower_context.agent2_transcript:
            combined_history.append({
                "source": "agent2_voice",
                "transcript": borrower_context.agent2_transcript,
                "outcome": voice_outcome,
                "offers_made": agent2_result.get("offers_made", []),
                "objections": agent2_result.get("objections", []),
                "borrower_state": borrower_state,
            })

        try:
            agent2_handoff = await workflow.execute_activity(
                "generate_handoff_ledger",
                combined_history,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_HANDOFF_RETRY,
            )
        except ActivityError as e:
            workflow.logger.error(f"Agent 2→3 handoff generation failed: {e}")
            agent2_handoff = {
                "prior_outcome": voice_outcome,
                "offers_rejected": agent2_result.get("offers_made", []),
                "hardship_detected": borrower_context.hardship_detected,
                "summary": "Handoff generation failed — minimal context available.",
            }

        borrower_context.agent2_summary = agent2_handoff

        workflow.logger.info(f"Phase 3: Final notice for {borrower_context.name}")

        try:
            agent3_result = await workflow.execute_activity(
                "run_final_notice_agent",
                args=[agent2_handoff, borrower_context.to_dict()],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_TRANSIENT_RETRY,
            )
        except ActivityError as e:
            workflow.logger.error(f"Final notice activity failed: {e}")
            borrower_context.final_outcome = "activity_failure"
            borrower_context.advance_stage("completed")
            return {"status": "activity_failure", "phase": "final_notice",
                    "error": str(e),
                    "borrower_context": borrower_context.to_dict()}

        borrower_context.agent3_result = agent3_result.get("result", {})
        borrower_context.agent3_messages = agent3_result.get("messages", [])
        borrower_context.final_outcome = agent3_result.get("outcome", "unresolved")
        borrower_context.advance_stage("completed")

        return {
            "status": borrower_context.final_outcome,
            "phase": "final_notice",
            "borrower_context": borrower_context.to_dict(),
        }
