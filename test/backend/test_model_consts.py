import pytest
from pydantic import ValidationError

from backend.consts import model as model_consts


def test_model_connect_status_enum_defaults_and_get_value():
    assert model_consts.ModelConnectStatusEnum.get_default() == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value("") == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value(None) == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value("available") == "available"


def test_model_request_and_validation():
    # Basic construction
    mr = model_consts.ModelRequest(model_name="mymodel", model_type="llm")
    assert mr.model_name == "mymodel"
    assert mr.model_type == "llm"

    # Chunk create request requires non-empty content
    with pytest.raises(ValidationError):
        model_consts.ChunkCreateRequest(content="")

    # Valid chunk create
    req = model_consts.ChunkCreateRequest(content="a", title="t", filename="f")
    assert req.content == "a"
    assert req.title == "t"
    assert req.filename == "f"


def test_conversation_knowledge_scope_validates_three_state_contract():
    scope = model_consts.ConversationKnowledgeScopeRequest.model_validate({
        "local": {"mode": "override", "knowledge_ids": [" 12 ", "12", "13"]},
        "aidp": {"mode": "disabled", "kds_ids": []},
    })

    assert scope.local.knowledge_ids == ["12", "13"]
    assert scope.aidp.mode == "disabled"

    with pytest.raises(ValidationError):
        model_consts.ConversationKnowledgeScopeRequest.model_validate({
            "local": {"mode": "override", "knowledge_ids": []},
        })

    with pytest.raises(ValidationError):
        model_consts.ConversationKnowledgeScopeRequest.model_validate({
            "aidp": {"mode": "inherit", "kds_ids": ["unexpected"]},
        })

    with pytest.raises(ValidationError):
        model_consts.ConversationKnowledgeScopeRequest.model_validate({
            "aidp": {
                "mode": "override",
                "kds_ids": [f"kds-{index}" for index in range(11)],
            },
        })


def test_skill_repository_install_request_limits_target_name_to_100_characters():
    request = model_consts.SkillRepositoryInstallRequest(target_name="x" * 100)
    assert len(request.target_name) == 100

    with pytest.raises(ValidationError):
        model_consts.SkillRepositoryInstallRequest(target_name="x" * 101)


def test_model_request_threads_w11_capacity_and_accept_fields():
    """W11 spec L721-727 + L500-502: ModelRequest must carry every capacity
    column the save handler can persist AND the audit-only accept-signal
    fields shipped by the frontend after a "Use suggestion" save. Pinning the
    field set here prevents a silent rename from dropping a column on the
    DB row or breaking the accept counter.
    """
    fields = set(model_consts.ModelRequest.model_fields.keys())
    required = {
        # W1/W2 capacity columns (persisted)
        "context_window_tokens",
        "max_input_tokens",
        "max_output_tokens",
        "default_output_reserve_tokens",
        "tokenizer_family",
        "capacity_source",
        "capability_profile_version",
        # Canonical provider/model values
        "model_factory",
        "model_name",
        # Accept-signal audit fields (wire-only, stripped by app layer)
        "accepted_suggestion_match_kind",
        "accepted_capability_profile_version",
    }
    missing = required - fields
    assert not missing, f"ModelRequest missing W11 fields: {missing}"


@pytest.mark.parametrize(
    ("request_type", "required_fields"),
    [
        (
            model_consts.ManageTenantModelCreateRequest,
            {"tenant_id", "model_name", "model_type"},
        ),
        (
            model_consts.ManageTenantModelUpdateRequest,
            {"tenant_id", "current_display_name"},
        ),
    ],
)
def test_manage_model_requests_preserve_capacity_fields(request_type, required_fields):
    """Manage create/update must not silently discard capacity fields."""
    capacity_values = {
        "context_window_tokens": 128_000,
        "max_input_tokens": 120_000,
        "max_output_tokens": 8_000,
        "default_output_reserve_tokens": 4_000,
        "tokenizer_family": "cl100k_base",
        "capacity_source": "operator",
        "capability_profile_version": "2026-07-17",
    }
    required_values = {
        "tenant_id": "tenant-1",
        "model_name": "test-model",
        "model_type": "llm",
        "current_display_name": "Test Model",
    }
    request = request_type(
        **{
            field: required_values[field]
            for field in required_fields
        },
        **capacity_values,
    )

    dumped = request.model_dump(exclude_unset=True)
    assert {field: dumped[field] for field in capacity_values} == capacity_values


