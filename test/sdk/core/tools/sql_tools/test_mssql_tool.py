"""
Unit tests for mssql_tool module.
"""
import pytest

from sdk.nexent.core.tools.sql_tools.mssql_tool import MsSqlTool


class TestInit:
    """Test MsSqlTool initialization."""

    def test_init_with_required_params(self):
        """Test MsSqlTool initialization with required parameters."""
        tool = MsSqlTool(host="localhost", user="sa", password="password", database="testdb")
        assert tool._host == "localhost"
        assert tool._user == "sa"
        assert tool._password == "password"
        assert tool._database == "testdb"

    def test_init_with_optional_port(self):
        """Test MsSqlTool initialization with custom port."""
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db", port=1434)
        assert tool._port == 1434

    def test_db_type(self):
        """Test db_type property."""
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        assert tool.db_type == "mssql"

    def test_tool_name(self):
        """Test tool_name property."""
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        assert tool.tool_name == "mssql_database"

    def test_default_port(self):
        """Test default_port property."""
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        assert tool.default_port == 1433


class TestConvertParamsForMssql:
    """Test _convert_params_for_mssql method."""

    def test_no_params(self):
        """Test _convert_params_for_mssql with no parameters."""
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql("SELECT * FROM users", None)
        assert sql == "SELECT * FROM users"
        assert params is None

    def test_with_params(self):
        """Test _convert_params_for_mssql converts ? to @p1, @p2."""
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql, params = tool._convert_params_for_mssql(
            "SELECT * FROM users WHERE id = ? AND name = ?", [1, "Alice"]
        )
        assert "@p1" in sql
        assert "@p2" in sql
        assert "?" not in sql
        assert params["@p1"] == 1
        assert params["@p2"] == "Alice"


class TestPreprocessSql:
    """Test _preprocess_sql method."""

    def test_converts_limit_to_top(self):
        """Test _preprocess_sql converts LIMIT to TOP for SQL Server."""
        tool = MsSqlTool(host="localhost", user="sa", password="pwd", database="db")
        sql = tool._preprocess_sql("SELECT * FROM users LIMIT 10")
        assert "TOP 10" in sql
