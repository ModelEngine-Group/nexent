"""
Unit tests for mssql_tool module.
"""
from unittest.mock import MagicMock, patch

import pytest

from sdk.nexent.core.tools.sql_tools.mssql_tool import MsSqlTool
from sdk.nexent.core.utils.tools_common_message import ToolCategory, ToolSign


class TestClassAttributes:
    """Test MsSqlTool class-level attributes."""

    def test_name(self):
        assert MsSqlTool.name == "mssql_database"

    def test_description_type(self):
        assert isinstance(MsSqlTool.description, str)
        assert "SQL Server" in MsSqlTool.description

    def test_description_contains_security_info(self):
        assert "DROP DATABASE" in MsSqlTool.description
        assert "WHERE" in MsSqlTool.description

    def test_description_zh_type(self):
        assert isinstance(MsSqlTool.description_zh, str)
        assert "Microsoft SQL Server" in MsSqlTool.description_zh

    def test_inputs_has_sql(self):
        assert "sql" in MsSqlTool.inputs
        assert MsSqlTool.inputs["sql"]["required"] is True

    def test_inputs_has_parameters(self):
        assert "parameters" in MsSqlTool.inputs
        assert MsSqlTool.inputs["parameters"]["nullable"] is True

    def test_inputs_has_max_rows(self):
        assert "max_rows" in MsSqlTool.inputs
        assert MsSqlTool.inputs["max_rows"]["default"] == 100

    def test_inputs_has_timeout(self):
        assert "timeout" in MsSqlTool.inputs
        assert MsSqlTool.inputs["timeout"]["default"] == 10

    def test_output_type(self):
        assert MsSqlTool.output_type == "string"

    def test_category(self):
        assert MsSqlTool.category == ToolCategory.DATABASE.value

    def test_tool_sign(self):
        assert MsSqlTool.tool_sign == ToolSign.DATABASE_OPERATION.value