def test_capacity_suggestion_response_has_required_fields():
    """Pin ModelCapacitySuggestionResponse schema so a downstream rename
    (e.g. suggested_provider -> canonical_provider) trips a test instead
    of silently dropping the field from the API contract.
    """
    fields = set(model_consts.ModelCapacitySuggestionResponse.model_fields.keys())
    required = {
        "suggestions",
        "match_kind",
        "match_confidence",
        "match_explanation",
        "suggested_provider",
        "canonical_model_name",
        "capability_profile_version",
        "capacity_source_on_accept",
    }
    missing = required - fields
    assert not missing, (
        f"ModelCapacitySuggestionResponse missing W11 fields: {missing}"
    )


def test_user_sign_up_request_validation():
    """Test UserSignUpRequest validation rules"""
    # Valid signup request
    req = model_consts.UserSignUpRequest(
        email="test@example.com",
        password="password123",
        invite_code="INVITE123"
    )
    assert req.email == "test@example.com"
    assert req.password == "password123"
    assert req.invite_code == "INVITE123"
    assert req.auto_login is True

    # Invite code is stripped of whitespace
    req = model_consts.UserSignUpRequest(
        email="test@example.com",
        password="password123",
        invite_code="  CODE123  "
    )
    assert req.invite_code == "CODE123"

    # Empty invite code raises
    with pytest.raises(ValidationError):
        model_consts.UserSignUpRequest(
            email="test@example.com",
            password="password123",
            invite_code="   "
        )

    # Password min length validation
    with pytest.raises(ValidationError):
        model_consts.UserSignUpRequest(
            email="test@example.com",
            password="short",
            invite_code="CODE123"
        )


def test_update_password_request():
    """Test UpdatePasswordRequest validation"""
    req = model_consts.UpdatePasswordRequest(
        old_password="oldpass123",
        new_password="newpassword123"
    )
    assert req.old_password == "oldpass123"
    assert req.new_password == "newpassword123"

    # New password too short
    with pytest.raises(ValidationError):
        model_consts.UpdatePasswordRequest(
            old_password="oldpass123",
            new_password="short"
        )


def test_user_update_request():
    """Test UserUpdateRequest validation"""
    # Valid with role
    req = model_consts.UserUpdateRequest(
        username="newname",
        email="new@example.com",
        role="ADMIN"
    )
    assert req.username == "newname"
    assert req.role == "ADMIN"

    # Invalid role pattern
    with pytest.raises(ValidationError):
        model_consts.UserUpdateRequest(role="INVALID_ROLE")

    # Optional fields can be None
    req = model_consts.UserUpdateRequest()
    assert req.username is None
    assert req.role is None


def test_oauth_complete_request():
    """Test OAuthCompleteRequest"""
    req = model_consts.OAuthCompleteRequest(
        password="password123",
        invite_code="CODE123"
    )
    assert req.password == "password123"
    assert req.invite_code == "CODE123"
    assert req.email is None

    # With optional email
    req = model_consts.OAuthCompleteRequest(
        email="user@example.com",
        password="password123",
        invite_code="CODE123"
    )
    assert req.email == "user@example.com"


def test_model_config_hierarchy():
    """Test ModelConfig, AppConfig, and GlobalConfig hierarchy"""
    # Build a complete config
    app_config = model_consts.AppConfig(
        appName="Legacy App",
        appDescription="Legacy description",
        iconType="icon",
        modelEngineEnabled=True
    )
    assert app_config.modelEngineEnabled is True
    assert "appName" not in app_config.model_dump()
    assert "appDescription" not in app_config.model_dump()

    # Single model config
    single_model = model_consts.SingleModelConfig(
        modelName="gpt-4",
        displayName="GPT-4",
        dimension=1536
    )
    assert single_model.modelName == "gpt-4"
    assert single_model.dimension == 1536

    # STT model config
    stt_model = model_consts.STTModelConfig(
        modelName="whisper",
        displayName="Whisper",
        modelFactory="openai",
        modelAppid="app123",
        accessToken="token123"
    )
    assert stt_model.modelAppid == "app123"
    assert stt_model.accessToken == "token123"

    # TTS model config
    tts_model = model_consts.TTSModelConfig(
        modelName="tts-1",
        displayName="TTS-1"
    )
    assert tts_model.modelName == "tts-1"


