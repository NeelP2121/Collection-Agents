import asyncio
from temporalio.client import Client

async def run():
    client = await Client.connect("localhost:7233")

    handle = await client.start_workflow(
        "BorrowerWorkflow.run",
        {"name": "John Doe", "phone": "+123456789"},
        id="multi-agent-test",
        task_queue="collections"
    )

    result = await handle.result()
    print("FINAL RESULT:", result)

if __name__ == "__main__":
    asyncio.run(run())