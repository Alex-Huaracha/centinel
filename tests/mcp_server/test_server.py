from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent
from sqlalchemy.orm import Session, sessionmaker

from centinel.config import get_settings
from centinel.mcp_server.server import create_server

pytestmark = pytest.mark.anyio

OCTOBER = {"start": "2026-10-01T00:00:00-05:00", "end": "2026-11-01T00:00:00-05:00"}


def _text(result: CallToolResult) -> str:
    content = result.content[0]
    assert isinstance(content, TextContent)
    return content.text


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(session_factory: sessionmaker[Session]) -> AsyncIterator[Client]:
    async with Client(create_server(session_factory)) as client:
        yield client


async def test_exposes_tools_with_read_only_hints(client: Client):
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    read_only = {
        name
        for name, tool in tools.items()
        if tool.annotations and tool.annotations.read_only_hint
    }
    assert set(tools) == {
        "get_current_time",
        "save_expense",
        "get_spending",
        "list_expenses",
        "find_merchant",
        "set_merchant_category",
        "list_categories",
        "create_category",
    }
    assert read_only == {
        "get_current_time",
        "get_spending",
        "list_expenses",
        "find_merchant",
        "list_categories",
    }


async def test_saved_expense_shows_up_in_spending(client: Client):
    await client.call_tool(
        "save_expense",
        {"data": {"amount": "25.50", "spent_at": "2026-10-10T12:00:00-05:00"}},
    )

    result = await client.call_tool("get_spending", {"data": OCTOBER})

    assert not result.is_error
    assert result.structured_content == {
        "result": [{"currency": "PEN", "total": "25.50", "count": 1}]
    }


async def test_service_error_reaches_the_model(client: Client):
    result = await client.call_tool(
        "get_spending", {"data": {**OCTOBER, "category": "pets"}}
    )

    assert result.is_error
    assert "Valid categories: food, shopping, transport" in _text(result)


async def test_invalid_input_is_rejected(client: Client):
    result = await client.call_tool("save_expense", {"data": {"amount": "0"}})

    assert result.is_error


async def test_current_time_uses_configured_timezone(client: Client):
    result = await client.call_tool("get_current_time", {})

    now = datetime.fromisoformat(_text(result))
    assert now.utcoffset() == datetime.now(get_settings().timezone).utcoffset()
