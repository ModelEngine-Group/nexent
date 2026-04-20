"""
SQLite Database Tool

Execute SQL queries on SQLite database.
"""
import logging
import sqlite3
from typing import Any, List, Optional, Tuple

from pydantic import Field

from .sql_database_base_tool import SqlDatabaseBaseTool
from ....core.utils.tools_common_message import ToolCategory, ToolSign


logger = logging.getLogger("sqlite_tool")


class SqliteTool(SqlDatabaseBaseTool):
    """Tool for executing SQL queries on SQLite database."""

    name = "sqlite_database"
    description = (
        "Execute SQL queries on SQLite database. "
        "SQLite is a lightweight, file-based database that requires no server. "
        "This tool provides a standardized interface for AI agents to query SQLite databases. "
        "It supports parameter binding and security controls. "
        "Security restrictions: DROP DATABASE (not applicable for SQLite), GRANT, REVOKE, CREATE USER, INTO OUTFILE, LOAD DATA INFILE are forbidden. "
        "UPDATE and DELETE statements require a WHERE clause. "
        "Input: sql, parameters (optional). "
        "Output: JSON containing execution status, column names, rows, row_count, and execution_time_ms."
    )
    description_zh = (
        "在 SQLite 数据库上执行 SQL 查询。SQLite 是一个轻量级的基于文件的数据库，无需服务器。"
        "该工具为 AI 智能体提供标准化的 SQLite 数据库操作接口。"
        "支持参数绑定和安全控制。"
        "安全限制：禁止执行 GRANT、REVOKE、CREATE USER、INTO OUTFILE、LOAD DATA INFILE 等危险操作。"
        "UPDATE 和 DELETE 语句必须包含 WHERE 子句。"
        "输入：sql、parameters（可选）。"
        "输出：JSON格式的执行状态、列名、行数据、行数、执行时间。"
    )

    inputs = {
        "sql": {
            "type": "string",
            "description": (
                "SQL query to execute. Use ? as parameter placeholders for "
                "parameterized queries. Examples: 'SELECT * FROM users WHERE id = ?', "
                "'SELECT name, email FROM orders WHERE status = ?'"
            ),
            "description_zh": (
                "要执行的 SQL 查询。使用 ? 作为参数占位符进行参数化查询。"
                "示例：'SELECT * FROM users WHERE id = ?'"
            ),
            "required": True,
        },
        "parameters": {
            "type": "array",
            "description": (
                "Optional list of parameter values for parameterized queries. "
                "Parameters are bound in order to ? placeholders in the SQL."
            ),
            "description_zh": "可选的参数值列表，用于参数化查询。",
            "nullable": True,
        },
        "max_rows": {
            "type": "integer",
            "description": "Maximum number of rows to return. Default is 100.",
            "description_zh": "最多返回的行数，默认100。",
            "default": 100,
            "nullable": True,
        },
        "timeout": {
            "type": "integer",
            "description": "Query execution timeout in seconds. Default is 10 seconds.",
            "description_zh": "查询执行超时时间（秒），默认10秒。",
            "default": 10,
            "nullable": True,
        },
    }

    output_type = "string"
    category = ToolCategory.DATABASE.value
    tool_sign = ToolSign.DATABASE_OPERATION.value

    def __init__(
        self,
        database: str = Field(description="SQLite database file path (or ':memory:' for in-memory database)"),
        observer: Any = Field(description="Message observer for real-time status updates", default=None, exclude=True),
    ):
        super().__init__(observer=observer)
        self._database = database

    @property
    def db_type(self) -> str:
        return "sqlite"

    @property
    def tool_name(self) -> str:
        return "sqlite_database"

    @property
    def default_port(self) -> int:
        return 0

    def _execute_query(
        self,
        sql: str,
        parameters: Optional[List[Any]],
        max_rows: int,
        timeout: int,
    ) -> Tuple[List[List[Any]], List[str]]:
        conn = None
        try:
            conn = sqlite3.connect(self._database, timeout=timeout)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if max_rows > 0:
                sql = self._add_limit_clause(sql, max_rows)

            if parameters:
                cursor.execute(sql, parameters)
            else:
                cursor.execute(sql)

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows_data = self._format_rows(rows, columns)

            return rows_data, columns

        finally:
            if conn:
                conn.close()

    def forward(
        self,
        sql: str,
        parameters: Optional[List[Any]] = None,
        max_rows: Optional[int] = 100,
        timeout: Optional[int] = 10,
    ) -> str:
        """
        Execute SQL query on SQLite database.

        Args:
            sql: SQL query to execute
            parameters: Optional list of parameter values for parameterized queries
            max_rows: Maximum number of rows to return (default 100)
            timeout: Query timeout in seconds (default 10)

        Returns:
            JSON string containing execution result
        """
        return super().forward(sql=sql, parameters=parameters, max_rows=max_rows, timeout=timeout)
