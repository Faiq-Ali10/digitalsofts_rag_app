"""Integration tests for Tool Registry and execution."""

import pytest

from app.db.models import UserRole
from app.tools.registry import ToolDefinition, execute_tool, register_all_tools, register_tool


@pytest.mark.asyncio
async def test_execute_tool_invalid_tool():
    """Test executing a non-existent tool raises ValueError."""
    with pytest.raises(ValueError, match="is not registered"):
        await execute_tool(
            tool_name="non_existent_tool",
            tool_input={},
            user_id="test_user",
            user_role=UserRole.USER
        )

@pytest.mark.asyncio
async def test_execute_tool_permission_denied():
    """Test executing a tool with insufficient permissions."""
    register_all_tools()

    # search_products requires user. Let's make a mock tool requiring admin.
    async def mock_admin_tool():
        return {}

    register_tool(ToolDefinition(
        name="admin_only_tool",
        description="test",
        handler=mock_admin_tool,
        required_role="admin"
    ))

    with pytest.raises(PermissionError, match="Insufficient permissions"):
        await execute_tool(
            tool_name="admin_only_tool",
            tool_input={},
            user_id="test_user",
            user_role=UserRole.USER
        )

@pytest.mark.asyncio
async def test_execute_tool_invalid_args():
    """Test executing a tool with invalid arguments."""
    register_all_tools()
    # search_products requires 'query' but we pass an empty dict, which should raise a TypeError when unpacking or calling.  # noqa: E501
    with pytest.raises(TypeError):
        await execute_tool(
            tool_name="search_products",
            tool_input={},
            user_id="test_user",
            user_role=UserRole.USER
        )