def test_agent_request_validation():
    """Test AgentRequest model validation"""
    # Basic agent request
    req = model_consts.AgentRequest(
        query="What is AI?"
    )
    assert req.query == "What is AI?"
    assert req.conversation_id is None
    assert req.enable_plan is False
    assert req.enable_automation_tool is True

    # With history
    history = [
        model_consts.HistoryItem(role="user", content="Hello"),
        model_consts.HistoryItem(role="assistant", content="Hi there")
    ]
    req = model_consts.AgentRequest(
        query="Follow up",
        history=history,
        conversation_id=123
    )
    assert len(req.history) == 2
    assert req.conversation_id == 123

    # With minio_files
    req = model_consts.AgentRequest(
        query="Analyze this",
        minio_files=[
            {"filename": "doc.pdf", "path": "/path/to/doc.pdf"}
        ]
    )
    assert len(req.minio_files) == 1

    # With tool_params
    req = model_consts.AgentRequest(
        query="Search",
        tool_params=model_consts.ToolParamsRequest(
            agents={
                "main": model_consts.AgentToolParamsRequest(
                    tools={"search": {"max_results": 10}}
                )
            }
        )
    )
    assert "main" in req.tool_params.agents
    assert req.tool_params.agents["main"].tools["search"]["max_results"] == 10


def test_message_unit_and_message_request():
    """Test MessageUnit and MessageRequest"""
    # MessageUnit
    msg = model_consts.MessageUnit(type="text", content="Hello world")
    assert msg.type == "text"
    assert msg.content == "Hello world"
    assert msg.tool_call_id is None

    msg_with_tool = model_consts.MessageUnit(
        type="tool_call",
        content="Calling search",
        tool_call_id="call_123"
    )
    assert msg_with_tool.tool_call_id == "call_123"

    # MessageRequest
    msg_req = model_consts.MessageRequest(
        conversation_id=1,
        message_idx=5,
        role="user",
        message=[msg]
    )
    assert msg_req.conversation_id == 1
    assert msg_req.message_idx == 5


def test_conversation_request_response():
    """Test ConversationRequest and ConversationResponse"""
    # Default title is Chinese
    req = model_consts.ConversationRequest()
    assert req.title == "新对话"

    # Custom title
    req = model_consts.ConversationRequest(title="My Chat")
    assert req.title == "My Chat"

    # Response
    resp = model_consts.ConversationResponse(
        code=200,
        message="Success",
        data={"id": 123}
    )
    assert resp.code == 200
    assert resp.data["id"] == 123


def test_rename_request():
    """Test RenameRequest"""
    req = model_consts.RenameRequest(
        conversation_id=42,
        name="New Name"
    )
    assert req.conversation_id == 42
    assert req.name == "New Name"


def test_batch_task_request():
    """Test BatchTaskRequest"""
    sources = [
        {"source": "file1.pdf", "source_type": "minio"},
        {"source": "file2.pdf", "source_type": "minio"}
    ]
    req = model_consts.BatchTaskRequest(sources=sources)
    assert len(req.sources) == 2


def test_indexing_response():
    """Test IndexingResponse"""
    resp = model_consts.IndexingResponse(
        success=True,
        message="Indexed successfully",
        total_indexed=100,
        total_submitted=100
    )
    assert resp.success is True
    assert resp.total_indexed == 100


def test_chunk_create_update_requests():
    """Test ChunkCreateRequest and ChunkUpdateRequest"""
    # Create request
    chunk = model_consts.ChunkCreateRequest(
        content="This is chunk content",
        title="Chunk 1",
        filename="doc.pdf",
        path_or_url="/path/to/doc",
        metadata={"source": "manual"}
    )
    assert chunk.content == "This is chunk content"
    assert chunk.metadata["source"] == "manual"

    # Update request
    update = model_consts.ChunkUpdateRequest(
        content="Updated content",
        title="Updated Title"
    )
    assert update.content == "Updated content"
    assert update.title == "Updated Title"


def test_hybrid_search_request():
    """Test HybridSearchRequest validation"""
    # Valid request
    req = model_consts.HybridSearchRequest(
        query="search term",
        index_names=["index1", "index2"],
        top_k=50,
        weight_accurate=0.7
    )
    assert req.query == "search term"
    assert len(req.index_names) == 2
    assert req.top_k == 50
    assert req.weight_accurate == 0.7

    # Empty index_names raises
    with pytest.raises(ValidationError):
        model_consts.HybridSearchRequest(
            query="search",
            index_names=[]
        )

    # top_k out of range
    with pytest.raises(ValidationError):
        model_consts.HybridSearchRequest(
            query="search",
            index_names=["index1"],
            top_k=200
        )

    # weight_accurate out of range
    with pytest.raises(ValidationError):
        model_consts.HybridSearchRequest(
            query="search",
            index_names=["index1"],
            weight_accurate=1.5
        )


def test_convert_state_request():
    """Test ConvertStateRequest"""
    req = model_consts.ConvertStateRequest(
        process_state="SUCCESS",
        forward_state="PENDING"
    )
    assert req.process_state == "SUCCESS"
    assert req.forward_state == "PENDING"

    # Empty values allowed
    req = model_consts.ConvertStateRequest()
    assert req.process_state == ""
    assert req.forward_state == ""


