#!/usr/bin/env python3
"""
Trigger a borrower workflow via Temporal.

Usage:
  python run_workflow.py                          # Default test borrower
  python run_workflow.py --name "Jane Doe" --phone "+15551234567" --balance 6500
"""

import asyncio
import argparse
import os
import uuid
from temporalio.client import Client


async def run(name: str, phone: str, balance: float):
    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    client = await Client.connect(temporal_host)

    workflow_id = f"borrower-{uuid.uuid4().hex[:8]}"
    borrower_data = {
        "name": name,
        "phone": phone,
        "balance": balance,
    }

    print(f"Starting workflow: {workflow_id}")
    print(f"  Borrower: {name}")
    print(f"  Phone:    {phone}")
    print(f"  Balance:  ${balance:,.2f}")
    print()

    handle = await client.start_workflow(
        "BorrowerWorkflow",
        borrower_data,
        id=workflow_id,
        task_queue="collections",
    )

    print(f"Workflow started. Waiting for completion...")
    print(f"  Temporal UI: http://localhost:8233/namespaces/default/workflows/{workflow_id}")
    print()

    result = await handle.result()
    print("=" * 60)
    print(f"WORKFLOW RESULT: {result.get('status', 'unknown')}")
    print(f"  Phase:   {result.get('phase', 'unknown')}")
    if result.get("deal_terms"):
        print(f"  Deal:    {result['deal_terms']}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trigger borrower workflow")
    parser.add_argument("--name", default="John Smith", help="Borrower name")
    parser.add_argument("--phone", default="+15551234567", help="Phone (E.164)")
    parser.add_argument("--balance", type=float, default=4800.0, help="Debt balance")
    args = parser.parse_args()

    asyncio.run(run(args.name, args.phone, args.balance))
