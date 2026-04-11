"""Wait for Temporal server to become available, then start the worker."""
import asyncio
import sys
import time


async def wait_for_temporal(host: str, max_wait: int = 120):
    """Poll Temporal until it accepts connections."""
    from temporalio.client import Client

    start = time.time()
    while time.time() - start < max_wait:
        try:
            client = await Client.connect(host)
            # If connect succeeds, Temporal is up
            print(f"Temporal is ready at {host}")
            return True
        except Exception:
            elapsed = int(time.time() - start)
            print(f"Waiting for Temporal at {host}... ({elapsed}s)")
            await asyncio.sleep(2)

    print(f"Temporal not available after {max_wait}s")
    return False


async def main():
    import os
    host = os.getenv("TEMPORAL_HOST", "localhost:7233")

    if not await wait_for_temporal(host):
        sys.exit(1)

    # Import and run worker
    from workers.main import main as worker_main
    await worker_main()


if __name__ == "__main__":
    asyncio.run(main())