def test_process_params():
    """Test ProcessParams model"""
    params = model_consts.ProcessParams(
        chunking_strategy="basic",
        source_type="minio",
        index_name="test-index",
        authorization="Bearer token123"
    )
    assert params.chunking_strategy == "basic"
    assert params.source_type == "minio"
    assert params.authorization == "Bearer token123"


def test_generate_prompt_request():
    """Test GeneratePromptRequest"""
    req = model_consts.GeneratePromptRequest(
        task_description="Create an agent",
        agent_id=1,
        model_id=2,
        prompt_template_id=3,
        tool_ids=[10, 20],
        sub_agent_ids=[100]
    )
    assert req.task_description == "Create an agent"
    assert req.agent_id == 1
    assert len(req.tool_ids) == 2
    assert req.has_selected_resources is True


def test_optimize_prompt_section_request():
    """Test OptimizePromptSectionRequest"""
    req = model_consts.OptimizePromptSectionRequest(
        task_description="Improve prompt",
        agent_id=1,
        model_id=2,
        section_type="duty",
        section_title="System Prompt",
        current_content="Old content",
        feedback="Add more details",
        mode="insert",
        start_pos=10,
        end_pos=20
    )
    assert req.section_type == "duty"
    assert req.start_pos == 10
    assert req.end_pos == 20


def test_bad_case_and_optimize_requests():
    """Test BadCaseItem and OptimizePromptBadCaseRequest"""
    item = model_consts.BadCaseItem(
        question="What is 2+2?",
        answer="5",
        label="wrong",
        reason="Incorrect answer"
    )
    assert item.label == "wrong"

    req = model_consts.OptimizePromptBadCaseRequest(
        agent_id=1,
        model_id=2,
        current_content="Current prompt",
        bad_cases=[item],
        section_type="duty",
        section_title="Math"
    )
    assert len(req.bad_cases) == 1


def test_generate_title_request():
    """Test GenerateTitleRequest"""
    req = model_consts.GenerateTitleRequest(
        conversation_id=42,
        question="How do I learn Python?"
    )
    assert req.conversation_id == 42
    assert "Python" in req.question


def test_agent_info_request():
    """Test AgentInfoRequest with various fields"""
    req = model_consts.AgentInfoRequest(
        agent_id=1,
        name="test_agent",
        display_name="Test Agent",
        description="A test agent",
        max_steps=10,
        is_main_agent=True,
        enabled=True,
        version_no=1
    )
    assert req.agent_id == 1
    assert req.max_steps == 10
    assert req.is_main_agent is True


def test_tool_instance_requests():
    """Test ToolInstanceInfoRequest and ToolInstanceSearchRequest"""
    tool_inst = model_consts.ToolInstanceInfoRequest(
        tool_id=1,
        agent_id=2,
        params={"max_results": 5},
        enabled=True
    )
    assert tool_inst.tool_id == 1
    assert tool_inst.params["max_results"] == 5

    tool_search = model_consts.ToolInstanceSearchRequest(
        tool_id=1,
        agent_id=2
    )
    assert tool_search.tool_id == 1


def test_skill_instance_info_request():
    """Test SkillInstanceInfoRequest"""
    req = model_consts.SkillInstanceInfoRequest(
        skill_id=1,
        agent_id=2,
        enabled=True,
        config_values={"param1": "value1"}
    )
    assert req.skill_id == 1
    assert req.config_values["param1"] == "value1"


def test_tool_source_enum():
    """Test ToolSourceEnum"""
    assert model_consts.ToolSourceEnum.LOCAL.value == "local"
    assert model_consts.ToolSourceEnum.MCP.value == "mcp"
    assert model_consts.ToolSourceEnum.LANGCHAIN.value == "langchain"
    assert model_consts.ToolSourceEnum.BUILTIN.value == "builtin"


def test_tool_info():
    """Test ToolInfo model"""
    info = model_consts.ToolInfo(
        name="search",
        description="Search the web",
        params=[{"name": "query", "type": "string"}],
        source="local",
        inputs="query: string",
        output_type="text",
        class_name="SearchTool",
        usage="search(query)",
        category="web",
        labels=["search", "web"]
    )
    assert info.name == "search"
    assert info.category == "web"
    assert len(info.labels) == 2


def test_change_summary_request():
    """Test ChangeSummaryRequest"""
    req = model_consts.ChangeSummaryRequest(
        summary_result="The file is about AI"
    )
    assert "AI" in req.summary_result


def test_message_id_request():
    """Test MessageIdRequest"""
    req = model_consts.MessageIdRequest(
        conversation_id=42,
        message_index=5
    )
    assert req.conversation_id == 42
    assert req.message_index == 5