class TestInit:
    """Test MsSqlTool initialization."""

    def test_init_with_required_params(self):
        tool = MsSqlTool(host="localhost", user="sa", password="password", database="testdb")
        assert tool._host == "localhost"
        assert tool._user == "sa"
        assert tool._password == "password"
        assert tool._database == "testdb"

    def test_init_with_optional_port(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", port=1434)
        assert tool._port == 1434

    def test_init_with_observer(self):
        mock_observer = MagicMock()
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", observer=mock_observer)
        assert tool.observer is mock_observer

    def test_db_type(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        assert tool.db_type == "mssql"

    def test_tool_name(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        assert tool.tool_name == "mssql_database"

    def test_default_port_property(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        assert tool.default_port == 1433

    def test_running_prompts(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        assert tool.running_prompt_zh == "正在执行 SQL 查询..."
        assert tool.running_prompt_en == "Executing SQL query..."


class TestPreprocessSql:
    """Test _preprocess_sql method."""

    def test_converts_limit_to_top(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql = tool._preprocess_sql("SELECT * FROM users LIMIT 10")
        assert sql == "SELECT * FROM users TOP 10"

    def test_limit_case_insensitive(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql = tool._preprocess_sql("select * from users limit 20")
        assert sql == "select * from users TOP 20"

    def test_no_limit_unchanged(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql = tool._preprocess_sql("SELECT * FROM users WHERE id = 1")
        assert sql == "SELECT * FROM users WHERE id = 1"

    def test_limit_in_subquery(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql = tool._preprocess_sql("SELECT * FROM (SELECT * FROM orders LIMIT 5) AS sub")
        assert "TOP 5" in sql

    def test_multiple_limits(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql = tool._preprocess_sql("SELECT * FROM a LIMIT 5; SELECT * FROM b LIMIT 10")
        assert sql.count("TOP") == 2


class TestConvertParamsForMssql:
    """Test _convert_params_for_mssql method."""

    def test_no_params_none(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql("SELECT * FROM users", None)
        assert sql == "SELECT * FROM users"
        assert params is None

    def test_empty_params(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql("SELECT * FROM users", [])
        assert sql == "SELECT * FROM users"
        assert params is None

    def test_single_param(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql("SELECT * FROM users WHERE id = ?", [42])
        assert sql == "SELECT * FROM users WHERE id = @p1"
        assert params == {"@p1": 42}

    def test_multiple_params(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql(
            "SELECT * FROM users WHERE id = ? AND status = ?", [1, "active"]
        )
        assert "@p1" in sql
        assert "@p2" in sql
        assert "?" not in sql
        assert params["@p1"] == 1
        assert params["@p2"] == "active"

    def test_params_with_special_chars(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql("SELECT * FROM users WHERE name = ?", ["O'Brien"])
        assert "@p1" in sql
        assert params["@p1"] == "O'Brien"

    def test_params_more_placeholders_than_values(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql("SELECT * FROM users WHERE id = ?", [1, 2, 3])
        assert "@p1" in sql
        assert params == {"@p1": 1, "@p2": 2, "@p3": 3}

    def test_no_placeholder(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql("SELECT * FROM users", [1])
        assert "?" not in sql
        assert params == {"@p1": 1}


class TestAddLimitClause:
    """Test _add_limit_clause method."""

    def test_add_limit_basic(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        result = tool._add_limit_clause("SELECT name FROM users", 10)
        assert "TOP 10" in result
        assert "subquery" in result

    def test_removes_semicolon(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        result = tool._add_limit_clause("SELECT name FROM users;", 10)
        assert "subquery" in result

    def test_zero_rows_no_change(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql = "SELECT name FROM users"
        assert tool._add_limit_clause(sql, 0) == sql

    def test_negative_rows_no_change(self):
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql = "SELECT name FROM users"
        assert tool._add_limit_clause(sql, -1) == sql


class TestExecuteQuery:
    """Test _execute_query method with mocked database.

    The code calls conn.cursor() directly (no context manager), so we set
    mock_conn.cursor.return_value = mock_cursor.
    """

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_execute_query_success(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = [{"col1": "val1", "col2": "val2"}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users", None, 10, 5)

        assert columns == ["col1", "col2"]
        assert rows == [["val1", "val2"]]
        mock_conn.close.assert_called_once()

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_execute_query_with_params(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = [{"id": 1, "name": "Alice"}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users WHERE id = @p1", {"@p1": 1}, 10, 5)

        assert columns == ["id", "name"]
        assert rows == [[1, "Alice"]]
        mock_cursor.execute.assert_called_once()

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_execute_query_max_rows_zero(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"col1": "v1"}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users", None, 0, 5)

        mock_cursor.fetchall.assert_called_once()
        mock_cursor.fetchmany.assert_not_called()
        assert columns == ["col1"]
        assert rows == [["v1"]]

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_execute_query_empty_result(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users", None, 10, 5)

        assert columns == []
        assert rows == []

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_execute_query_connects_with_timeout(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        tool._execute_query("SELECT 1", None, 10, 30)

        mock_pymssql.connect.assert_called_once()
        call_kwargs = mock_pymssql.connect.call_args[1]
        assert call_kwargs["login_timeout"] == 30
        assert call_kwargs["timeout"] == 30

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_execute_query_closes_conn_on_exception(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("DB error")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        with pytest.raises(Exception):
            tool._execute_query("SELECT * FROM users", None, 10, 5)

        mock_conn.close.assert_called()


class TestForward:
    """Test forward method."""

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_forward_success(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = [{"id": 1, "name": "Alice"}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT * FROM users")

        import json
        data = json.loads(result)
        assert data["status"] == "success"
        assert data["row_count"] == 1

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_forward_with_observer(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"

        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", observer=mock_observer)
        tool.forward("SELECT * FROM users")

        mock_observer.add_message.assert_called_once()

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_forward_security_error(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("DROP DATABASE production")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "SQL SECURITY BLOCK" in data["message"]

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_forward_update_without_where(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("UPDATE users SET name = 'test'")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "MISSING_WHERE" in data["message"]

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_forward_with_parameters(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = [{"id": 1}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT * FROM users WHERE id = @p1", parameters=[42])

        import json
        data = json.loads(result)
        assert data["status"] == "success"

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_forward_with_none_max_rows(self, mock_pymssql):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymssql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT 1", max_rows=None)

        import json
        data = json.loads(result)
        assert data["status"] == "success"

    @patch("sdk.nexent.core.tools.sql_tools.mssql_tool.pymssql")
    def test_forward_db_exception(self, mock_pymssql):
        mock_pymssql.connect.side_effect = Exception("Connection refused")

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT 1")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "Connection refused" in data["message"]
