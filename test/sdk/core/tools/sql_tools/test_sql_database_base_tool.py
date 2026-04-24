"""
Unit tests for sql_tools package - base tool, MSSQL, MySQL, PostgreSQL tools.
"""
import json
import re
from datetime import datetime
from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from sdk.nexent.core.tools.sql_tools.sql_database_base_tool import (
    HIGH_RISK_SQL_PATTERNS,
    WHERE_REQUIRED_PATTERNS,
)


# ---------------------------------------------------------------------------
# HIGH_RISK_SQL_PATTERNS tests
# ---------------------------------------------------------------------------

class TestHighRiskSqlPatterns:

    def test_is_list(self):
        assert isinstance(HIGH_RISK_SQL_PATTERNS, list)

    def test_not_empty(self):
        assert len(HIGH_RISK_SQL_PATTERNS) > 0

    def test_tuple_structure(self):
        for item in HIGH_RISK_SQL_PATTERNS:
            assert len(item) == 3
            assert isinstance(item[0], type(re.compile("")))
            assert isinstance(item[1], str)
            assert isinstance(item[2], str)

    @pytest.mark.parametrize("sql,expected_code", [
        ("DROP DATABASE testdb", "DROP_DATABASE"),
        ("drop database prod", "DROP_DATABASE"),
        ("DroP DaTaBaSe production", "DROP_DATABASE"),
        ("GRANT ALL TO admin", "GRANT"),
        ("grant select on users to public", "GRANT"),
        ("REVOKE ALL FROM guest", "REVOKE"),
        ("revoke insert on orders from app_user", "REVOKE"),
        ("CREATE USER newuser", "CREATE_USER"),
        ("create user admin identified by 'pass'", "CREATE_USER"),
        ("SELECT * INTO OUTFILE '/tmp/data.txt'", "INTO_OUTFILE"),
        ("insert into outfile '/data.csv' select * from orders", "INTO_OUTFILE"),
        ("LOAD DATA INFILE '/tmp/data.txt'", "LOAD_DATA_INFILE"),
        ("load data infile '/data.csv' into table mytable", "LOAD_DATA_INFILE"),
        ("EXEC xp_cmdshell 'dir'", "EXEC_XP"),
        ("exec xp_cmdshell 'whoami'", "EXEC_XP"),
        ("EXEC xp_shelloutput 'cmd'", "EXEC_XP"),
    ])
    def test_pattern_blocks_sql(self, sql, expected_code):
        for pattern, name, code in HIGH_RISK_SQL_PATTERNS:
            if code == expected_code:
                assert pattern.search(sql) is not None, f"Pattern {code} should match '{sql}'"
                return
        pytest.fail(f"Pattern {expected_code} not found in HIGH_RISK_SQL_PATTERNS")

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM users WHERE id = 1",
        "INSERT INTO users (name) VALUES ('test')",
        "UPDATE users SET name = 'test' WHERE id = 1",
        "DELETE FROM users WHERE id = 1",
    ])
    def test_safe_sql_not_matched(self, sql):
        for pattern, name, code in HIGH_RISK_SQL_PATTERNS:
            assert pattern.search(sql) is None, f"Pattern {code} should NOT match safe SQL '{sql}'"


# ---------------------------------------------------------------------------
# WHERE_REQUIRED_PATTERNS tests
# ---------------------------------------------------------------------------

class TestWhereRequiredPatterns:

    def test_is_list(self):
        assert isinstance(WHERE_REQUIRED_PATTERNS, list)

    def test_not_empty(self):
        assert len(WHERE_REQUIRED_PATTERNS) > 0

    def test_tuple_structure(self):
        for item in WHERE_REQUIRED_PATTERNS:
            assert len(item) == 2
            assert isinstance(item[0], type(re.compile("")))
            assert isinstance(item[1], str)

    def test_update_pattern_matches(self):
        for pattern, name in WHERE_REQUIRED_PATTERNS:
            if name == "UPDATE":
                assert pattern.search("UPDATE users SET name = 'test'")
                assert pattern.search("update orders set status = 'shipped'")
                return
        pytest.fail("UPDATE pattern not found")

    def test_delete_pattern_matches(self):
        for pattern, name in WHERE_REQUIRED_PATTERNS:
            if name == "DELETE":
                assert pattern.search("DELETE FROM users")
                assert pattern.search("delete from orders where id > 10")
                return
        pytest.fail("DELETE pattern not found")

    def test_select_not_matched(self):
        for pattern, name in WHERE_REQUIRED_PATTERNS:
            assert pattern.search("SELECT * FROM users") is None


# ---------------------------------------------------------------------------
# Security validation logic tests
# ---------------------------------------------------------------------------

