"""
MySQL Database Tool

Execute SQL queries on MySQL database.
"""
import logging
from typing import Any, List, Optional, Tuple

from pydantic import Field

from .sql_database_base_tool import SqlDatabaseBaseTool
from ....core.utils.tools_common_message import ToolCategory, ToolSign


logger = logging.getLogger("mysql_tool")

import pymysql  # MySQL driver


class MySqlTool(SqlDatabaseBaseTool):
    """Tool for executing SQL queries on MySQL database."""

    name = "mysql_database"
    description = (
        "Execute SQL queries on MySQL database. "
        "This tool provides a standardized interface for AI agents to query MySQL databases. "
        "It supports parameter binding and security controls. "
        "Security restrictions: DROP DATABASE, GRANT, REVOKE, CREATE USER, INTO OUTFILE, LOAD DATA INFILE are forbidden. "
        "UPDATE and DELETE statements require a WHERE clause. "
        "Input: sql, parameters (optional). "
        "Output: JSON containing execution status, column names, rows, row_count, and execution_time_ms."
    )
    description_zh = (
        "在 MySQL 数据库上执行 SQL 查询。该工具为 AI 智能体提供标准化的 MySQL 数据库操作接口。"
        "支持参数绑定和安全控制。"
        "安全限制：禁止执行 DROP DATABASE、GRANT、REVOKE、CREATE USER、INTO OUTFILE、LOAD DATA INFILE 等危险操作。"
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
                "'SELECT name, email FROM orders WHERE status = ? AND amount > ?'"
            ),
            "description_zh": (
                "要执行的 SQL 查询。使用 ? 作为参数占位符进行参数化查询。"
                "示例：'SELECT * FROM users WHERE id = ?'、"
                "'SELECT name, email FROM orders WHERE status = ? AND amount > ?'"
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
        host: str = Field(description="MySQL database host IP or domain"),
        user: str = Field(description="MySQL database username"),
        password: str = Field(description="MySQL database password"),
        database: str = Field(description="MySQL database name"),
        port: int = Field(description="MySQL database port", default=3306),
        observer: Any = Field(description="Message observer for real-time status updates", default=None, exclude=True),
    ):
        super().__init__(observer=observer)
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database

    @property
    def db_type(self) -> str:
        return "mysql"

    @property
    def tool_name(self) -> str:
        return "mysql_database"

    @property
    def default_port(self) -> int:
        return 3306

    def _execute_query(
        self,
        sql: str,
        parameters: Optional[List[Any]],
        max_rows: int,
        timeout: int,
    ) -> Tuple[List[List[Any]], List[str]]:
        conn = None
        try:
            conn = pymysql.connect(
                host=self._host,
                port=self._port or self.default_port,
                user=self._user,
                password=self._password,
                database=self._database,
                connect_timeout=timeout,
                read_timeout=timeout,
                write_timeout=timeout,
            )

            cursor = conn.cursor(pymysql.cursors.DictCursor)

            if max_rows > 0:
                sql = self._add_limit_clause(sql, max_rows)

            if parameters:
                cursor.execute(sql, parameters)
            else:
                cursor.execute(sql)

            rows = cursor.fetchall()
            columns = list(rows[0].keys()) if rows else []
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
        Execute SQL query on MySQL database.

        Args:
            sql: SQL query to execute
            parameters: Optional list of parameter values for parameterized queries
            max_rows: Maximum number of rows to return (default 100)
            timeout: Query timeout in seconds (default 10)

        Returns:
            JSON string containing execution result
        """
        return super().forward(sql=sql, parameters=parameters, max_rows=max_rows, timeout=timeout)