def test_pagination_request():
    """Test PaginationRequest validation"""
    req = model_consts.PaginationRequest(page=1, page_size=20)
    assert req.page == 1
    assert req.page_size == 20

    # Page must be >= 1
    with pytest.raises(ValidationError):
        model_consts.PaginationRequest(page=0)

    # Page_size must be <= 100
    with pytest.raises(ValidationError):
        model_consts.PaginationRequest(page=1, page_size=150)


def test_mcp_source_type_enum():
    """Test MCPSourceType enum"""
    assert model_consts.MCPSourceType.LOCAL.value == "local"
    assert model_consts.MCPSourceType.MCP_REGISTRY.value == "mcp_registry"
    assert model_consts.MCPSourceType.COMMUNITY.value == "community"


def test_add_mcp_service_request():
    """Test AddMcpServiceRequest with strip validators"""
    req = model_consts.AddMcpServiceRequest(
        name="  my-mcp  ",
        server_url="  https://mcp.example.com  ",
        description="  A test MCP  "
    )
    assert req.name == "my-mcp"
    assert req.server_url == "https://mcp.example.com"
    assert req.description == "A test MCP"


def test_update_mcp_service_request():
    """Test UpdateMcpServiceRequest"""
    req = model_consts.UpdateMcpServiceRequest(
        mcp_id=1,
        name="updated-mcp",
        tags=["tag1", "tag2"],
        group_ids="1,2,3"
    )
    assert req.mcp_id == 1
    assert len(req.tags) == 2


def test_community_list_request():
    """Test CommunityListRequest"""
    req = model_consts.CommunityListRequest(
        search="  search term  ",
        tag="  ai  ",
        transport_type="url",
        limit=50
    )
    assert req.search == "search term"
    assert req.tag == "ai"
    assert req.limit == 50


def test_capacity_bare_model():
    """Test CapacityCoverageBareModel"""
    model = model_consts.CapacityCoverageBareModel(
        model_id=1,
        model_name="gpt-4",
        model_type="llm",
        max_tokens=8192,
        suggestion_available=True
    )
    assert model.model_id == 1
    assert model.suggestion_available is True


def test_capacity_coverage_response():
    """Test CapacityCoverageResponse"""
    resp = model_consts.CapacityCoverageResponse(
        total_llm_vlm=10,
        bare_count=3,
        bare_models=[
            model_consts.CapacityCoverageBareModel(
                model_id=1,
                model_name="model1",
                model_type="llm"
            )
        ]
    )
    assert resp.total_llm_vlm == 10
    assert len(resp.bare_models) == 1


def test_memory_agent_share_mode():
    """Test MemoryAgentShareMode enum"""
    assert model_consts.MemoryAgentShareMode.default() == model_consts.MemoryAgentShareMode.NEVER
    assert model_consts.MemoryAgentShareMode.ALWAYS.value == "always"
    assert model_consts.MemoryAgentShareMode.ASK.value == "ask"


def test_tenant_management_requests():
    """Test TenantCreateRequest and TenantUpdateRequest"""
    create_req = model_consts.TenantCreateRequest(
        tenant_name="New Tenant",
        skill_ids=[1, 2, 3],
        locale="zh"
    )
    assert create_req.tenant_name == "New Tenant"
    assert len(create_req.skill_ids) == 3
    assert create_req.locale == "zh"

    update_req = model_consts.TenantUpdateRequest(
        tenant_name="Updated Tenant"
    )
    assert update_req.tenant_name == "Updated Tenant"


def test_group_management_requests():
    """Test GroupCreateRequest, GroupUpdateRequest, GroupListRequest"""
    create_req = model_consts.GroupCreateRequest(
        tenant_id="tenant-1",
        group_name="Admins",
        group_description="Admin group"
    )
    assert create_req.tenant_id == "tenant-1"

    update_req = model_consts.GroupUpdateRequest(
        group_name="Super Admins"
    )
    assert update_req.group_name == "Super Admins"

    list_req = model_consts.GroupListRequest(
        tenant_id="tenant-1",
        page=1,
        page_size=50,
        sort_by="created_at",
        sort_order="asc"
    )
    assert list_req.sort_order == "asc"


def test_user_list_request():
    """Test UserListRequest"""
    req = model_consts.UserListRequest(
        tenant_id="tenant-1",
        page=2,
        page_size=25
    )
    assert req.page == 2
    assert req.page_size == 25


