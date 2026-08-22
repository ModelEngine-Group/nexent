"""
Unit tests for postgres_tool module.
"""
from unittest.mock import MagicMock, patch

import pytest

from sdk.nexent.core.tools.sql_tools.postgres_tool import PostgreSqlTool
from sdk.nexent.core.utils.tools_common_message import ToolCategory, ToolSign


class TestClassAttributes:
    """Test PostgreSqlTool class-level attributes."""

    def test_name(self):
        assert PostgreSqlTool.name == "postgres_database"

    def test_description_type(self):
        assert isinstance(PostgreSqlTool.description, str)
        assert "PostgreSQL" in PostgreSqlTool.description

    def test_description_contains_security_info(self):
        assert "DROP DATABASE" in PostgreSqlTool.description
        assert "WHERE" in PostgreSqlTool.description

    def test_description_zh_type(self):
        assert isinstance(PostgreSqlTool.description_zh, str)
        assert "PostgreSQL" in PostgreSqlTool.description_zh

    def test_inputs_has_sql(self):
        assert "sql" in PostgreSqlTool.inputs
        assert PostgreSqlTool.inputs["sql"]["required"] is True

    def test_inputs_has_parameters(self):
        assert "parameters" in PostgreSqlTool.inputs
        assert PostgreSqlTool.inputs["parameters"]["nullable"] is True

    def test_inputs_has_max_rows(self):
        assert "max_rows" in PostgreSqlTool.inputs
        assert PostgreSqlTool.inputs["max_rows"]["default"] == 100

    def test_inputs_has_timeout(self):
        assert "timeout" in PostgreSqlTool.inputs
        assert PostgreSqlTool.inputs["timeout"]["default"] == 10

    def test_output_type(self):
        assert PostgreSqlTool.output_type == "string"

    def test_category(self):
        assert PostgreSqlTool.category == ToolCategory.DATABASE.value

    def test_tool_sign(self):
        assert PostgreSqlTool.tool_sign == ToolSign.DATABASE_OPERATION.value


class TestInit:
    """Test PostgreSqlTool initialization."""

    def test_init_with_required_params(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="password", database="testdb")
        assert tool._host == "localhost"
        assert tool._user == "postgres"
        assert tool._password == "password"
        assert tool._database == "testdb"

    def test_init_with_optional_port(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", port=5433)
        assert tool._port == 5433

    def test_init_with_observer(self):
        mock_observer = MagicMock()
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", observer=mock_observer)
        assert tool.observer is mock_observer

    def test_db_type(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool.db_type == "postgres"

    def test_tool_name(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool.tool_name == "postgres_database"

    def test_default_port_property(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool.default_port == 5432

    def test_running_prompts(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool.running_prompt_zh == "正在执行 SQL 查询..."
        assert tool.running_prompt_en == "Executing SQL query..."


class TestConvertParamsForPostgres:
    """Test _convert_params_for_postgres method."""

    def test_no_params_none(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres("SELECT * FROM users", None)
        assert sql == "SELECT * FROM users"
        assert params is None

    def test_empty_params(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres("SELECT * FROM users", [])
        assert sql == "SELECT * FROM users"

    def test_single_param(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres("SELECT * FROM users WHERE id = ?", [42])
        assert sql == "SELECT * FROM users WHERE id = $1"
        assert params == [42]

    def test_multiple_params(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres(
            "SELECT * FROM users WHERE id = ? AND status = ?", [1, "active"]
        )
        assert "$1" in sql
        assert "$2" in sql
        assert "?" not in sql
        assert params == [1, "active"]

    def test_params_with_special_chars(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres(
            "SELECT * FROM users WHERE name = ?", ["O'Brien"]
        )
        assert "$1" in sql
        assert params == ["O'Brien"]

    def test_no_placeholder(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres("SELECT * FROM users", [1])
        assert "?" not in sql
        assert params == [1]

    def test_params_not_modified(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres("SELECT * FROM users WHERE id = ?", [42])
        assert params == [42]


class TestAddLimitLogic:
    """Test _add_limit_clause method inherited from base."""

    def test_add_limit(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool._add_limit_clause("SELECT * FROM users", 10) == "SELECT * FROM users LIMIT 10"

    def test_removes_semicolon(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool._add_limit_clause("SELECT * FROM users;", 10) == "SELECT * FROM users LIMIT 10"

    def test_zero_rows_no_change(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool._add_limit_clause("SELECT * FROM users", 0) == "SELECT * FROM users"

    def test_negative_rows_no_change(self):
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool._add_limit_clause("SELECT * FROM users", -1) == "SELECT * FROM users"


class TestExecuteQuery:
    """Test _execute_query method with mocked database."""

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_execute_query_success(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("val1", "val2")]
        mock_cursor.description = [("col1",), ("col2",)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users", None, 10, 5)

        assert columns == ["col1", "col2"]
        assert rows == [["val1", "val2"]]
        mock_conn.close.assert_called_once()

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_execute_query_with_params(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "Alice")]
        mock_cursor.description = [("id",), ("name",)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users WHERE id = ?", [1], 10, 5)

        assert columns == ["id", "name"]
        assert rows == [[1, "Alice"]]

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_execute_query_max_rows_zero(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("v1",)]
        mock_cursor.description = [("col1",)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users", None, 0, 5)

        assert "LIMIT" not in mock_conn.cursor.return_value.execute.call_args[0][0]
        assert columns == ["col1"]
        assert rows == [["v1"]]

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_execute_query_empty_result(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users", None, 10, 5)

        assert columns == []
        assert rows == []

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_execute_query_connects_with_timeout(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        tool._execute_query("SELECT 1", None, 10, 30)

        mock_psycopg2.connect.assert_called_once()
        call_kwargs = mock_psycopg2.connect.call_args[1]
        assert call_kwargs["connect_timeout"] == 30
        assert "statement_timeout=30000" in call_kwargs["options"]

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_execute_query_closes_conn_on_exception(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.description = []
        mock_cursor.execute.side_effect = Exception("Query error")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        with pytest.raises(Exception):
            tool._execute_query("SELECT * FROM users", None, 10, 5)

        mock_conn.close.assert_called()


class TestForward:
    """Test forward method."""

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_forward_success(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "Alice")]
        mock_cursor.description = [("id",), ("name",)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT * FROM users")

        import json
        data = json.loads(result)
        assert data["status"] == "success"

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_forward_with_observer(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "zh"

        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", observer=mock_observer)
        tool.forward("SELECT * FROM users")

        mock_observer.add_message.assert_called_once()

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_forward_security_error(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("DROP DATABASE production")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "SQL SECURITY BLOCK" in data["message"]

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_forward_update_without_where(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("UPDATE users SET name = 'test'")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "MISSING_WHERE" in data["message"]

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_forward_with_parameters(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1,)]
        mock_cursor.description = [("id",)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT * FROM users WHERE id = ?", parameters=[42])

        import json
        data = json.loads(result)
        assert data["status"] == "success"

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_forward_with_none_max_rows(self, mock_psycopg2):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT 1", max_rows=None)

        import json
        data = json.loads(result)
        assert data["status"] == "success"

    @patch("sdk.nexent.core.tools.sql_tools.postgres_tool.psycopg2")
    def test_forward_db_exception(self, mock_psycopg2):
        mock_psycopg2.connect.side_effect = Exception("Connection refused")

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT 1")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "Connection refused" in data["message"]
