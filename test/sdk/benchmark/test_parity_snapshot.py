from types import SimpleNamespace

from sdk.benchmark.generic.provenance.parity_snapshot import (
    build_parity_snapshot,
    canonical_tool_schema,
    diff_parity_snapshots,
)


def _item(item_id, item_type, text, priority):
    return SimpleNamespace(
        id=item_id,
        type=item_type,
        content={"text": text},
        source=(f"source:{item_id}",),
        priority=priority,
        required=item_id == "system:header",
        metadata={},
    )


def test_snapshot_records_prompt_context_resource_and_tool_contracts():
    items = [
        _item("system:header", "system", "Basic", 100),
        _item("system:duty", "system", "Duty", 80),
        _item("tool:search", "tool", "Search resource", 50),
    ]
    tool = SimpleNamespace(
        class_name="SearchTool",
        name="search",
        description="Search",
        inputs='{"query": {"type": "string"}}',
        output_type="string",
        params={},
        source="local",
        usage=None,
    )

    snapshot = build_parity_snapshot(
        context_items=items,
        prompt_templates={"final_answer": {"pre_messages": "Finish"}},
        tools=[tool],
        language="en",
        template_version="2",
        template_source="gaia_solver.yaml",
        intentional_empty_resources={"skills": True},
    )

    assert snapshot["prompt"]["component_hashes"]["basic_information_hash"]
    assert snapshot["prompt"]["component_hashes"]["final_answer_contract_hash"]
    header = next(item for item in snapshot["context_items"] if item["id"] == "system:header")
    assert header["required"] is True
    assert snapshot["resources"]["tools"]["count"] == 1
    assert snapshot["resources"]["skills"]["status"] == "intentional_empty"
    assert snapshot["tools"]["ordered_names"] == ["search"]


def test_canonical_tool_schema_excludes_metadata_and_secrets():
    tool = {
        "class_name": "SearchTool",
        "name": "search",
        "description": "Search",
        "inputs": "{}",
        "params": {
            "exa_api_key": "secret-exa",
            "tavily_api_key": "secret-tavily",
            "terminal_password": "secret-password",
        },
        "metadata": {"api_key": "secret"},
    }

    schema = canonical_tool_schema(tool)

    assert "metadata" not in schema
    assert "secret" not in str(schema)
    assert schema["params"] == {
        "exa_api_key": "[REDACTED]",
        "tavily_api_key": "[REDACTED]",
        "terminal_password": "[REDACTED]",
    }


def test_diff_reports_prompt_item_and_tool_failures_separately():
    base = build_parity_snapshot(
        context_items=[_item("system:header", "system", "Basic", 100)],
        prompt_templates={"final_answer": {"pre_messages": "Finish"}},
        tools=[{"class_name": "SearchTool", "name": "search", "description": "A"}],
        language="en",
        template_version="2",
        template_source="config",
    )
    changed = build_parity_snapshot(
        context_items=[
            _item("system:header", "system", "Changed", 99),
            _item("system:extra", "system", "Extra", 1),
        ],
        prompt_templates={"final_answer": {"pre_messages": "Different"}},
        tools=[{"class_name": "SearchTool", "name": "search", "description": "B"}],
        language="zh",
        template_version="3",
        template_source="config",
    )

    diff = diff_parity_snapshots(base, changed)

    assert diff["passed"] is False
    assert "basic_information_hash" in diff["prompt_component_mismatches"]
    assert "system:extra" in diff["unexpected_items"]
    assert "system:header" in diff["priority_mismatches"]
    assert diff["tool_schema_mismatches"] == ["search"]
    assert diff["language_mismatch"] is True


def test_diff_detects_configured_tool_masquerading_as_injected_builtin():
    configured = {
        "class_name": "RunSkillScriptTool",
        "name": "run_skill_script",
        "description": "Execute",
        "inputs": "{}",
        "source": "builtin",
    }
    injected = SimpleNamespace(
        **configured,
        metadata={
            "_benchmark_assembly_origin": "injected_builtin",
            "agent_id": 8,
            "tenant_id": "tenant-a",
            "version_no": 2,
        },
    )
    configured_snapshot = build_parity_snapshot(
        context_items=[],
        prompt_templates={},
        tools=[configured],
        language="en",
        template_version="2",
        template_source="config",
    )
    injected_snapshot = build_parity_snapshot(
        context_items=[],
        prompt_templates={},
        tools=[injected],
        language="en",
        template_version="2",
        template_source="config",
    )

    diff = diff_parity_snapshots(injected_snapshot, configured_snapshot)

    assert diff["tool_assembly_origin_mismatches"] == ["run_skill_script"]
    assert diff["tool_implementation_mismatches"] == ["run_skill_script"]