def test_invitation_requests():
    """Test invitation-related request models"""
    create_req = model_consts.InvitationCreateRequest(
        tenant_id="tenant-1",
        code_type="ADMIN_INVITE",
        capacity=5,
        expiry_date="2025-12-31"
    )
    assert create_req.code_type == "ADMIN_INVITE"
    assert create_req.capacity == 5

    update_req = model_consts.InvitationUpdateRequest(
        capacity=10,
        expiry_date="2026-06-30"
    )
    assert update_req.capacity == 10


def test_version_management_requests():
    """Test version management request/response models"""
    publish_req = model_consts.VersionPublishRequest(
        version_name="v1.0.0",
        release_note="Initial release",
    )
    assert publish_req.version_name == "v1.0.0"
    assert publish_req.release_note == "Initial release"

    rollback_req = model_consts.VersionRollbackRequest(
        version_name="Rollback v1",
        release_note="Rolling back"
    )
    assert rollback_req.version_name == "Rollback v1"

    compare_req = model_consts.VersionCompareRequest(
        version_no_a=1,
        version_no_b=2
    )
    assert compare_req.version_no_a == 1


def test_version_list_item_response():
    """Test VersionListItemResponse"""
    resp = model_consts.VersionListItemResponse(
        id=1,
        version_no=1,
        version_name="v1.0",
        status="RELEASED",
        is_a2a=False,
        created_by="admin",
        create_time="2025-01-01"
    )
    assert resp.status == "RELEASED"
    assert resp.created_by == "admin"


def test_current_version_response():
    """Test CurrentVersionResponse"""
    resp = model_consts.CurrentVersionResponse(
        version_no=5,
        version_name="v1.5",
        status="RELEASED",
        source_type="NORMAL",
        created_by="admin"
    )
    assert resp.version_no == 5


def test_skill_management_requests():
    """Test SkillCreateRequest and SkillUpdateRequest"""
    create_req = model_consts.SkillCreateRequest(
        name="my-skill",
        description="A custom skill",
        content="# SKILL\n\nThis is my skill",
        tool_ids=[1, 2],
        tags=["ai", "automation"]
    )
    assert create_req.name == "my-skill"
    assert len(create_req.tool_ids) == 2

    file_data = model_consts.SkillFileData(
        path="scripts/helper.py",
        content="def help(): pass"
    )
    update_req = model_consts.SkillUpdateRequest(
        name="updated-skill",
        files=[file_data]
    )
    assert update_req.name == "updated-skill"
    assert len(update_req.files) == 1


def test_skill_repository_requests():
    """Test skill repository request models"""
    install_req = model_consts.SkillRepositoryInstallRequest(
        target_name="my-installed-skill"
    )
    assert install_req.target_name == "my-installed-skill"

    listing_req = model_consts.SkillRepositoryListingDetailResponse(
        skill_repository_id=1,
        name="shared-skill",
        status="approved",
        tags=["featured"],
        tool_ids=[1, 2]
    )
    assert listing_req.status == "approved"


def test_manage_tenant_model_requests():
    """Test manage tenant model request models"""
    list_req = model_consts.ManageTenantModelListRequest(
        tenant_id="tenant-1",
        model_type="llm",
        page=1,
        page_size=20
    )
    assert list_req.tenant_id == "tenant-1"
    assert list_req.model_type == "llm"

    health_req = model_consts.ManageTenantModelHealthcheckRequest(
        tenant_id="tenant-1",
        display_name="GPT-4",
        model_type="llm"
    )
    assert health_req.tenant_id == "tenant-1"

    delete_req = model_consts.ManageTenantModelDeleteRequest(
        tenant_id="tenant-1",
        display_name="Old Model"
    )
    assert delete_req.display_name == "Old Model"


def test_batch_create_models_request():
    """Test BatchCreateModelsRequest"""
    req = model_consts.BatchCreateModelsRequest(
        api_key="key123",
        models=[{"name": "model1"}, {"name": "model2"}],
        provider="openai",
        type="llm"
    )
    assert len(req.models) == 2


def test_provider_model_requests():
    """Test provider model request models"""
    list_req = model_consts.ManageProviderModelListRequest(
        tenant_id="tenant-1",
        provider="silicon",
        model_type="llm"
    )
    assert list_req.provider == "silicon"

    create_req = model_consts.ManageProviderModelCreateRequest(
        tenant_id="tenant-1",
        provider="openai",
        model_type="llm",
        api_key="key123",
        base_url="https://api.openai.com"
    )
    assert create_req.base_url == "https://api.openai.com"


