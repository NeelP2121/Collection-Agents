import asyncio
import os
from temporalio.client import Client
from temporalio.worker import Worker

from temporal.workflow import BorrowerWorkflow
from temporal.activities import (
    run_assessment_agent,
    generate_handoff_ledger,
    run_voice_resolution_agent,
    run_final_notice_agent
)

async def main():
    # Use environment variable if available, else localhost (important for docker)
    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    client = await Client.connect(temporal_host)

    worker = Worker(
        client,
        task_queue="collections",
        workflows=[BorrowerWorkflow],
        activities=[
            run_assessment_agent,
            generate_handoff_ledger,
            run_voice_resolution_agent,
            run_final_notice_agent
        ]
    )

    print(f"Worker connected to {temporal_host} and listening on task queue 'collections'...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())