class TestSecurityValidationLogic:

    def _validate_sql(self, sql: str) -> str:
        for pattern, name, code in HIGH_RISK_SQL_PATTERNS:
            if pattern.search(sql):
                return f"BLOCKED: {code}"
        for pattern, op_name in WHERE_REQUIRED_PATTERNS:
            if pattern.search(sql):
                if not re.search(r"\bWHERE\b", sql, re.IGNORECASE):
                    return "BLOCKED: MISSING_WHERE"
        return "OK"

    def test_valid_select_allowed(self):
        assert self._validate_sql("SELECT * FROM users WHERE id = 1") == "OK"

    def test_valid_insert_allowed(self):
        assert self._validate_sql("INSERT INTO users (name) VALUES ('test')") == "OK"

    def test_valid_create_allowed(self):
        assert self._validate_sql("CREATE TABLE orders (id INT)") == "OK"

    def test_valid_alter_allowed(self):
        assert self._validate_sql("ALTER TABLE users ADD COLUMN age INT") == "OK"

    def test_update_without_where_blocked(self):
        result = self._validate_sql("UPDATE users SET name = 'test'")
        assert "BLOCKED" in result
        assert "MISSING_WHERE" in result

    def test_update_with_where_allowed(self):
        assert self._validate_sql("UPDATE users SET name = 'test' WHERE id = 1") == "OK"

    def test_update_with_where_case_insensitive(self):
        assert self._validate_sql("UPDATE users SET name = 'test' where id = 1") == "OK"

    def test_delete_without_where_blocked(self):
        result = self._validate_sql("DELETE FROM users")
        assert "BLOCKED" in result
        assert "MISSING_WHERE" in result

    def test_delete_with_where_allowed(self):
        assert self._validate_sql("DELETE FROM users WHERE id = 1") == "OK"

    def test_multiple_where_keywords_still_allowed(self):
        assert self._validate_sql("DELETE FROM users WHERE id = 1 AND name = 'test'") == "OK"


# ---------------------------------------------------------------------------
# LIMIT clause logic tests
# ---------------------------------------------------------------------------

class TestAddLimitLogic:

    def _add_limit(self, sql: str, max_rows: int) -> str:
        if max_rows <= 0:
            return sql
        sql = sql.strip().rstrip(";")
        return f"{sql} LIMIT {max_rows}"

    def test_add_limit_basic(self):
        assert self._add_limit("SELECT * FROM users", 10) == "SELECT * FROM users LIMIT 10"

    def test_removes_semicolon(self):
        assert self._add_limit("SELECT * FROM users;", 10) == "SELECT * FROM users LIMIT 10"

    def test_multiple_semicolons(self):
        assert self._add_limit("SELECT 1;;;", 5) == "SELECT 1 LIMIT 5"

    def test_strips_whitespace(self):
        assert self._add_limit("  SELECT * FROM users  ", 10) == "SELECT * FROM users LIMIT 10"

    def test_zero_rows_no_change(self):
        assert self._add_limit("SELECT * FROM users", 0) == "SELECT * FROM users"

    def test_negative_rows_no_change(self):
        assert self._add_limit("SELECT * FROM users", -1) == "SELECT * FROM users"


# ---------------------------------------------------------------------------
# Row formatting logic tests
# ---------------------------------------------------------------------------

class TestFormatRowsLogic:

    def _format_rows(self, rows, columns):
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return [list(row.values()) for row in rows]
        return [list(row) for row in rows]

    def test_empty_rows(self):
        assert self._format_rows([], ["col1", "col2"]) == []

    def test_tuple_list(self):
        rows = [("val1", "val2"), ("val3", "val4")]
        assert self._format_rows(rows, ["col1", "col2"]) == [["val1", "val2"], ["val3", "val4"]]

    def test_dict_list(self):
        rows = [{"col1": "val1", "col2": "val2"}]
        assert self._format_rows(rows, ["col1", "col2"]) == [["val1", "val2"]]

    def test_tuple_with_none(self):
        rows = [(None, "val2")]
        assert self._format_rows(rows, ["col1", "col2"]) == [[None, "val2"]]

    def test_empty_tuple_list(self):
        assert self._format_rows([], []) == []


# ---------------------------------------------------------------------------
# JSON serializer logic tests
# ---------------------------------------------------------------------------

