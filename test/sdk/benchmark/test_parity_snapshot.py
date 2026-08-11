from types import SimpleNamespace

from sdk.benchmark.generic.provenance.parity_snapshot import (
    build_agent_run_info_parity_snapshot,
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
    assert snapshot["snapshot_schema_version"] == 2


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
    runtime_scope = injected_snapshot["tools"]["schemas"][0]["implementation"]["runtime_scope"]
    assert "tenant_id" not in runtime_scope
    assert runtime_scope["tenant_fingerprint"]


def test_agent_run_info_snapshot_captures_runtime_surfaces_without_secrets():
    model = SimpleNamespace(
        cite_name="main",
        model_name="model-a",
        url="https://user:password@example.invalid?api_key=secret-url",
        api_key="secret-api-key",
        temperature=0.2,
        top_p=0.9,
        ssl_verify=True,
        model_factory="openai",
        extra_body={"nested_api_key": "secret-extra", "thinking": False},
    )
    context_config = SimpleNamespace(
        policy_layers={"platform": {"processing_mode": "adaptive_compact"}},
        token_threshold=1000,
        context_window_tokens=32000,
        soft_input_budget_tokens=8000,
        hard_input_budget_tokens=12000,
        keep_recent_steps=4,
    )
    agent_config = SimpleNamespace(
        model_name="main",
        context_items=[_item("system:header", "system", "Basic", 100)],
        prompt_templates={},
        tools=[],
        context_manager_config=context_config,
        enable_planning=True,
        provide_run_summary=False,
        verification_config={"enabled": True},
        max_steps=12,
        requested_output_tokens=2048,
        capacity_snapshot={"context_window_tokens": 32000},
        safe_input_budget_snapshot={"safe_input_tokens": 12000},
    )
    run_info = SimpleNamespace(
        agent_config=agent_config,
        model_config_list=[model],
        history=[],
        mcp_host=[],
        sandbox_config=None,
        run_time="frozen",
        capacity_snapshot=agent_config.capacity_snapshot,
        safe_input_budget_snapshot=agent_config.safe_input_budget_snapshot,
        query="private query",
        user_id="private user",
    )

    snapshot = build_agent_run_info_parity_snapshot(
        run_info,
        language="en",
        template_version="2",
        template_source="production",
    )

    serialized = str(snapshot)
    assert snapshot["model"]["endpoint_configured"] is True
    assert snapshot["model"]["extra_body"]["nested_api_key"] == "[REDACTED]"
    assert snapshot["capacity"]["model_capacity"]["context_window_tokens"] == 32000
    assert snapshot["policy"]["effective_processing_mode"] == "adaptive_compact"
    assert snapshot["runtime_flags"]["enable_planning"] is True
    assert "secret-api-key" not in serialized
    assert "secret-url" not in serialized
    assert "private query" not in serialized
    assert "private user" not in serialized


def test_diff_enforces_declared_runtime_surfaces():
    base = build_parity_snapshot(
        context_items=[],
        prompt_templates={},
        tools=[],
        language="en",
        template_version="2",
        template_source="config",
        model={"model_name": "a"},
    )
    changed = {**base, "model": {"model_name": "b"}}

    diff = diff_parity_snapshots(base, changed)

    assert diff["passed"] is False
    assert diff["runtime_surface_mismatches"] == ["model"]
