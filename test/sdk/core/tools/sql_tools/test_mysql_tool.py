"""
Unit tests for mysql_tool module.
"""
import pytest

from sdk.nexent.core.tools.sql_tools.mysql_tool import MySqlTool


class TestInit:
    """Test MySqlTool initialization."""

    def test_init_with_required_params(self):
        """Test MySqlTool initialization with required parameters."""
        tool = MySqlTool(host="localhost", user="root", password="password", database="testdb")
        assert tool._host == "localhost"
        assert tool._user == "root"
        assert tool._password == "password"
        assert tool._database == "testdb"

    def test_init_with_optional_port(self):
        """Test MySqlTool initialization with custom port."""
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db", port=3307)
        assert tool._port == 3307

    def test_db_type(self):
        """Test db_type property."""
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool.db_type == "mysql"

    def test_tool_name(self):
        """Test tool_name property."""
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool.tool_name == "mysql_database"

    def test_default_port(self):
        """Test default_port property."""
        tool = MySqlTool(host="localhost", user="root", password="pwd", database="db")
        assert tool.default_port == 3306