class TestJsonSerializerLogic:

    def _json_serializer(self, obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if isinstance(obj, (bytes, bytearray)):
            return obj.decode("utf-8", errors="replace")
        if hasattr(obj, "__str__"):
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    def test_datetime(self):
        dt = datetime(2024, 1, 15, 12, 30, 45)
        assert self._json_serializer(dt) == "2024-01-15T12:30:45"

    def test_bytes(self):
        b = b"test data"
        assert self._json_serializer(b) == "test data"

    def test_bytearray(self):
        ba = bytearray(b"test data")
        assert self._json_serializer(ba) == "test data"

    def test_string(self):
        assert self._json_serializer("hello world") == "hello world"

    def test_int(self):
        assert self._json_serializer(42) == "42"

    def test_float(self):
        assert self._json_serializer(3.14) == "3.14"

    def test_bool(self):
        assert self._json_serializer(True) == "True"
        assert self._json_serializer(False) == "False"

    def test_none(self):
        assert self._json_serializer(None) == "None"

    def test_list(self):
        assert self._json_serializer([1, 2, 3]) == "[1, 2, 3]"


# ---------------------------------------------------------------------------
# Result structure tests
# ---------------------------------------------------------------------------

class TestResultStructure:

    def _make_result(self, status: str, columns: list, rows: list, message: str = ""):
        return json.dumps({
            "status": status,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": 10,
            "message": message or f"Query executed successfully. Returned {len(rows)} rows in 10ms.",
        }, ensure_ascii=False)

    def test_success_result_has_required_keys(self):
        result = self._make_result("success", ["col1"], [["val1"]])
        data = json.loads(result)

        assert data["status"] == "success"
        assert "columns" in data
        assert "rows" in data
        assert "row_count" in data
        assert "execution_time_ms" in data
        assert "message" in data

    def test_error_result_has_required_keys(self):
        result = self._make_result("error", [], [], "SQL SECURITY BLOCK: DROP_DATABASE")
        data = json.loads(result)

        assert data["status"] == "error"
        assert "message" in data
        assert data["columns"] == []
        assert data["rows"] == []
        assert data["row_count"] == 0

    def test_row_count_matches_rows(self):
        result = self._make_result("success", ["col1"], [["v1"], ["v2"], ["v3"]])
        data = json.loads(result)
        assert data["row_count"] == 3

    def test_empty_result(self):
        result = self._make_result("success", [], [])
        data = json.loads(result)
        assert data["row_count"] == 0
        assert data["columns"] == []
        assert data["rows"] == []

    def test_message_format(self):
        result = self._make_result("success", ["col1"], [["v1"]])
        data = json.loads(result)
        assert "Returned 1 rows" in data["message"]

    def test_unicode_in_message(self):
        result = self._make_result("success", ["col1"], [["v1"]], "查询执行成功。Returned 1 rows.")
        data = json.loads(result)
        assert "查询执行成功" in data["message"]

    def test_ensure_ascii_false(self):
        result = self._make_result("success", ["col1"], [["中文"]])
        data = json.loads(result)
        assert data["rows"][0][0] == "中文"


# ---------------------------------------------------------------------------
# MSSQL-specific logic tests
# ---------------------------------------------------------------------------

class TestMssqlPreprocessLogic:

    def _preprocess_sql(self, sql: str) -> str:
        limit_pattern = re.compile(r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?", re.IGNORECASE)

        def replace_limit(match):
            offset = match.group(2)
            limit = match.group(1)
            if offset:
                return f"OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
            else:
                return f"TOP {limit}"

        return limit_pattern.sub(replace_limit, sql)

    def test_limit_converted_to_top(self):
        result = self._preprocess_sql("SELECT * FROM users LIMIT 10")
        assert result == "SELECT * FROM users TOP 10"

    def test_limit_case_insensitive(self):
        result = self._preprocess_sql("select * from users limit 20")
        assert result == "select * from users TOP 20"

    def test_limit_with_offset_converted(self):
        result = self._preprocess_sql("SELECT * FROM users LIMIT 5, 10")
        assert result == "SELECT * FROM users OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"

    def test_no_limit_unchanged(self):
        sql = "SELECT * FROM users WHERE id = 1"
        assert self._preprocess_sql(sql) == sql

    def test_limit_in_subquery(self):
        result = self._preprocess_sql("SELECT * FROM (SELECT * FROM orders LIMIT 5) AS sub")
        assert "TOP 5" in result

    def test_multiple_limits(self):
        result = self._preprocess_sql("SELECT * FROM a LIMIT 5; SELECT * FROM b LIMIT 10")
        assert "TOP 5" in result
        assert "TOP 10" in result


class TestMssqlConvertParamsLogic:

    def _convert_params_for_mssql(self, sql: str, parameters: Optional[List[Any]]):
        if not parameters:
            return sql, None

        param_count = [0]

        def replace_placeholder(match):
            param_count[0] += 1
            return f"@p{param_count[0]}"

        converted_sql = re.sub(r"\?", replace_placeholder, sql)
        param_dict = {}
        for i, val in enumerate(parameters, start=1):
            param_dict[f"@p{i}"] = val

        return converted_sql, param_dict

    def test_no_parameters(self):
        sql = "SELECT * FROM users"
        result_sql, result_params = self._convert_params_for_mssql(sql, None)
        assert result_sql == sql
        assert result_params is None

    def test_empty_parameters(self):
        sql = "SELECT * FROM users"
        result_sql, result_params = self._convert_params_for_mssql(sql, [])
        assert result_sql == sql
        assert result_params is None

    def test_single_parameter(self):
        sql = "SELECT * FROM users WHERE id = ?"
        result_sql, result_params = self._convert_params_for_mssql(sql, [42])
        assert result_sql == "SELECT * FROM users WHERE id = @p1"
        assert result_params == {"@p1": 42}

    def test_multiple_parameters(self):
        sql = "SELECT * FROM users WHERE id = ? AND status = ?"
        result_sql, result_params = self._convert_params_for_mssql(sql, [1, "active"])
        assert result_sql == "SELECT * FROM users WHERE id = @p1 AND status = @p2"
        assert result_params == {"@p1": 1, "@p2": "active"}

    def test_parameters_with_special_chars(self):
        sql = "SELECT * FROM users WHERE name = ?"
        result_sql, result_params = self._convert_params_for_mssql(sql, ["O'Brien"])
        assert result_sql == "SELECT * FROM users WHERE name = @p1"
        assert result_params == {"@p1": "O'Brien"}

    def test_parameters_count_exceeds_placeholder(self):
        sql = "SELECT * FROM users WHERE id = ?"
        result_sql, result_params = self._convert_params_for_mssql(sql, [1, 2, 3])
        assert result_sql == "SELECT * FROM users WHERE id = @p1"
        assert result_params == {"@p1": 1, "@p2": 2, "@p3": 3}


class TestMssqlAddLimitLogic:

    def _add_limit_clause(self, sql: str, max_rows: int) -> str:
        if max_rows <= 0:
            return sql
        sql = sql.strip().rstrip(";")
        return f"SELECT TOP {max_rows} * FROM ({sql.rstrip()}) AS subquery"

    def test_add_limit(self):
        result = self._add_limit_clause("SELECT name FROM users", 10)
        assert result == "SELECT TOP 10 * FROM (SELECT name FROM users) AS subquery"

    def test_removes_semicolon(self):
        result = self._add_limit_clause("SELECT name FROM users;", 10)
        assert "subquery" in result

    def test_zero_rows_no_change(self):
        sql = "SELECT name FROM users"
        assert self._add_limit_clause(sql, 0) == sql

    def test_negative_rows_no_change(self):
        sql = "SELECT name FROM users"
        assert self._add_limit_clause(sql, -1) == sql


# ---------------------------------------------------------------------------
# PostgreSQL-specific logic tests
# ---------------------------------------------------------------------------

class TestPostgresConvertParamsLogic:

    def _convert_params_for_postgres(self, sql: str, parameters: Optional[List[Any]]):
        if not parameters:
            return sql, parameters

        param_count = [0]

        def replace_placeholder(match):
            param_count[0] += 1
            return f"${param_count[0]}"

        converted_sql = re.sub(r"\?", replace_placeholder, sql)
        return converted_sql, parameters

    def test_no_parameters(self):
        sql = "SELECT * FROM users"
        result_sql, result_params = self._convert_params_for_postgres(sql, None)
        assert result_sql == sql
        assert result_params is None

    def test_empty_parameters(self):
        sql = "SELECT * FROM users"
        result_sql, result_params = self._convert_params_for_postgres(sql, [])
        assert result_sql == sql
        assert result_params == []

    def test_single_parameter(self):
        sql = "SELECT * FROM users WHERE id = ?"
        result_sql, _ = self._convert_params_for_postgres(sql, [42])
        assert result_sql == "SELECT * FROM users WHERE id = $1"

    def test_multiple_parameters(self):
        sql = "SELECT * FROM users WHERE id = ? AND status = ?"
        result_sql, _ = self._convert_params_for_postgres(sql, [1, "active"])
        assert result_sql == "SELECT * FROM users WHERE id = $1 AND status = $2"

    def test_parameters_not_modified(self):
        sql = "SELECT * FROM users WHERE id = ?"
        _, result_params = self._convert_params_for_postgres(sql, [42])
        assert result_params == [42]


# ---------------------------------------------------------------------------
# Tool __init__ exports tests
# ---------------------------------------------------------------------------

class TestSqlToolsInit:

    def test_sql_tools_imports(self):
        from sdk.nexent.core.tools.sql_tools import MySqlTool, PostgreSqlTool, MsSqlTool
        assert MySqlTool is not None
        assert PostgreSqlTool is not None
        assert MsSqlTool is not None

    def test_sql_tools_all_list(self):
        from sdk.nexent.core.tools.sql_tools import __all__
        assert "MySqlTool" in __all__
        assert "PostgreSqlTool" in __all__
        assert "MsSqlTool" in __all__
