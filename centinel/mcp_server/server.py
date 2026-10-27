"""MCP server that exposes the expenses service as tools.

Each tool is a thin adapter: it opens a database session, calls the service and
turns an ExpenseError into a ToolError, so the model reads the message and can
correct its next call.
"""

from collections.abc import Callable
from datetime import datetime

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from sqlalchemy.orm import Session, sessionmaker

from centinel.config import get_settings
from centinel.db.engine import create_db_engine, create_session_factory
from centinel.expenses import service
from centinel.expenses.errors import ExpenseError
from centinel.expenses.schemas import (
    CreateCategoryInput,
    ExpenseOut,
    FindMerchantInput,
    GetSpendingInput,
    ListExpensesInput,
    MerchantOut,
    SaveExpenseInput,
    SetMerchantCategoryInput,
    SetMerchantCategoryOut,
    SpendingTotal,
)

INSTRUCTIONS = """\
Centinel tracks the user's personal expenses.
- Call get_current_time before resolving relative dates like "today" or "this month".
- Amounts are in PEN unless the user says otherwise.
- Pick categories only from list_categories. If one clearly fits, use it and tell
  the user which one. If none fits, ask the user for a name and create it with
  create_category; never invent one without asking.
- When an expense's merchant has no category yet, save it with
  set_merchant_category so future expenses there get it automatically.
- Never add up amounts in different currencies.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True)


def create_server(session_factory: sessionmaker[Session]) -> MCPServer:
    server = MCPServer("centinel", instructions=INSTRUCTIONS)

    def call[I, O](fn: Callable[[Session, I], O], data: I) -> O:
        with session_factory() as session:
            try:
                return fn(session, data)
            except ExpenseError as error:
                raise ToolError(str(error)) from error

    @server.tool(annotations=READ_ONLY)
    def get_current_time() -> str:
        """Current date and time in the user's timezone, as ISO 8601."""
        return datetime.now(get_settings().timezone).isoformat()

    @server.tool()
    def save_expense(data: SaveExpenseInput) -> ExpenseOut:
        """Register a new expense."""
        return call(service.save_expense, data)

    @server.tool(annotations=READ_ONLY)
    def get_spending(data: GetSpendingInput) -> list[SpendingTotal]:
        """Total spent in a period, one row per currency."""
        return call(service.get_spending, data)

    @server.tool(annotations=READ_ONLY)
    def list_expenses(data: ListExpensesInput) -> list[ExpenseOut]:
        """List expenses, most recent first."""
        return call(service.list_expenses, data)

    @server.tool(annotations=READ_ONLY)
    def find_merchant(data: FindMerchantInput) -> list[MerchantOut]:
        """Look up known merchants whose name contains the query."""
        return call(service.find_merchant, data)

    @server.tool()
    def set_merchant_category(data: SetMerchantCategoryInput) -> SetMerchantCategoryOut:
        """Learn a merchant's category and apply it to its uncategorized expenses."""
        return call(service.set_merchant_category, data)

    @server.tool(annotations=READ_ONLY)
    def list_categories() -> list[str]:
        """Names of all categories expenses can be filed under."""
        with session_factory() as session:
            return service.list_categories(session)

    @server.tool()
    def create_category(data: CreateCategoryInput) -> str:
        """Add a new category chosen by the user. Returns its name."""
        return call(service.create_category, data)

    return server


def main() -> None:
    server = create_server(create_session_factory(create_db_engine()))
    server.run("stdio")


if __name__ == "__main__":
    main()
