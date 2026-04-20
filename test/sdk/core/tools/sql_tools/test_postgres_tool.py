"""
Unit tests for postgres_tool module.
"""
import pytest

from sdk.nexent.core.tools.sql_tools.postgres_tool import PostgreSqlTool


class TestInit:
    """Test PostgreSqlTool initialization."""

    def test_init_with_required_params(self):
        """Test PostgreSqlTool initialization with required parameters."""
        tool = PostgreSqlTool(host="localhost", user="postgres", password="password", database="testdb")
        assert tool._host == "localhost"
        assert tool._user == "postgres"
        assert tool._password == "password"
        assert tool._database == "testdb"

    def test_init_with_optional_port(self):
        """Test PostgreSqlTool initialization with custom port."""
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db", port=5433)
        assert tool._port == 5433

    def test_db_type(self):
        """Test db_type property."""
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool.db_type == "postgres"

    def test_tool_name(self):
        """Test tool_name property."""
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool.tool_name == "postgres_database"

    def test_default_port(self):
        """Test default_port property."""
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        assert tool.default_port == 5432


class TestConvertParamsForPostgres:
    """Test _convert_params_for_postgres method."""

    def test_no_params(self):
        """Test _convert_params_for_postgres with no parameters."""
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres("SELECT * FROM users", None)
        assert sql == "SELECT * FROM users"
        assert params is None

    def test_with_params(self):
        """Test _convert_params_for_postgres converts ? to $1, $2."""
        tool = PostgreSqlTool(host="localhost", user="postgres", password="pwd", database="db")
        sql, params = tool._convert_params_for_postgres(
            "SELECT * FROM users WHERE id = ? AND name = ?", [1, "Alice"]
        )
        assert "$1" in sql
        assert "$2" in sql
        assert "?" not in sql
        assert params == [1, "Alice"]