def test_nl2_agent_skill_requests():
    """Test NL2AgentRunRequest and NL2SkillRunRequest"""
    nl2_agent = model_consts.NL2AgentRunRequest(
        query="Create a chatbot",
        history=[],
        minio_files=[],
        agent_id=42,
    )
    assert nl2_agent.query == "Create a chatbot"
    assert nl2_agent.agent_id == 42

    with pytest.raises(ValidationError):
        model_consts.NL2AgentRunRequest(query="Create a chatbot")

    nl2_skill = model_consts.NL2SkillRunRequest(
        query="Build an automation",
        complexity="simple",
        language="en"
    )
    assert nl2_skill.complexity == "simple"
    assert nl2_skill.language == "en"


def test_export_import_requests():
    """Test export and import request models"""
    agent_info = model_consts.ExportAndImportAgentInfo(
        agent_id=1,
        tenant_id="tenant-1",
        name="exported-agent",
        display_name="Exported Agent",
        description="An exported agent",
        max_steps=10,
        is_main_agent=True,
        provide_run_summary=True,
        enabled=True,
        tools=[],
        managed_agents=[]
    )
    assert agent_info.agent_id == 1

    mcp_info = model_consts.MCPInfo(
        mcp_server_name="test-mcp",
        mcp_url="https://mcp.test.com"
    )
    assert mcp_info.mcp_server_name == "test-mcp"


def test_agent_repository_snapshot():
    """Test AgentRepositorySnapshot"""
    snapshot = model_consts.AgentRepositorySnapshot(
        agent_id=1,
        agent_info={},
        mcp_info=[],
        skills=[
            model_consts.SkillZipEntry(
                skill_name="my-skill",
                skill_zip_base64="base64data=="
            )
        ]
    )
    assert len(snapshot.skills) == 1


def test_repository_import_requests():
    """Test repository import request models"""
    req = model_consts.RepositoryImportPrecheckResponse(
        agent_repository_id=1,
        display_name="Test Repo",
        total_count=5,
        available_count=3,
        percent=60,
        has_abnormal=True,
        items=[
            model_consts.RepositoryImportRequirementItem(
                type="model",
                key="gpt-4",
                name="GPT-4",
                available=True
            )
        ]
    )
    assert req.has_abnormal is True
    assert len(req.items) == 1


def test_agent_name_batch_requests():
    """Test agent name batch request models"""
    batch_regen = model_consts.AgentNameBatchRegenerateRequest(
        items=[
            model_consts.AgentNameBatchRegenerateItem(
                name="old-name",
                display_name="Old Name",
                task_description="Redo the name"
            )
        ]
    )
    assert len(batch_regen.items) == 1

    batch_check = model_consts.AgentNameBatchCheckRequest(
        items=[
            model_consts.AgentNameBatchCheckItem(
                name="check-name",
                agent_id=1
            )
        ]
    )
    assert len(batch_check.items) == 1


def test_nl2_skill_run_with_complexity():
    """Test NL2SkillRunRequest with different complexity modes"""
    req_simple = model_consts.NL2SkillRunRequest(
        query="Simple task",
        complexity="simple"
    )
    assert req_simple.complexity == "simple"

    req_complicated = model_consts.NL2SkillRunRequest(
        query="Complex task",
        complexity="complicated"
    )
    assert req_complicated.complexity == "complicated"


def test_model_api_config():
    """Test ModelApiConfig"""
    config = model_consts.ModelApiConfig(
        apiKey="secret-key",
        modelUrl="https://api.example.com"
    )
    assert config.apiKey == "secret-key"


def test_add_container_mcp_service_request():
    """Test AddContainerMcpServiceRequest"""
    mcp_config = model_consts.MCPConfigRequest(
        mcpServers={
            "server1": model_consts.MCPServerConfig(
                command="npx",
                args=["-y", "server1"],
                port=5020
            )
        }
    )
    req = model_consts.AddContainerMcpServiceRequest(
        name="container-mcp",
        description="A container MCP",
        port=5020,
        mcp_config=mcp_config
    )
    assert req.port == 5020


def test_list_mcp_services_query():
    """Test ListMcpServicesQuery with strip validation"""
    req = model_consts.ListMcpServicesQuery(
        tag="  ai  "
    )
    assert req.tag == "ai"


def test_port_conflict_check_request():
    """Test PortConflictCheckRequest"""
    req = model_consts.PortConflictCheckRequest(
        port=8080
    )
    assert req.port == 8080

    # Invalid port range
    with pytest.raises(ValidationError):
        model_consts.PortConflictCheckRequest(port=0)

    with pytest.raises(ValidationError):
        model_consts.PortConflictCheckRequest(port=70000)


def test_community_review_requests():
    """Test community review request models"""
    review_list = model_consts.CommunityReviewListRequest(
        status="  pending  "
    )
    assert review_list.status == "pending"

    review_action = model_consts.CommunityReviewActionRequest(
        review_id=1,
        content="  Approved  "
    )
    assert review_action.content == "Approved"


