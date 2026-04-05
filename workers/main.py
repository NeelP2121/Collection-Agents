import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

from workflows.borrower_workflow import BorrowerWorkflow
from workflows.activities import (
    run_assessment_agent,
    summarize_chat,
    run_voice_agent,
    summarize_combined,
    run_final_agent
)

async def main():
    client = await Client.connect("localhost:7233")

    worker = Worker(
        client,
        task_queue="collections",
        workflows=[BorrowerWorkflow],
        activities=[
            run_assessment_agent,
            summarize_chat,
            run_voice_agent,
            summarize_combined,
            run_final_agent
        ]
    )

    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())