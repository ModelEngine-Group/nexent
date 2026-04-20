"""
Oracle Database Tool

Execute SQL queries on Oracle database.
"""
import logging
import re
from typing import Any, List, Optional, Tuple

from pydantic import Field

from .sql_database_base_tool import SqlDatabaseBaseTool
from ....core.utils.tools_common_message import ToolCategory, ToolSign


logger = logging.getLogger("oracle_tool")

try:
    import cx_Oracle  # Oracle driver
except ImportError:
    cx_Oracle = None


class OracleSqlTool(SqlDatabaseBaseTool):
    """Tool for executing SQL queries on Oracle database."""

    name = "oracle_database"
    description = (
        "Execute SQL queries on Oracle database. "
        "This tool provides a standardized interface for AI agents to query Oracle databases. "
        "It supports parameter binding and security controls. "
        "Security restrictions: DROP DATABASE, GRANT, REVOKE, CREATE USER, INTO OUTFILE, LOAD DATA INFILE are forbidden. "
        "UPDATE and DELETE statements require a WHERE clause. "
        "Input: sql, parameters (optional). "
        "Output: JSON containing execution status, column names, rows, row_count, and execution_time_ms."
    )
    description_zh = (
        "在 Oracle 数据库上执行 SQL 查询。该工具为 AI 智能体提供标准化的 Oracle 数据库操作接口。"
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
                "SQL query to execute. Use :1, :2, ... as parameter placeholders for "
                "parameterized queries. Examples: 'SELECT * FROM users WHERE id = :1', "
                "'SELECT name, email FROM orders WHERE status = :1'"
            ),
            "description_zh": (
                "要执行的 SQL 查询。使用 :1, :2, ... 作为参数占位符进行参数化查询。"
                "示例：'SELECT * FROM users WHERE id = :1'"
            ),
            "required": True,
        },
        "parameters": {
            "type": "array",
            "description": (
                "Optional list of parameter values for parameterized queries. "
                "Parameters are bound in order to :1, :2, ... placeholders in the SQL."
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
        host: str = Field(description="Oracle database host IP or domain"),
        user: str = Field(description="Oracle database username"),
        password: str = Field(description="Oracle database password"),
        database: str = Field(description="Oracle database service name (SID or service name)"),
        port: int = Field(description="Oracle database port", default=1521),
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
        return "oracle"

    @property
    def tool_name(self) -> str:
        return "oracle_database"

    @property
    def default_port(self) -> int:
        return 1521

    def _preprocess_sql(self, sql: str) -> str:
        """Convert standard LIMIT clause to ROWNUM for Oracle."""
        limit_pattern = re.compile(
            r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?",
            re.IGNORECASE
        )

        def replace_limit(match):
            offset = match.group(2)
            limit = match.group(1)

            if offset:
                return f"ROWNUM <= {int(offset) + int(limit)} AND rnum > {offset}"
            else:
                return f"ROWNUM <= {limit}"

        return limit_pattern.sub(replace_limit, sql)

    def _convert_params_for_oracle(
        self, sql: str, parameters: Optional[List[Any]]
    ) -> Tuple[str, Optional[Tuple]]:
        """Convert standard ? placeholders to :1, :2, ... format."""
        if not parameters:
            return sql, None

        param_count = [0]

        def replace_placeholder(match):
            param_count[0] += 1
            return f":{param_count[0]}"

        converted_sql = re.sub(r"\?", replace_placeholder, sql)

        return converted_sql, tuple(parameters)

    def _add_limit_clause(self, sql: str, max_rows: int) -> str:
        """Oracle uses ROWNUM, which is handled in _preprocess_sql."""
        return sql

    def _execute_query(
        self,
        sql: str,
        parameters: Optional[List[Any]],
        max_rows: int,
        timeout: int,
    ) -> Tuple[List[List[Any]], List[str]]:
        if cx_Oracle is None:
            raise Exception(
                "cx_Oracle driver not installed. Please install it with: pip install cx_Oracle"
            )

        sql, parameters = self._convert_params_for_oracle(sql, parameters)

        conn = None
        try:
            dsn = cx_Oracle.makedsn(
                self._host,
                self._port or self.default_port,
                service_name=self._database,
            )

            conn = cx_Oracle.connect(
                user=self._user,
                password=self._password,
                dsn=dsn,
            )

            cursor = conn.cursor()

            if parameters:
                cursor.execute(sql, parameters)
            else:
                cursor.execute(sql)

            if max_rows > 0:
                rows = cursor.fetchmany(max_rows)
            else:
                rows = cursor.fetchall()

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows_data = self._format_rows(rows, columns)

            return rows_data, columns

        except ImportError:
            raise Exception(
                "cx_Oracle driver not installed. Please install it with: pip install cx_Oracle"
            )
        except Exception as e:
            if "DPI-1047" in str(e) or "Cannot locate" in str(e):
                raise Exception(
                    f"Oracle client library not found. Please install Oracle Instant Client. "
                    f"Original error: {str(e)}"
                )
            raise
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
        Execute SQL query on Oracle database.

        Args:
            sql: SQL query to execute
            parameters: Optional list of parameter values for parameterized queries
            max_rows: Maximum number of rows to return (default 100)
            timeout: Query timeout in seconds (default 10)

        Returns:
            JSON string containing execution result
        """
        return super().forward(sql=sql, parameters=parameters, max_rows=max_rows, timeout=timeout)
