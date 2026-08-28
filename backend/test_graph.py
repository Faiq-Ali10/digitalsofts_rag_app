import asyncio
import uuid

import structlog

from app.agents.graph import run_agent

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(20),
)


async def main():
    query = "I want a demo of the Poultry ERP. My name is John, my email is john@farm.com. My company is John Farms, and my requirement is just to see the dashboard."

    result = await run_agent(
        query=query,
        conversation_id=str(uuid.uuid4()),
        user_id="00000000-0000-0000-0000-000000000000",
    )

    print("FINAL INTENT:", result.intent)
    print("FINAL RESPONSE:", result.response)


if __name__ == "__main__":
    asyncio.run(main())
