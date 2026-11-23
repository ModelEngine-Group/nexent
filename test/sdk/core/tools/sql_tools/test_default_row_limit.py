"""Regression tests for unlimited SQL results unless a row limit is requested."""

import json
from unittest.mock import MagicMock

import pytest

from sdk.nexent.core.tools.sql_tools.mssql_tool import MsSqlTool
from sdk.nexent.core.tools.sql_tools.mysql_tool import MySqlTool
from sdk.nexent.core.tools.sql_tools.postgres_tool import PostgreSqlTool


@pytest.fixture(params=[
    (MySqlTool, "mysql_tool.pymysql", True),
    (PostgreSqlTool, "postgres_tool.psycopg2", False),
    (MsSqlTool, "mssql_tool.pymssql", True),
], ids=["mysql", "postgres", "mssql"])
def database_tool(request, mocker):
    tool_class, driver_path, dict_rows = request.param
    driver = mocker.patch(f"sdk.nexent.core.tools.sql_tools.{driver_path}")
    cursor = MagicMock()
    rows = [{"id": i} for i in range(101)] if dict_rows else [(i,) for i in range(101)]
    cursor.fetchall.return_value = rows
    cursor.fetchmany.return_value = rows[:7]
    cursor.description = [("id",)]
    connection = driver.connect.return_value
    connection.cursor.return_value = cursor
    tool = tool_class(host="localhost", user="user", password="password", database="db", observer=None)
    return tool, cursor, driver, connection


@pytest.mark.parametrize("options", [{}, {"max_rows": None}, {"max_rows": 0}, {"max_rows": -1}])
def test_no_implicit_row_limit(database_tool, options):
    tool, cursor, _, connection = database_tool
    result = json.loads(tool.forward("SELECT id FROM users", **options))

    assert result["status"] == "success"
    assert result["row_count"] == 101
    assert result["rows"] == [[i] for i in range(101)]
    cursor.execute.assert_called_once_with("SELECT id FROM users")
    cursor.fetchall.assert_called_once_with()
    cursor.fetchmany.assert_not_called()
    connection.close.assert_called_once_with()


def test_explicit_row_limit_still_applies(database_tool):
    tool, cursor, _, _ = database_tool
    result = json.loads(tool.forward("SELECT id FROM users", max_rows=7))

    assert result["status"] == "success"
    cursor.execute.assert_called_once_with("SELECT id FROM users")
    cursor.fetchmany.assert_called_once_with(7)
    cursor.fetchall.assert_not_called()
    assert result["row_count"] == 7


@pytest.mark.parametrize("sql", [
    "SELECT id FROM users;",
    "SELECT id FROM users ORDER BY id -- Keep this comment",
    "WITH selected AS (SELECT id FROM users) SELECT id FROM selected",
    "SELECT 1 UNION ALL SELECT 2",
    "UPDATE users SET name = 'Alice' WHERE id = 1",
])
def test_explicit_limit_does_not_modify_sql(database_tool, sql):
    tool, cursor, _, _ = database_tool
    result = json.loads(tool.forward(sql, max_rows=7))

    assert result["status"] == "success"
    cursor.execute.assert_called_once_with(sql)
    cursor.fetchmany.assert_called_once_with(7)


@pytest.mark.parametrize("options", [{}, {"max_rows": 7}])
def test_sql_limit_is_preserved(database_tool, options):
    tool, cursor, _, _ = database_tool
    sql = "SELECT TOP 3 id FROM users" if isinstance(tool, MsSqlTool) else "SELECT id FROM users LIMIT 3"
    result = json.loads(tool.forward(sql, **options))

    assert result["status"] == "success"
    cursor.execute.assert_called_once_with(sql)
    if options:
        cursor.fetchmany.assert_called_once_with(7)
    else:
        cursor.fetchmany.assert_not_called()


def test_security_error_does_not_connect(database_tool):
    tool, cursor, driver, _ = database_tool
    result = json.loads(tool.forward("DELETE FROM users"))

    assert result["status"] == "error"
    assert "MISSING_WHERE" in result["message"]
    driver.connect.assert_not_called()
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("max_rows", [0, 7])
def test_query_error_closes_connection(database_tool, max_rows):
    tool, cursor, _, connection = database_tool
    cursor.fetchall.side_effect = RuntimeError("Query failed")
    cursor.fetchmany.side_effect = RuntimeError("Query failed")
    result = json.loads(tool.forward("SELECT id FROM users", max_rows=max_rows))

    assert result["status"] == "error"
    assert result["message"] == "Query failed"
    assert result["rows"] == []
    connection.close.assert_called_once_with()
