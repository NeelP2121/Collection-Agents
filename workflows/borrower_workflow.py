from temporalio import workflow
from datetime import timedelta

@workflow.defn
class BorrowerWorkflow:

    @workflow.run
    async def run(self, borrower: dict):

        # Agent 1
        a1 = await workflow.execute_activity(
            "run_assessment_agent",
            borrower,
            start_to_close_timeout=timedelta(minutes=5)
        )

        # Summarize
        h1 = await workflow.execute_activity(
            "summarize_chat",
            a1["conversation"],
            start_to_close_timeout=timedelta(minutes=2)
        )

        # Agent 2 (voice)
        voice = await workflow.execute_activity(
            "run_voice_agent",
            h1,
            start_to_close_timeout=timedelta(minutes=5)
        )

        if voice["outcome"] == "deal_agreed":
            return {"status": "resolved_voice"}

        # Summarize combined
        h2 = await workflow.execute_activity(
            "summarize_combined",
            [a1, voice],
            start_to_close_timeout=timedelta(minutes=2)
        )

        # Agent 3
        final = await workflow.execute_activity(
            "run_final_agent",
            h2,
            start_to_close_timeout=timedelta(minutes=5)
        )

        return final
