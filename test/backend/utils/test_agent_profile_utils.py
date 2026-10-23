"""Unit tests for ``backend.utils.agent_profile_utils``.

Targets
-------
* ``_fetch_agent_tools`` / ``_extract_kb_index_names`` – tool dict
  normalisation, source fallbacks, description truncation, KB index name
  extraction (params as list/dict/None), ``_MAX_TOOLS`` truncation and the
  exception fallback.
* ``_fetch_knowledge_bases`` – empty-index short-circuit (no DB call), KB
  name resolution order (``kb_name`` → ``name_map`` → ``index_name``),
  description truncation and exception fallback.
* ``_fetch_agent_skills`` / ``_fetch_sub_agents`` – empty / filtered /
  truncated results plus exception fallbacks.
* ``fetch_agent_profile`` – ``None`` when agent missing, full assembly and
  missing-field / truncation branches.
* ``_format_list_section`` / ``_format_tool_section`` /
  ``format_agent_profile_context`` – empty / single / multi item rendering.

The pattern mirrors ``test_evaluator_db.py``: sys.path injection, idempotent
``_register_package`` registration and permanent (never-uninstalled)
``sys.modules`` stubs for the module's transitive imports
(``database.agent_db``, ``database.tool_db``, ``management.services.skill.service`` plus
the lazy ``database.knowledge_db`` / ``database.client`` /
``database.db_models`` imports inside ``_fetch_knowledge_bases``).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1. Path setup + idempotent package registration (mirrors
#    test_evaluator_db.py pattern)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

MODULE_UNDER_TEST = "agent_profile_utils"


def _register_package(name: str) -> types.ModuleType:
    """Register ``name`` as a real package on ``sys.modules``.

    See ``test_evaluator_db.py`` – real ``__path__`` (pointing to the
    matching backend dir when one applies) lets ``from X.Y import Z`` resolve
    lazily, while the permanent stub identity stays shared across sibling
    test files.
    """
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    backend_path = _BACKEND_DIR / name
    if backend_path.is_dir():
        pkg.__path__ = [str(backend_path)]
    else:
        pkg.__path__ = []
    sys.modules[name] = pkg
    return pkg


# ---------------------------------------------------------------------------
# 2. Sys.modules stub chain – permanent top-level install (no monkeypatch
#    undo, no dependency on sibling test files)
# ---------------------------------------------------------------------------


def _install_stubs():
    db_pkg = _register_package("database")

    # database.agent_db
    agent_db = types.ModuleType("database.agent_db")
    agent_db.query_sub_agent_relations = MagicMock()
    agent_db.search_agent_info_by_agent_id = MagicMock()
    sys.modules["database.agent_db"] = agent_db
    db_pkg.agent_db = agent_db

    # database.tool_db
    tool_db = types.ModuleType("database.tool_db")
    tool_db.search_tools_for_sub_agent = MagicMock()
    sys.modules["database.tool_db"] = tool_db
    db_pkg.tool_db = tool_db

    # database.knowledge_db (lazy import inside _fetch_knowledge_bases)
    knowledge_db = types.ModuleType("database.knowledge_db")
    knowledge_db.get_knowledge_name_map_by_index_names = MagicMock()
    sys.modules["database.knowledge_db"] = knowledge_db
    db_pkg.knowledge_db = knowledge_db

    # database.client (lazy import inside _fetch_knowledge_bases)
    client = types.ModuleType("database.client")
    client.get_db_session = MagicMock()
    sys.modules["database.client"] = client
    db_pkg.client = client

    # database.db_models – KnowledgeRecord attribute access must not raise
    db_models = types.ModuleType("database.db_models")
    db_models.KnowledgeRecord = MagicMock(name="KnowledgeRecord")
    sys.modules["database.db_models"] = db_models
    db_pkg.db_models = db_models

    # management.services.skill.service – SkillService is a (mock) class
    services_pkg = _register_package("services")
    skill_service = types.ModuleType("management.services.skill.service")
    skill_service.SkillService = MagicMock(name="SkillService")
    sys.modules["management.services.skill.service"] = skill_service
    services_pkg.skill_service = skill_service

    return _StubBundle(agent_db, tool_db, knowledge_db, client, db_models, skill_service)


class _StubBundle:
    """Named accessor for the installed sys.modules stub modules."""

    def __init__(self, agent_db, tool_db, knowledge_db, client, db_models, skill_service):
        self.agent_db = agent_db
        self.tool_db = tool_db
        self.knowledge_db = knowledge_db
        self.client = client
        self.db_models = db_models
        self.skill_service = skill_service


_STUBS = _install_stubs()


@pytest.fixture(scope="module")
def stubs():
    return _STUBS


@pytest.fixture(scope="module")
def profile_mod():
    """Module-scoped fresh import of agent_profile_utils with stubs installed.

    Loaded via ``spec_from_file_location`` so the ``database`` / ``services``
    package ``__init__`` files (SQLAlchemy-heavy) are never executed and the
    ``from database.X import Y`` lines resolve to our stubs.
    """
    import importlib.util as _ilu

    if MODULE_UNDER_TEST in sys.modules:
        del sys.modules[MODULE_UNDER_TEST]

    _src = _BACKEND_DIR / "utils" / "agent_profile_utils.py"
    _spec = _ilu.spec_from_file_location(MODULE_UNDER_TEST, str(_src))
    assert _spec is not None, f"cannot locate agent_profile_utils.py at {_src}"
    assert _spec.loader is not None, f"cannot locate agent_profile_utils.py at {_src}"
    mod = _ilu.module_from_spec(_spec)
    sys.modules[MODULE_UNDER_TEST] = mod
    _spec.loader.exec_module(mod)
    yield mod


@pytest.fixture(autouse=True)
def _reset_stubs(stubs):
    """Reset every stub before each test so return values never leak across tests.

    ``reset_mock(side_effect=True)`` is required: the default ``reset_mock()``
    keeps the previous ``side_effect`` list, and an exhausted side_effect list
    raises ``StopIteration`` on the next call.
    """
    for stub in (
        stubs.agent_db.query_sub_agent_relations,
        stubs.agent_db.search_agent_info_by_agent_id,
        stubs.tool_db.search_tools_for_sub_agent,
        stubs.knowledge_db.get_knowledge_name_map_by_index_names,
        stubs.client.get_db_session,
        stubs.skill_service.SkillService,
    ):
        stub.reset_mock(side_effect=True)
    # ``return_value`` is NOT part of ``_mock_children``, so reset_mock does not
    # reach the instance mock; reset it explicitly to clear leaked side_effects.
    stubs.skill_service.SkillService.return_value.reset_mock(side_effect=True)


# ---------------------------------------------------------------------------
# 3. _fetch_agent_tools / _extract_kb_index_names
# ---------------------------------------------------------------------------


class TestFetchAgentTools:
    def test_no_tools_returns_empty(self, profile_mod, stubs):
        stubs.tool_db.search_tools_for_sub_agent.return_value = []
        assert profile_mod._fetch_agent_tools(1, "t1") == ([], [])

        stubs.tool_db.search_tools_for_sub_agent.return_value = None
        assert profile_mod._fetch_agent_tools(1, "t1") == ([], [])

    def test_collects_tools_and_kb_names(self, profile_mod, stubs):
        stubs.tool_db.search_tools_for_sub_agent.return_value = [
            {"name": "search_knowledge", "description": "kb tool",
             "source": "api", "params": [{"index_names": ["kb1", "kb2"]}]},
            {"name": "weather", "description": "w", "source": "local"},
        ]
        tools, kb_names = profile_mod._fetch_agent_tools(1, "t1")
        assert tools == [
            {"name": "search_knowledge", "description": "kb tool", "source": "api"},
            {"name": "weather", "description": "w", "source": "local"},
        ]
        assert kb_names == ["kb1", "kb2"]

    def test_name_fallback_to_class_name(self, profile_mod, stubs):
        stubs.tool_db.search_tools_for_sub_agent.return_value = [
            {"class_name": "search_knowledge", "params": {"kb_names": ["kbx"]}},
        ]
        tools, kb_names = profile_mod._fetch_agent_tools(1, "t1")
        assert tools[0]["name"] == "search_knowledge"
        assert kb_names == ["kbx"]

    def test_skips_tool_without_name(self, profile_mod, stubs):
        stubs.tool_db.search_tools_for_sub_agent.return_value = [
            {"name": "", "class_name": None},
            {"name": "ok", "description": "d"},
        ]
        tools, _ = profile_mod._fetch_agent_tools(1, "t1")
        assert [t["name"] for t in tools] == ["ok"]

    def test_description_fallback_and_truncation(self, profile_mod, stubs):
        long_desc = "x" * (profile_mod._DESC_TOOL_MAX + 50)
        stubs.tool_db.search_tools_for_sub_agent.return_value = [
            {"name": "a"},                       # no desc -> ""
            {"name": "b", "description_zh": "zh"},  # description_zh fallback
            {"name": "c", "description": long_desc},  # truncated
        ]
        tools, _ = profile_mod._fetch_agent_tools(1, "t1")
        assert tools[0]["description"] == ""
        assert tools[1]["description"] == "zh"
        assert len(tools[2]["description"]) == profile_mod._DESC_TOOL_MAX

    def test_truncates_to_max_tools(self, profile_mod, stubs):
        n = profile_mod._MAX_TOOLS + 5
        stubs.tool_db.search_tools_for_sub_agent.return_value = [
            {"name": f"t{i}", "description": f"d{i}"} for i in range(n)
        ]
        tools, _ = profile_mod._fetch_agent_tools(1, "t1")
        assert len(tools) == profile_mod._MAX_TOOLS

    def test_exception_returns_empty(self, profile_mod, stubs):
        stubs.tool_db.search_tools_for_sub_agent.side_effect = RuntimeError("boom")
        assert profile_mod._fetch_agent_tools(1, "t1") == ([], [])


class TestExtractKbIndexNames:
    @pytest.mark.parametrize(
        "params,expected",
        [
            (None, []),
            ("not-a-struct", []),
            (42, []),
            ({}, []),
            ([], []),
            ({"index_names": ["kb1"]}, ["kb1"]),
            ({"index_names": None, "kb_names": ["kb2"]}, ["kb2"]),
            ({"index_names": ["kb1"], "kb_names": ["ignored"]}, ["kb1"]),
            ([{"index_names": ["kb1"]}, "junk", None, {"kb_names": ["kb2"]}], ["kb1", "kb2"]),
            ([{"index_names": "not-a-list"}], []),
        ],
    )
    def test_extract_kb_index_names(self, profile_mod, params, expected):
        assert profile_mod._extract_kb_index_names({"params": params}) == expected


# ---------------------------------------------------------------------------
# 4. _fetch_knowledge_bases
# ---------------------------------------------------------------------------


class TestFetchKnowledgeBases:
    def test_no_index_names_skips_db(self, profile_mod, stubs):
        assert profile_mod._fetch_knowledge_bases([], "t1") == []
        stubs.knowledge_db.get_knowledge_name_map_by_index_names.assert_not_called()

    def test_builds_kb_list_with_name_fallbacks(self, profile_mod, stubs):
        stubs.knowledge_db.get_knowledge_name_map_by_index_names.return_value = {
            "kb2": "Fallback",
        }
        session = stubs.client.get_db_session.return_value.__enter__.return_value
        session.query.return_value.filter.return_value.all.return_value = [
            ("kb1", "KB One", "desc one"),
            ("kb2", None, None),
            ("kb3", "", ""),
        ]
        result = profile_mod._fetch_knowledge_bases(["kb1", "kb2", "kb3"], "t1")
        assert result == [
            {"name": "KB One", "description": "desc one"},
            {"name": "Fallback", "description": ""},
            {"name": "kb3", "description": ""},
        ]

    def test_description_truncation(self, profile_mod, stubs):
        long_desc = "x" * (profile_mod._DESC_KB_MAX + 10)
        stubs.knowledge_db.get_knowledge_name_map_by_index_names.return_value = {}
        session = stubs.client.get_db_session.return_value.__enter__.return_value
        session.query.return_value.filter.return_value.all.return_value = [
            ("k1", "K", long_desc),
        ]
        result = profile_mod._fetch_knowledge_bases(["k1"], "t1")
        assert len(result[0]["description"]) == profile_mod._DESC_KB_MAX

    def test_exception_returns_empty(self, profile_mod, stubs):
        stubs.knowledge_db.get_knowledge_name_map_by_index_names.side_effect = RuntimeError("boom")
        assert profile_mod._fetch_knowledge_bases(["kb1"], "t1") == []


# ---------------------------------------------------------------------------
# 5. _fetch_agent_skills
# ---------------------------------------------------------------------------


class TestFetchAgentSkills:
    def test_empty_skills_returns_empty(self, profile_mod, stubs):
        stubs.skill_service.SkillService.return_value.get_enabled_skills_for_agent.return_value = []
        assert profile_mod._fetch_agent_skills(1, "t1") == []

    def test_filters_truncates_and_trims_desc(self, profile_mod, stubs):
        skills = [
            {"name": "s1", "description": "d1"},
            {"name": "", "description": "no name"},
            {"name": "s2"},
            {"name": "s3", "description": "x" * (profile_mod._DESC_SKILL_MAX + 10)},
        ] + [{"name": f"s{i}"} for i in range(profile_mod._MAX_SKILLS)]
        stubs.skill_service.SkillService.return_value.get_enabled_skills_for_agent.return_value = skills
        result = profile_mod._fetch_agent_skills(1, "t1")
        # source slices skills[:_MAX_SKILLS] first, then filters empty names:
        # first 20 entries contain one empty-name entry -> 19 kept
        assert len(result) == profile_mod._MAX_SKILLS - 1
        assert result[0] == {"name": "s1", "description": "d1"}
        assert result[1] == {"name": "s2", "description": ""}
        assert len(result[2]["description"]) == profile_mod._DESC_SKILL_MAX

    def test_exception_returns_empty(self, profile_mod, stubs):
        stubs.skill_service.SkillService.return_value.get_enabled_skills_for_agent.side_effect = RuntimeError("boom")
        assert profile_mod._fetch_agent_skills(1, "t1") == []


# ---------------------------------------------------------------------------
# 6. _fetch_sub_agents
# ---------------------------------------------------------------------------


class TestFetchSubAgents:
    def test_empty_relations_returns_empty(self, profile_mod, stubs):
        stubs.agent_db.query_sub_agent_relations.return_value = []
        assert profile_mod._fetch_sub_agents(1, "t1") == []

    def test_builds_sub_agents_skipping_missing(self, profile_mod, stubs):
        stubs.agent_db.query_sub_agent_relations.return_value = [
            {"selected_agent_id": 11},
            {"selected_agent_id": 12},
            {"selected_agent_id": 13},
        ]
        stubs.agent_db.search_agent_info_by_agent_id.side_effect = [
            {"display_name": "Sub1", "description": "d1"},
            {"name": "Sub2", "description": "x" * (profile_mod._DESC_SUB_AGENT_MAX + 10)},
            None,  # sub agent not found -> skipped
        ]
        result = profile_mod._fetch_sub_agents(1, "t1")
        assert [r["name"] for r in result] == ["Sub1", "Sub2"]
        assert result[0]["description"] == "d1"
        assert len(result[1]["description"]) == profile_mod._DESC_SUB_AGENT_MAX

    def test_name_fallback_and_skip_empty_name(self, profile_mod, stubs):
        stubs.agent_db.query_sub_agent_relations.return_value = [
            {"selected_agent_id": 21},
            {"selected_agent_id": 22},
        ]
        stubs.agent_db.search_agent_info_by_agent_id.side_effect = [
            {"display_name": "", "name": "Fallback"},
            {"display_name": "", "name": ""},
        ]
        result = profile_mod._fetch_sub_agents(1, "t1")
        assert [r["name"] for r in result] == ["Fallback"]

    def test_truncates_to_max_sub_agents(self, profile_mod, stubs):
        n = profile_mod._MAX_SUB_AGENTS + 3
        stubs.agent_db.query_sub_agent_relations.return_value = [
            {"selected_agent_id": i} for i in range(n)
        ]
        stubs.agent_db.search_agent_info_by_agent_id.side_effect = [
            {"display_name": f"Sub{i}", "description": ""} for i in range(n)
        ]
        result = profile_mod._fetch_sub_agents(1, "t1")
        assert len(result) == profile_mod._MAX_SUB_AGENTS

    def test_exception_returns_empty(self, profile_mod, stubs):
        stubs.agent_db.query_sub_agent_relations.side_effect = RuntimeError("boom")
        assert profile_mod._fetch_sub_agents(1, "t1") == []


# ---------------------------------------------------------------------------
# 7. fetch_agent_profile
# ---------------------------------------------------------------------------


class TestFetchAgentProfile:
    def test_agent_not_found_returns_none(self, profile_mod, stubs):
        stubs.agent_db.search_agent_info_by_agent_id.return_value = None
        assert profile_mod.fetch_agent_profile(1, "t1") is None

    def test_full_profile_assembly(self, profile_mod, stubs):
        agent = {
            "display_name": "AgentA",
            "description": "desc",
            "duty_prompt": "duty",
            "constraint_prompt": "cons",
            "business_description": "biz",
        }
        stubs.agent_db.search_agent_info_by_agent_id.side_effect = [
            agent, {"display_name": "Sub", "description": "sd"},
        ]
        stubs.tool_db.search_tools_for_sub_agent.return_value = [
            {"name": "weather", "description": "w", "source": "local"},
        ]
        stubs.skill_service.SkillService.return_value.get_enabled_skills_for_agent.return_value = [
            {"name": "s1", "description": "d1"},
        ]
        stubs.agent_db.query_sub_agent_relations.return_value = [
            {"selected_agent_id": 9},
        ]

        profile = profile_mod.fetch_agent_profile(1, "t1")

        assert profile["name"] == "AgentA"
        assert profile["description"] == "desc"
        assert profile["duty_prompt"] == "duty"
        assert profile["constraint_prompt"] == "cons"
        assert profile["business_description"] == "biz"
        assert profile["tools"] == [{"name": "weather", "description": "w", "source": "local"}]
        assert profile["skills"] == [{"name": "s1", "description": "d1"}]
        assert profile["sub_agents"] == [{"name": "Sub", "description": "sd"}]
        assert profile["knowledge_bases"] == []

    def test_missing_fields_and_truncation(self, profile_mod, stubs):
        stubs.agent_db.search_agent_info_by_agent_id.return_value = {
            "name": "OnlyName",
            "description": "d" * (profile_mod._DESC_AGENT_MAX + 10),
            "duty_prompt": "x" * (profile_mod._DUTY_PROMPT_MAX + 10),
        }
        stubs.tool_db.search_tools_for_sub_agent.return_value = []
        stubs.skill_service.SkillService.return_value.get_enabled_skills_for_agent.return_value = []
        stubs.agent_db.query_sub_agent_relations.return_value = []

        profile = profile_mod.fetch_agent_profile(1, "t1")

        assert profile["name"] == "OnlyName"
        assert len(profile["description"]) == profile_mod._DESC_AGENT_MAX
        assert len(profile["duty_prompt"]) == profile_mod._DUTY_PROMPT_MAX
        assert profile["constraint_prompt"] == ""
        assert profile["business_description"] == ""
        assert profile["tools"] == []
        assert profile["skills"] == []
        assert profile["sub_agents"] == []
        assert profile["knowledge_bases"] == []

    def test_wires_kb_index_names_into_kb_fetch(self, profile_mod, stubs):
        stubs.agent_db.search_agent_info_by_agent_id.return_value = {"name": "A"}
        stubs.tool_db.search_tools_for_sub_agent.return_value = [
            {"name": "search_knowledge", "params": [{"index_names": ["kb1"]}]},
        ]
        stubs.skill_service.SkillService.return_value.get_enabled_skills_for_agent.return_value = []
        stubs.agent_db.query_sub_agent_relations.return_value = []
        stubs.knowledge_db.get_knowledge_name_map_by_index_names.return_value = {}
        session = stubs.client.get_db_session.return_value.__enter__.return_value
        session.query.return_value.filter.return_value.all.return_value = [
            ("kb1", "KB", "d"),
        ]

        profile = profile_mod.fetch_agent_profile(1, "t1")

        assert profile["knowledge_bases"] == [{"name": "KB", "description": "d"}]
        stubs.knowledge_db.get_knowledge_name_map_by_index_names.assert_called_once_with(
            ["kb1"], "t1"
        )


# ---------------------------------------------------------------------------
# 8. Formatting helpers
# ---------------------------------------------------------------------------


class TestFormatListSection:
    @pytest.mark.parametrize(
        "items,label,expected",
        [
            ([], "Skills", ""),
            ([{"name": "a"}], "Skills", "Skills: a"),
            ([{"name": "a", "description": "d"}], "Skills", "Skills: a (d)"),
            (
                [{"name": "a", "description": "d"}, {"name": "b"}],
                "Skills",
                "Skills: a (d); b",
            ),
        ],
    )
    def test_format_list_section(self, profile_mod, items, label, expected):
        assert profile_mod._format_list_section(items, label) == expected


class TestFormatToolSection:
    @pytest.mark.parametrize(
        "tools,expected",
        [
            ([], ""),
            ([{"name": "t"}], "Tools: t"),
            ([{"name": "t", "description": "d"}], "Tools: t: d"),
            ([{"name": "t", "source": "local"}], "Tools: t"),
            ([{"name": "t", "source": "api"}], "Tools: t [API]"),
            ([{"name": "t", "source": "custom"}], "Tools: t [CUSTOM]"),
            (
                [{"name": "t1", "source": "api", "description": "d1"},
                 {"name": "t2", "source": "local"}],
                "Tools: t1 [API]: d1; t2",
            ),
        ],
    )
    def test_format_tool_section(self, profile_mod, tools, expected):
        assert profile_mod._format_tool_section(tools) == expected


class TestFormatAgentProfileContext:
    @pytest.mark.parametrize("profile", [None, {}])
    def test_empty_profile_returns_empty(self, profile_mod, profile):
        assert profile_mod.format_agent_profile_context(profile) == ""

    def test_full_profile_rendering(self, profile_mod):
        profile = {
            "name": "AgentA",
            "description": "desc",
            "duty_prompt": "duty",
            "constraint_prompt": "cons",
            "business_description": "biz",
            "tools": [{"name": "t1", "source": "api", "description": "d1"}],
            "skills": [{"name": "s1", "description": "sd"}],
            "sub_agents": [{"name": "sub1"}],
            "knowledge_bases": [{"name": "kb1", "description": "kbd"}],
        }
        expected = "\n".join([
            "## Agent Configuration",
            "### Agent: AgentA",
            "Description: desc",
            "Duty: duty",
            "Constraints: cons",
            "Business Context: biz",
            "Tools: t1 [API]: d1",
            "Skills: s1 (sd)",
            "Sub-agents: sub1",
            "Knowledge Bases: kb1 (kbd)",
        ])
        assert profile_mod.format_agent_profile_context(profile) == expected

    def test_partial_profile_omits_empty_lines(self, profile_mod):
        profile = {
            "name": "A",
            "description": "",
            "duty_prompt": "",
            "constraint_prompt": "c",
            "business_description": "",
            "tools": [],
            "skills": [{"name": "s"}],
            "sub_agents": [],
        }
        expected = "\n".join([
            "## Agent Configuration",
            "### Agent: A",
            "Constraints: c",
            "Skills: s",
        ])
        assert profile_mod.format_agent_profile_context(profile) == expected
