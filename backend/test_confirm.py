import asyncio
import uuid

import structlog

from app.agents.graph import run_agent
from app.db.models import Conversation, Message, ToolCall, ToolCallStatus
from app.db.session import async_session_factory

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))


async def test_confirm():
    # Insert a fake pending tool call to simulate state after previous turn
    conv_id = uuid.uuid4()
    msg_id = uuid.uuid4()

    async with async_session_factory() as session:
        conv = Conversation(
            id=conv_id, user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"), title="Test"
        )
        session.add(conv)
        msg = Message(id=msg_id, conversation_id=conv_id, role="assistant", content="confirm?")
        session.add(msg)
        tc = ToolCall(
            message_id=msg_id,
            tool_name="create_demo_request",
            tool_input='{"company":"John Farms","requirements":"just to see the dashboard"}',
            status=ToolCallStatus.PENDING,
        )
        session.add(tc)
        await session.commit()

    query = "yes, confirm"
    print(f"Testing confirmation with query: {query}")

    result = await run_agent(
        query=query,
        conversation_id=str(conv_id),
        user_id="00000000-0000-0000-0000-000000000000",
    )

    print("FINAL INTENT:", result.intent)
    print("FINAL RESPONSE:", result.response)


if __name__ == "__main__":
    asyncio.run(test_confirm())
