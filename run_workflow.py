import asyncio
import uuid
from temporalio.client import Client

async def run():
    client = await Client.connect("localhost:7233")

    workflow_id = f"test-{uuid.uuid4()}"
    handle = await client.start_workflow(
        "BorrowerWorkflow",
        {"name": "John Doe", "phone": "+123456789"},
        id=workflow_id,
        task_queue="collections"
    )

    result = await handle.result()
    print("FINAL RESULT:", result)

if __name__ == "__main__":
    asyncio.run(run())