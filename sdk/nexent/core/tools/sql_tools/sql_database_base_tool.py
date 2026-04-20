"""
SQL Database Tool Base Classes

Provides common functionality for all SQL database tools including:
- Security validation (SQL blacklist, WHERE clause enforcement)
- SQL dialect conversion (LIMIT clause adaptation)
- Result formatting
"""
import json
import logging
import re
import time
from typing import Any, List, Optional, Tuple

from pydantic import Field
from smolagents.tools import Tool

from ....core.utils.observer import MessageObserver, ProcessType


logger = logging.getLogger("sql_database_base")


HIGH_RISK_SQL_PATTERNS = [
    (re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE), "DROP DATABASE", "DROP_DATABASE"),
    (re.compile(r"\bGRANT\b", re.IGNORECASE), "GRANT", "GRANT"),
    (re.compile(r"\bREVOKE\b", re.IGNORECASE), "REVOKE", "REVOKE"),
    (re.compile(r"\bCREATE\s+USER\b", re.IGNORECASE), "CREATE USER", "CREATE_USER"),
    (re.compile(r"\bINTO\s+OUTFILE\b", re.IGNORECASE), "INTO OUTFILE", "INTO_OUTFILE"),
    (re.compile(r"\bLOAD\s+DATA\s+INFILE\b", re.IGNORECASE), "LOAD DATA INFILE", "LOAD_DATA_INFILE"),
    (re.compile(r"\bEXEC\s+xp_", re.IGNORECASE), "EXEC xp_", "EXEC_XP"),
]

WHERE_REQUIRED_PATTERNS = [
    (re.compile(r"\bUPDATE\s+.*\s+SET\b", re.IGNORECASE), "UPDATE"),
    (re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE), "DELETE"),
]


class SqlDatabaseBaseTool(Tool):
    """
    Base class for SQL database tools.

    Provides common functionality:
    - Security validation (SQL blacklist, WHERE clause enforcement)
    - SQL dialect conversion (LIMIT clause adaptation)
    - Result formatting
    """

    def __init__(
        self,
        observer: MessageObserver = Field(
            description="Message observer for real-time status updates",
            default=None,
            exclude=True,
        ),
    ):
        super().__init__()
        self.observer = observer
        self.running_prompt_zh = "正在执行 SQL 查询..."
        self.running_prompt_en = "Executing SQL query..."

    @property
    def db_type(self) -> str:
        """Database type identifier."""
        raise NotImplementedError("Subclasses must implement db_type property")

    @property
    def tool_name(self) -> str:
        """Tool name for this database."""
        raise NotImplementedError("Subclasses must implement tool_name property")

    @property
    def default_port(self) -> int:
        """Default port for this database."""
        raise NotImplementedError("Subclasses must implement default_port property")

    def _execute_query(
        self,
        sql: str,
        parameters: Optional[List[Any]],
        max_rows: int,
        timeout: int,
    ) -> Tuple[List[List[Any]], List[str]]:
        """
        Execute query on the database.

        Args:
            sql: SQL query to execute
            parameters: Parameter values for binding
            max_rows: Maximum rows to return
            timeout: Query timeout in seconds

        Returns:
            Tuple of (rows, columns)
        """
        raise NotImplementedError("Subclasses must implement _execute_query method")

    def forward(
        self,
        sql: str,
        parameters: Optional[List[Any]] = None,
        max_rows: Optional[int] = 100,
        timeout: Optional[int] = 10,
    ) -> str:
        """
        Execute SQL query on the database.

        Args:
            sql: SQL query to execute (supports standard ANSI SQL)
            parameters: Optional list of parameter values for parameterized queries
            max_rows: Maximum number of rows to return (default 100)
            timeout: Query timeout in seconds (default 10)

        Returns:
            JSON string containing execution result with keys:
            - status: "success" or "error"
            - columns: list of column names
            - rows: list of row data (max max_rows)
            - row_count: number of rows returned
            - execution_time_ms: execution time in milliseconds
            - message: status message or error details
        """
        try:
            if self.observer:
                running_prompt = (
                    self.running_prompt_zh
                    if self.observer.lang == "zh"
                    else self.running_prompt_en
                )
                self.observer.add_message("", ProcessType.TOOL, running_prompt)

            if max_rows is None:
                max_rows = 100
            if timeout is None:
                timeout = 10

            sql = self._preprocess_sql(sql)
            self._validate_sql_security(sql)

            start_time = time.time()
            rows, columns = self._execute_query(sql, parameters, max_rows, timeout)
            execution_time_ms = int((time.time() - start_time) * 1000)

            result = {
                "status": "success",
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "execution_time_ms": execution_time_ms,
                "message": f"Query executed successfully. Returned {len(rows)} rows in {execution_time_ms}ms.",
            }

            def json_serializer(obj):
                if hasattr(obj, "isoformat"):
                    return obj.isoformat()
                if isinstance(obj, (bytes, bytearray)):
                    return obj.decode("utf-8", errors="replace")
                if hasattr(obj, "__str__"):
                    return str(obj)
                raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

            return json.dumps(result, ensure_ascii=False, default=json_serializer)

        except Exception as e:
            logger.error(f"SQL execution error: {str(e)}")
            error_result = {
                "status": "error",
                "message": str(e),
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0,
            }
            return json.dumps(error_result, ensure_ascii=False)

    def _preprocess_sql(self, sql: str) -> str:
        """Preprocess SQL for dialect-specific conversions. Override in subclasses."""
        return sql

    def _validate_sql_security(self, sql: str) -> None:
        """Validate SQL for security concerns."""
        for pattern, name, code in HIGH_RISK_SQL_PATTERNS:
            if pattern.search(sql):
                raise Exception(
                    f"SQL SECURITY BLOCK: Forbidden operation '{name}' detected. "
                    f"This operation is not allowed for security reasons. "
                    f"Code: {code}"
                )

        for pattern, op_name in WHERE_REQUIRED_PATTERNS:
            if pattern.search(sql):
                where_pattern = re.compile(r"\bWHERE\b", re.IGNORECASE)
                if not where_pattern.search(sql):
                    raise Exception(
                        f"SQL SECURITY BLOCK: '{op_name}' statement must include a WHERE clause. "
                        f"For safety reasons, UPDATE and DELETE operations require WHERE conditions. "
                        f"Code: MISSING_WHERE"
                    )

    def _add_limit_clause(self, sql: str, max_rows: int) -> str:
        """Add LIMIT clause to SQL query. Override in subclasses for different syntax."""
        if max_rows <= 0:
            return sql
        sql = sql.strip().rstrip(";")
        return f"{sql} LIMIT {max_rows}"

    def _format_rows(self, rows, columns: List[str]) -> List[List[Any]]:
        """Format rows as list of lists."""
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return [list(row.values()) for row in rows]
        return [list(row) for row in rows]
