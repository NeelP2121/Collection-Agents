import asyncio
from temporalio.worker import Worker
from temporalio.client import Client

from workflows.borrower_workflow import BorrowerCollectionsWorkflow
from workflows.activities import (
    run_assessment_agent,
    summarize_chat,
    run_voice_agent,
    summarize_combined,
    run_final_agent
)

async def main():
    client = await Client.connect("temporal:7233")

    worker = Worker(
        client,
        task_queue="collections-task-queue",
        workflows=[BorrowerCollectionsWorkflow],
        activities=[
            run_assessment_agent,
            summarize_chat,
            initiate_voice_call,
            summarize_combined,
            run_final_notice_agent
        ],
    )

    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
