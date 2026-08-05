import yaml

from sdk.benchmark.generic.tools.export_agent_config import export_agent_config


class _FakeCursor:
    def __init__(self):
        self.last_query = ""
        self.fetchone_calls = 0

    def execute(self, query, params=None):
        self.last_query = query

    def fetchone(self):
        self.fetchone_calls += 1
        if self.fetchone_calls == 1:
            return (8, "GAIA Agent", 1, "tenant_id")
        return (
            8,
            "gaia_agent",
            "GAIA Agent",
            "Description",
            "Duty",
            "Constraint",
            "",
            15,
            True,
            False,
            {},
            "Hello",
            [],
            0,
            1,
        )

    def fetchall(self):
        if "FROM ag_tool_instance_t" in self.last_query:
            return [
                (
                    "exa_search",
                    "ExaSearchTool",
                    "local",
                    "search",
                    "Search",
                    "{}",
                    "string",
                    {
                        "exa_api_key": "secret-exa-value",
                        "max_results": 3,
                    },
                    True,
                ),
                (
                    "terminal",
                    "TerminalTool",
                    "local",
                    "terminal",
                    "Terminal",
                    "{}",
                    "string",
                    {
                        "password": "secret-terminal-value",
                        "ssh_host": "localhost",
                    },
                    True,
                ),
            ]
        return []

    def close(self):
        pass


class _FakeConnection:
    def __init__(self):
        self.cursor_instance = _FakeCursor()

    def cursor(self):
        return self.cursor_instance

    def rollback(self):
        pass

    def close(self):
        pass


def test_export_agent_config_externalizes_tool_secrets(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(
        "sdk.benchmark.generic.tools.export_agent_config.get_db_connection",
        _FakeConnection,
    )
    output_path = tmp_path / "agent.yaml"

    export_agent_config(agent_id=8, output_path=str(output_path))

    raw_output = output_path.read_text(encoding="utf-8")
    config = yaml.safe_load(raw_output)
    exa_params = config["tools"][0]["tool_params"]
    terminal_params = config["tools"][1]["tool_params"]
    console_output = capsys.readouterr().out

    assert exa_params == {
        "exa_api_key": {"$env": "EXA_API_KEY"},
        "max_results": 3,
    }
    assert terminal_params == {
        "password": {"$env": "TERMINAL_PASSWORD"},
        "ssh_host": "localhost",
    }
    assert "EXA_API_KEY" in console_output
    assert "TERMINAL_PASSWORD" in console_output
    assert "secret-exa-value" not in raw_output
    assert "secret-terminal-value" not in raw_output
    assert "secret-exa-value" not in console_output
    assert "secret-terminal-value" not in console_output
