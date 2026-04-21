"""
Unit tests for mysql_tool module.
"""
from unittest.mock import MagicMock, patch

import pytest

from sdk.nexent.core.tools.sql_tools.mysql_tool import MySqlTool
from sdk.nexent.core.utils.tools_common_message import ToolCategory, ToolSign


class TestClassAttributes:
    """Test MySqlTool class-level attributes."""

    def test_name(self):
        assert MySqlTool.name == "mysql_database"

    def test_description_type(self):
        assert isinstance(MySqlTool.description, str)
        assert "MySQL" in MySqlTool.description

    def test_description_contains_security_info(self):
        assert "DROP DATABASE" in MySqlTool.description
        assert "WHERE" in MySqlTool.description

    def test_description_zh_type(self):
        assert isinstance(MySqlTool.description_zh, str)
        assert "MySQL" in MySqlTool.description_zh

    def test_inputs_has_sql(self):
        assert "sql" in MySqlTool.inputs
        assert MySqlTool.inputs["sql"]["required"] is True

    def test_inputs_has_parameters(self):
        assert "parameters" in MySqlTool.inputs
        assert MySqlTool.inputs["parameters"]["nullable"] is True

    def test_inputs_has_max_rows(self):
        assert "max_rows" in MySqlTool.inputs
        assert MySqlTool.inputs["max_rows"]["default"] == 100

    def test_inputs_has_timeout(self):
        assert "timeout" in MySqlTool.inputs
        assert MySqlTool.inputs["timeout"]["default"] == 10

    def test_output_type(self):
        assert MySqlTool.output_type == "string"

    def test_category(self):
        assert MySqlTool.category == ToolCategory.DATABASE.value

    def test_tool_sign(self):
        assert MySqlTool.tool_sign == ToolSign.DATABASE_OPERATION.value


class TestInit:
    """Test MySqlTool initialization."""

    def test_init_with_required_params(self):
        tool = MySqlTool(host="localhost", user="root", password="password", database="testdb")
        assert tool._host == "localhost"
        assert tool._user == "root"
        assert tool._password == "password"
        assert tool._database == "testdb"

    def test_init_with_optional_port(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", port=3307)
        assert tool._port == 3307

    def test_init_with_observer(self):
        mock_observer = MagicMock()
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", observer=mock_observer)
        assert tool.observer is mock_observer

    def test_db_type(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool.db_type == "mysql"

    def test_tool_name(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool.tool_name == "mysql_database"

    def test_default_port_property(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool.default_port == 3306

    def test_running_prompts(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool.running_prompt_zh == "正在执行 SQL 查询..."
        assert tool.running_prompt_en == "Executing SQL query..."


class TestAddLimitLogic:
    """Test _add_limit_clause method inherited from base."""

    def test_add_limit(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool._add_limit_clause("SELECT * FROM users", 10) == "SELECT * FROM users LIMIT 10"

    def test_removes_semicolon(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool._add_limit_clause("SELECT * FROM users;", 10) == "SELECT * FROM users LIMIT 10"

    def test_zero_rows_no_change(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool._add_limit_clause("SELECT * FROM users", 0) == "SELECT * FROM users"

    def test_negative_rows_no_change(self):
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool._add_limit_clause("SELECT * FROM users", -1) == "SELECT * FROM users"


class TestExecuteQuery:
    """Test _execute_query method with mocked database.

    The code calls conn.cursor() directly (no context manager), so we set
    mock_conn.cursor.return_value = mock_cursor.
    """

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_execute_query_success(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"col1": "val1", "col2": "val2"}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users", None, 10, 5)

        assert columns == ["col1", "col2"]
        assert rows == [["val1", "val2"]]
        mock_conn.close.assert_called_once()

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_execute_query_with_params(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"id": 1, "name": "Alice"}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users WHERE id = ?", [1], 10, 5)

        assert columns == ["id", "name"]
        assert rows == [[1, "Alice"]]

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_execute_query_max_rows_zero(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"col1": "v1"}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        tool._execute_query("SELECT * FROM users", None, 0, 5)

        assert "LIMIT" not in mock_conn.cursor.return_value.execute.call_args[0][0]

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_execute_query_empty_result(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        rows, columns = tool._execute_query("SELECT * FROM users", None, 10, 5)

        assert columns == []
        assert rows == []

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_execute_query_connects_with_timeout(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        tool._execute_query("SELECT 1", None, 10, 30)

        mock_pymysql.connect.assert_called_once()
        call_kwargs = mock_pymysql.connect.call_args[1]
        assert call_kwargs["connect_timeout"] == 30
        assert call_kwargs["read_timeout"] == 30
        assert call_kwargs["write_timeout"] == 30

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_execute_query_closes_conn_on_exception(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.description = []
        mock_cursor.fetchall.side_effect = Exception("Query error")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        with pytest.raises(Exception):
            tool._execute_query("SELECT * FROM users", None, 10, 5)

        mock_conn.close.assert_called()


class TestForward:
    """Test forward method."""

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_forward_success(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"id": 1, "name": "Alice"}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT * FROM users")

        import json
        data = json.loads(result)
        assert data["status"] == "success"
        assert data["row_count"] == 1

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_forward_with_observer(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "zh"

        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", observer=mock_observer)
        tool.forward("SELECT * FROM users")

        mock_observer.add_message.assert_called_once()

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_forward_security_error(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("DROP DATABASE production")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "SQL SECURITY BLOCK" in data["message"]

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_forward_update_without_where(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("DELETE FROM users")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "MISSING_WHERE" in data["message"]

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_forward_with_parameters(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"id": 1}]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT * FROM users WHERE id = ?", parameters=[42])

        import json
        data = json.loads(result)
        assert data["status"] == "success"

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_forward_with_none_max_rows(self, mock_pymysql):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_pymysql.connect.return_value = mock_conn

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT 1", max_rows=None)

        import json
        data = json.loads(result)
        assert data["status"] == "success"

    @patch("sdk.nexent.core.tools.sql_tools.mysql_tool.pymysql")
    def test_forward_db_exception(self, mock_pymysql):
        mock_pymysql.connect.side_effect = Exception("Access denied")

        mock_observer = MagicMock()
        mock_observer.lang = "en"
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", observer=mock_observer)
        result = tool.forward("SELECT 1")

        import json
        data = json.loads(result)
        assert data["status"] == "error"
        assert "Access denied" in data["message"]