def test_group_members_update_request():
    """Test GroupMembersUpdateRequest"""
    req = model_consts.GroupMembersUpdateRequest(
        user_ids=["user1", "user2", "user3"]
    )
    assert len(req.user_ids) == 3


def test_set_default_group_request():
    """Test SetDefaultGroupRequest"""
    req = model_consts.SetDefaultGroupRequest(
        default_group_id=5
    )
    assert req.default_group_id == 5

    # Invalid group_id
    with pytest.raises(ValidationError):
        model_consts.SetDefaultGroupRequest(default_group_id=0)


def test_voice_connectivity_models():
    """Test VoiceConnectivityRequest and VoiceConnectivityResponse"""
    req = model_consts.VoiceConnectivityRequest(
        model_type="stt"
    )
    assert req.model_type == "stt"

    resp = model_consts.VoiceConnectivityResponse(
        connected=True,
        model_type="tts",
        message="Service available"
    )
    assert resp.connected is True


def test_tool_validate_request():
    """Test ToolValidateRequest"""
    req = model_consts.ToolValidateRequest(
        name="search",
        source="local",
        usage="search(query)",
        inputs={"query": {"type": "string"}},
        params={"max_results": 10}
    )
    assert req.name == "search"
    assert req.params["max_results"] == 10


def test_update_knowledge_list_request():
    """Test UpdateKnowledgeListRequest"""
    req = model_consts.UpdateKnowledgeListRequest(
        nexent=["index1", "index2"],
        datamate=["dm-index1"]
    )
    assert len(req.nexent) == 2
    assert req.datamate == ["dm-index1"]


def test_mcp_update_request():
    """Test MCPUpdateRequest"""
    req = model_consts.MCPUpdateRequest(
        current_service_name="old-name",
        current_mcp_url="https://old.example.com",
        new_service_name="new-name",
        new_mcp_url="https://new.example.com",
        new_authorization_token="Bearer new-token"
    )
    assert req.new_service_name == "new-name"


def test_invitation_list_request():
    """Test InvitationListRequest"""
    req = model_consts.InvitationListRequest(
        tenant_id="tenant-1",
        page=2,
        page_size=50
    )
    assert req.page == 2
    assert req.page_size == 50


def test_invitation_response():
    """Test InvitationResponse"""
    resp = model_consts.InvitationResponse(
        invitation_id=1,
        invitation_code="INV123",
        code_type="ADMIN_INVITE",
        group_ids=[1, 2],
        capacity=10,
        status="active",
        created_at="2025-01-01"
    )
    assert resp.status == "active"
    assert len(resp.group_ids) == 2


def test_manage_tenant_model_list_response():
    """Test ManageTenantModelListResponse"""
    resp = model_consts.ManageTenantModelListResponse(
        tenant_id="tenant-1",
        tenant_name="Test Tenant",
        models=[{"name": "model1"}, {"name": "model2"}],
        total=2,
        page=1,
        page_size=20,
        total_pages=1
    )
    assert resp.total == 2
    assert resp.total_pages == 1


def test_agent_repository_listing_requests():
    """Test AgentRepositoryListingCreateRequest"""
    req = model_consts.AgentRepositoryListingCreateRequest(
        icon="🚀",
        downloads=100,
        tags=["ai", "automation"],
        tool_count=10,
        content="This is a great agent"
    )
    assert req.icon == "🚀"
    assert req.downloads == 100


def test_agent_repository_listing_detail_response():
    """Test AgentRepositoryListingDetailResponse"""
    resp = model_consts.AgentRepositoryListingDetailResponse(
        agent_repository_id=1,
        name="great-agent",
        status="approved",
        downloads=500,
        tools=["search", "write"]
    )
    assert resp.downloads == 500
    assert len(resp.tools) == 2


def test_community_publish_update_requests():
    """Test CommunityPublishRequest and CommunityUpdateRequest"""
    publish = model_consts.CommunityPublishRequest(
        mcp_id=1,
        name="new-mcp",
        tags=["featured"]
    )
    assert publish.mcp_id == 1

    update = model_consts.CommunityUpdateRequest(
        market_id=1,
        description="Updated description"
    )
    assert update.description == "Updated description"


def test_community_status_update_request():
    """Test CommunityStatusUpdateRequest"""
    req = model_consts.CommunityStatusUpdateRequest(
        status="shared",
        content="Approved for community"
    )
    assert req.status == "shared"


def test_delete_mcp_service_request():
    """Test DeleteMcpServiceRequest"""
    req = model_consts.DeleteMcpServiceRequest(
        mcp_id=42
    )
    assert req.mcp_id == 42
