from temporalio import workflow
from datetime import timedelta

@workflow.defn
class BorrowerCollectionsWorkflow:

    def __init__(self):
        self.voice_result = None

    @workflow.signal
    def voice_call_completed(self, result: dict):
        self.voice_result = result

    @workflow.run
    async def run(self, borrower: dict):

        assessment = await workflow.execute_activity(
            "run_assessment_agent",
            borrower,
            start_to_close_timeout=timedelta(hours=24)
        )

        handoff_1 = await workflow.execute_activity(
            "summarize_chat",
            assessment,
            start_to_close_timeout=timedelta(minutes=2)
        )

        call_id = await workflow.execute_activity(
            "initiate_voice_call",
            handoff_1,
            start_to_close_timeout=timedelta(minutes=5)
        )

        await workflow.wait_condition(
            lambda: self.voice_result is not None,
            timeout=timedelta(hours=1)
        )

        if self.voice_result["outcome"] == "deal_agreed":
            return {"status": "resolved"}

        handoff_2 = await workflow.execute_activity(
            "summarize_combined",
            [assessment, self.voice_result],
            start_to_close_timeout=timedelta(minutes=2)
        )

        final = await workflow.execute_activity(
            "run_final_notice_agent",
            handoff_2,
            start_to_close_timeout=timedelta(hours=48)
        )

        return final
