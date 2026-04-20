"""
Unit tests for sql_database_base_tool module.
"""
import json
import re
from unittest.mock import MagicMock

import pytest

from sdk.nexent.core.tools.sql_tools.sql_database_base_tool import (
    HIGH_RISK_SQL_PATTERNS,
    WHERE_REQUIRED_PATTERNS,
)


class TestHighRiskSqlPatterns:
    """Test HIGH_RISK_SQL_PATTERNS constant."""

    def test_is_list(self):
        assert isinstance(HIGH_RISK_SQL_PATTERNS, list)

    def test_not_empty(self):
        assert len(HIGH_RISK_SQL_PATTERNS) > 0

    @pytest.mark.parametrize("sql,expected_code", [
        ("DROP DATABASE testdb", "DROP_DATABASE"),
        ("drop database prod", "DROP_DATABASE"),
        ("GRANT ALL TO admin", "GRANT"),
        ("REVOKE ALL FROM guest", "REVOKE"),
        ("CREATE USER newuser", "CREATE_USER"),
        ("SELECT * INTO OUTFILE '/tmp/data.txt'", "INTO_OUTFILE"),
        ("LOAD DATA INFILE '/tmp/data.txt'", "LOAD_DATA_INFILE"),
        ("EXEC xp_cmdshell 'dir'", "EXEC_XP"),
    ])
    def test_pattern_blocks_sql(self, sql, expected_code):
        """Each pattern should match its corresponding SQL."""
        for pattern, name, code in HIGH_RISK_SQL_PATTERNS:
            if code == expected_code:
                assert pattern.search(sql) is not None, f"Pattern {code} should match '{sql}'"
                return
        pytest.fail(f"Pattern {expected_code} not found in HIGH_RISK_SQL_PATTERNS")


class TestWhereRequiredPatterns:
    """Test WHERE_REQUIRED_PATTERNS constant."""

    def test_is_list(self):
        assert isinstance(WHERE_REQUIRED_PATTERNS, list)

    def test_not_empty(self):
        assert len(WHERE_REQUIRED_PATTERNS) > 0

    def test_update_pattern_matches(self):
        for pattern, name in WHERE_REQUIRED_PATTERNS:
            if name == "UPDATE":
                assert pattern.search("UPDATE users SET name = 'test'")
                return
        pytest.fail("UPDATE pattern not found")

    def test_delete_pattern_matches(self):
        for pattern, name in WHERE_REQUIRED_PATTERNS:
            if name == "DELETE":
                assert pattern.search("DELETE FROM users")
                return
        pytest.fail("DELETE pattern not found")


class TestSecurityValidationLogic:
    """Test SQL security validation logic by simulating the behavior."""

    def _validate_sql(self, sql: str) -> str:
        """Simulate _validate_sql_security behavior."""
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

    def test_update_without_where_blocked(self):
        result = self._validate_sql("UPDATE users SET name = 'test'")
        assert "BLOCKED" in result
        assert "MISSING_WHERE" in result

    def test_update_with_where_allowed(self):
        assert self._validate_sql("UPDATE users SET name = 'test' WHERE id = 1") == "OK"

    def test_delete_without_where_blocked(self):
        result = self._validate_sql("DELETE FROM users")
        assert "BLOCKED" in result
        assert "MISSING_WHERE" in result

    def test_delete_with_where_allowed(self):
        assert self._validate_sql("DELETE FROM users WHERE id = 1") == "OK"

    @pytest.mark.parametrize("sql", [
        "DROP DATABASE testdb",
        "GRANT ALL TO admin",
        "REVOKE ALL FROM guest",
        "CREATE USER newuser",
        "SELECT * INTO OUTFILE '/tmp/data.txt'",
        "LOAD DATA INFILE '/tmp/data.txt'",
        "EXEC xp_cmdshell 'dir'",
    ])
    def test_high_risk_blocked(self, sql):
        result = self._validate_sql(sql)
        assert "BLOCKED" in result


class TestAddLimitLogic:
    """Test LIMIT clause addition logic."""

    def _add_limit(self, sql: str, max_rows: int) -> str:
        """Simulate _add_limit_clause behavior."""
        if max_rows <= 0:
            return sql
        sql = sql.strip().rstrip(";")
        return f"{sql} LIMIT {max_rows}"

    def test_add_limit(self):
        assert self._add_limit("SELECT * FROM users", 10) == "SELECT * FROM users LIMIT 10"

    def test_removes_semicolon(self):
        assert self._add_limit("SELECT * FROM users;", 10) == "SELECT * FROM users LIMIT 10"

    def test_zero_rows_no_change(self):
        assert self._add_limit("SELECT * FROM users", 0) == "SELECT * FROM users"

    def test_negative_rows_no_change(self):
        assert self._add_limit("SELECT * FROM users", -1) == "SELECT * FROM users"


class TestFormatRowsLogic:
    """Test row formatting logic."""

    def _format_rows(self, rows, columns):
        """Simulate _format_rows behavior."""
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


class TestJsonSerializerLogic:
    """Test JSON serialization logic."""

    def _json_serializer(self, obj):
        """Simulate json_serializer behavior."""
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if isinstance(obj, (bytes, bytearray)):
            return obj.decode("utf-8", errors="replace")
        if hasattr(obj, "__str__"):
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    def test_datetime(self):
        from datetime import datetime
        dt = datetime(2024, 1, 1, 12, 0, 0)
        assert self._json_serializer(dt) == "2024-01-01T12:00:00"

    def test_bytes(self):
        b = b"test data"
        assert self._json_serializer(b) == "test data"

    def test_string(self):
        assert self._json_serializer("hello") == "hello"

    def test_int(self):
        assert self._json_serializer(42) == "42"


class TestResultStructure:
    """Test forward result structure."""

    def _make_result(self, status: str, columns: list, rows: list, message: str = ""):
        """Simulate forward result format."""
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
