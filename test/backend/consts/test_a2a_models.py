"""
Unit tests for A2A Pydantic models.

Tests the Pydantic model classes defined in backend/consts/a2a_models.py.
"""
import pytest
from pydantic import ValidationError


class TestA2AMessageContent:
    """Test class for A2AMessageContent model."""

    def test_default_values(self):
        """Test creating model with default values."""
        from backend.consts.a2a_models import A2AMessageContent

        content = A2AMessageContent()
        assert content.type == "text"
        assert content.text is None

    def test_with_text(self):
        """Test creating model with text content."""
        from backend.consts.a2a_models import A2AMessageContent

        content = A2AMessageContent(type="text", text="Hello, world!")
        assert content.type == "text"
        assert content.text == "Hello, world!"

    def test_with_image_type(self):
        """Test creating model with image content."""
        from backend.consts.a2a_models import A2AMessageContent

        content = A2AMessageContent(type="image", text="image_data")
        assert content.type == "image"


class TestA2AMessage:
    """Test class for A2AMessage model."""

    def test_required_fields(self):
        """Test that role and content are required."""
        from backend.consts.a2a_models import A2AMessage, A2AMessageContent

        message = A2AMessage(
            role="user",
            content=A2AMessageContent(type="text", text="test")
        )
        assert message.role == "user"
        assert message.content.type == "text"

    def test_optional_metadata(self):
        """Test optional metadata field."""
        from backend.consts.a2a_models import A2AMessage, A2AMessageContent

        message = A2AMessage(
            role="agent",
            content=A2AMessageContent(type="text", text="response"),
            metadata={"session_id": "123"}
        )
        assert message.metadata == {"session_id": "123"}


class TestA2ATaskStatus:
    """Test class for A2ATaskStatus model."""

    def test_required_state(self):
        """Test required state field."""
        from backend.consts.a2a_models import A2ATaskStatus

        status = A2ATaskStatus(state="working")
        assert status.state == "working"

    def test_optional_message(self):
        """Test optional message field."""
        from backend.consts.a2a_models import A2ATaskStatus, A2AMessage, A2AMessageContent

        status = A2ATaskStatus(
            state="completed",
            message=A2AMessage(
                role="agent",
                content=A2AMessageContent(type="text", text="Done")
            )
        )
        assert status.state == "completed"
        assert status.message.content.text == "Done"

    def test_optional_tokens(self):
        """Test optional tokens field."""
        from backend.consts.a2a_models import A2ATaskStatus

        status = A2ATaskStatus(
            state="completed",
            tokens={"input": 100, "output": 200}
        )
        assert status.tokens == {"input": 100, "output": 200}


class TestA2ATask:
    """Test class for A2ATask model."""

    def test_required_id(self):
        """Test required id field."""
        from backend.consts.a2a_models import A2ATask

        task = A2ATask(id="task-123")
        assert task.id == "task-123"

    def test_optional_status(self):
        """Test optional status field."""
        from backend.consts.a2a_models import A2ATask, A2ATaskStatus

        task = A2ATask(
            id="task-123",
            status=A2ATaskStatus(state="working")
        )
        assert task.id == "task-123"
        assert task.status.state == "working"

    def test_optional_artifacts(self):
        """Test optional artifacts field."""
        from backend.consts.a2a_models import A2ATask

        task = A2ATask(
            id="task-123",
            artifacts=[{"parts": [{"type": "text", "text": "result"}]}]
        )
        assert len(task.artifacts) == 1


class TestA2ATaskEvent:
    """Test class for A2ATaskEvent model."""

    def test_required_fields(self):
        """Test required kind and task_id fields."""
        from backend.consts.a2a_models import A2ATaskEvent

        event = A2ATaskEvent(kind="taskProgress", task_id="task-123")
        assert event.kind == "taskProgress"
        assert event.task_id == "task-123"


class TestA2AAgentProvider:
    """Test class for A2AAgentProvider model."""

    def test_required_organization(self):
        """Test required organization field."""
        from backend.consts.a2a_models import A2AAgentProvider

        provider = A2AAgentProvider(organization="Nexent Corp")
        assert provider.organization == "Nexent Corp"

    def test_optional_url(self):
        """Test optional url field."""
        from backend.consts.a2a_models import A2AAgentProvider

        provider = A2AAgentProvider(
            organization="Nexent Corp",
            url="https://nexent.ai"
        )
        assert provider.url == "https://nexent.ai"


class TestA2AAgentCapabilities:
    """Test class for A2AAgentCapabilities model."""

    def test_default_values(self):
        """Test default capability values."""
        from backend.consts.a2a_models import A2AAgentCapabilities

        caps = A2AAgentCapabilities()
        assert caps.streaming is False
        assert caps.pushNotifications is False
        assert caps.stateTransitionReports is False
        assert caps.artifacts is False
        assert caps.protocolVersion == "1.0"

    def test_streaming_enabled(self):
        """Test enabling streaming capability."""
        from backend.consts.a2a_models import A2AAgentCapabilities

        caps = A2AAgentCapabilities(streaming=True)
        assert caps.streaming is True

    def test_supported_transport_types(self):
        """Test supported transport types."""
        from backend.consts.a2a_models import A2AAgentCapabilities

        caps = A2AAgentCapabilities(
            supportedTransportTypes=["http-streaming", "http-polling"]
        )
        assert "http-streaming" in caps.supportedTransportTypes


class TestA2ASupportedInterface:
    """Test class for A2ASupportedInterface model."""

    def test_required_fields(self):
        """Test required fields."""
        from backend.consts.a2a_models import A2ASupportedInterface

        iface = A2ASupportedInterface(
            protocolBinding="http-json-rpc",
            url="https://example.com/a2a/v1"
        )
        assert iface.protocolBinding == "http-json-rpc"
        assert iface.url == "https://example.com/a2a/v1"

    def test_default_protocol_version(self):
        """Test default protocol version."""
        from backend.consts.a2a_models import A2ASupportedInterface

        iface = A2ASupportedInterface(
            protocolBinding="rest",
            url="https://example.com/a2a"
        )
        assert iface.protocolVersion == "1.0"


class TestA2AAgentSkill:
    """Test class for A2AAgentSkill model."""

    def test_required_fields(self):
        """Test required id and name fields."""
        from backend.consts.a2a_models import A2AAgentSkill

        skill = A2AAgentSkill(id="chat", name="Chat Assistant")
        assert skill.id == "chat"
        assert skill.name == "Chat Assistant"

    def test_optional_fields(self):
        """Test optional fields with defaults."""
        from backend.consts.a2a_models import A2AAgentSkill

        skill = A2AAgentSkill(
            id="code",
            name="Code Assistant",
            description="Helps with coding",
            tags=["development", "programming"],
            examples=["Write a function", "Debug this code"]
        )
        assert skill.description == "Helps with coding"
        assert "development" in skill.tags
        assert len(skill.examples) == 2


class TestA2AAgentCard:
    """Test class for A2AAgentCard model."""

    def test_required_name(self):
        """Test required name field."""
        from backend.consts.a2a_models import A2AAgentCard

        card = A2AAgentCard(name="Test Agent")
        assert card.name == "Test Agent"

    def test_optional_description(self):
        """Test optional description field."""
        from backend.consts.a2a_models import A2AAgentCard

        card = A2AAgentCard(
            name="Test Agent",
            description="A test agent for unit testing"
        )
        assert card.description == "A test agent for unit testing"

    def test_default_capabilities(self):
        """Test that default capabilities are created."""
        from backend.consts.a2a_models import A2AAgentCard

        card = A2AAgentCard(name="Test Agent")
        assert card.capabilities is not None
        assert card.capabilities.protocolVersion == "1.0"

    def test_with_provider(self):
        """Test with provider information."""
        from backend.consts.a2a_models import A2AAgentCard, A2AAgentProvider

        card = A2AAgentCard(
            name="Test Agent",
            provider=A2AAgentProvider(
                organization="Test Corp",
                url="https://test.com"
            )
        )
        assert card.provider.organization == "Test Corp"

    def test_with_skills(self):
        """Test with skills."""
        from backend.consts.a2a_models import A2AAgentCard, A2AAgentSkill

        card = A2AAgentCard(
            name="Test Agent",
            skills=[
                A2AAgentSkill(id="chat", name="Chat"),
                A2AAgentSkill(id="code", name="Code")
            ]
        )
        assert len(card.skills) == 2

    def test_with_supported_interfaces(self):
        """Test with supported interfaces."""
        from backend.consts.a2a_models import (
            A2AAgentCard,
            A2ASupportedInterface
        )

        card = A2AAgentCard(
            name="Test Agent",
            supportedInterfaces=[
                A2ASupportedInterface(
                    protocolBinding="http-json-rpc",
                    url="https://test.com/v1"
                )
            ]
        )
        assert len(card.supportedInterfaces) == 1

    def test_with_endpoints(self):
        """Test legacy url field."""
        from backend.consts.a2a_models import A2AAgentCard

        card = A2AAgentCard(
            name="Test Agent",
            url="https://test.com/a2a"
        )
        assert card.url == "https://test.com/a2a"

    def test_with_security(self):
        """Test security fields."""
        from backend.consts.a2a_models import A2AAgentCard

        card = A2AAgentCard(
            name="Test Agent",
            securitySchemes={"api_key": {"type": "apiKey"}},
            securityRequirements=[{"api_key": []}]
        )
        assert "api_key" in card.securitySchemes


class TestDiscoverFromUrlRequest:
    """Test class for DiscoverFromUrlRequest model."""

    def test_required_url(self):
        """Test required url field."""
        from backend.consts.a2a_models import DiscoverFromUrlRequest

        req = DiscoverFromUrlRequest(url="https://example.com/agent.json")
        assert req.url == "https://example.com/agent.json"

    def test_optional_name(self):
        """Test optional name override."""
        from backend.consts.a2a_models import DiscoverFromUrlRequest

        req = DiscoverFromUrlRequest(
            url="https://example.com/agent.json",
            name="Custom Name"
        )
        assert req.name == "Custom Name"


class TestDiscoverFromNacosRequest:
    """Test class for DiscoverFromNacosRequest model."""

    def test_required_fields(self):
        """Test required nacos_config_id and agent_names."""
        from backend.consts.a2a_models import DiscoverFromNacosRequest

        req = DiscoverFromNacosRequest(
            nacos_config_id="config-1",
            agent_names=["agent-a", "agent-b"]
        )
        assert req.nacos_config_id == "config-1"
        assert len(req.agent_names) == 2

    def test_default_namespace(self):
        """Test default namespace value."""
        from backend.consts.a2a_models import DiscoverFromNacosRequest

        req = DiscoverFromNacosRequest(
            nacos_config_id="config-1",
            agent_names=["agent-a"]
        )
        assert req.namespace == "public"


class TestExternalAgentResponse:
    """Test class for ExternalAgentResponse model."""

    def test_required_fields(self):
        """Test required fields."""
        from backend.consts.a2a_models import ExternalAgentResponse

        resp = ExternalAgentResponse(
            id=1,
            name="External Agent",
            agent_url="https://example.com",
            source_type="url",
            is_available=True
        )
        assert resp.id == 1
        assert resp.name == "External Agent"

    def test_optional_fields(self):
        """Test optional fields with defaults."""
        from backend.consts.a2a_models import ExternalAgentResponse

        resp = ExternalAgentResponse(
            id=1,
            name="External Agent",
            agent_url="https://example.com",
            source_type="url",
            is_available=True
        )
        assert resp.description is None
        assert resp.version is None
        assert resp.streaming is False
        assert resp.supported_interfaces is None


class TestNacosConfigRequest:
    """Test class for NacosConfigRequest model."""

    def test_required_fields(self):
        """Test required fields."""
        from backend.consts.a2a_models import NacosConfigRequest

        req = NacosConfigRequest(
            config_id="nacos-config-1",
            name="Nacos Config",
            nacos_addr="http://nacos:8848"
        )
        assert req.config_id == "nacos-config-1"
        assert req.nacos_addr == "http://nacos:8848"

    def test_optional_credentials(self):
        """Test optional credentials."""
        from backend.consts.a2a_models import NacosConfigRequest

        req = NacosConfigRequest(
            config_id="nacos-config-1",
            name="Nacos Config",
            nacos_addr="http://nacos:8848",
            nacos_username="admin",
            nacos_password="secret"
        )
        assert req.nacos_username == "admin"

    def test_default_namespace(self):
        """Test default namespace."""
        from backend.consts.a2a_models import NacosConfigRequest

        req = NacosConfigRequest(
            config_id="nacos-config-1",
            name="Nacos Config",
            nacos_addr="http://nacos:8848"
        )
        assert req.namespace_id == "public"


class TestA2AServerSettings:
    """Test class for A2AServerSettings model."""

    def test_default_is_enabled(self):
        """Test default is_enabled value."""
        from backend.consts.a2a_models import A2AServerSettings

        settings = A2AServerSettings()
        assert settings.is_enabled is False

    def test_all_fields(self):
        """Test all fields."""
        from backend.consts.a2a_models import (
            A2AServerSettings,
            A2ASupportedInterface
        )

        settings = A2AServerSettings(
            is_enabled=True,
            name="Server Agent",
            description="Agent exposed as A2A server",
            version="1.0.0",
            agent_url="https://example.com/a2a",
            streaming=True,
            supported_interfaces=[
                A2ASupportedInterface(
                    protocolBinding="http-json-rpc",
                    url="https://example.com/a2a/v1"
                )
            ],
            card_overrides={"tags": ["a2a", "server"]}
        )
        assert settings.is_enabled is True
        assert settings.streaming is True
        assert settings.card_overrides == {"tags": ["a2a", "server"]}


class TestCallExternalAgentRequest:
    """Test class for CallExternalAgentRequest model."""

    def test_required_fields(self):
        """Test required agent_id and message."""
        from backend.consts.a2a_models import CallExternalAgentRequest

        req = CallExternalAgentRequest(
            agent_id=1,
            message={"text": "Hello"}
        )
        assert req.agent_id == 1
        assert req.message["text"] == "Hello"

    def test_default_stream(self):
        """Test default stream value."""
        from backend.consts.a2a_models import CallExternalAgentRequest

        req = CallExternalAgentRequest(
            agent_id=1,
            message={"text": "Hello"}
        )
        assert req.stream is False

    def test_optional_protocol_binding(self):
        """Test optional protocol binding."""
        from backend.consts.a2a_models import CallExternalAgentRequest

        req = CallExternalAgentRequest(
            agent_id=1,
            message={"text": "Hello"},
            protocol_binding="http-json-rpc"
        )
        assert req.protocol_binding == "http-json-rpc"


class TestTaskListRequest:
    """Test class for TaskListRequest model."""

    def test_default_values(self):
        """Test default limit and offset values."""
        from backend.consts.a2a_models import TaskListRequest

        req = TaskListRequest()
        assert req.limit == 50
        assert req.offset == 0

    def test_optional_filters(self):
        """Test optional filter fields."""
        from backend.consts.a2a_models import TaskListRequest

        req = TaskListRequest(
            endpoint_id="a2a_endpoint_1",
            status="TASK_STATE_COMPLETED",
            limit=10,
            offset=5
        )
        assert req.endpoint_id == "a2a_endpoint_1"
        assert req.limit == 10

    def test_limit_validation(self):
        """Test limit must be between 1 and 100."""
        from backend.consts.a2a_models import TaskListRequest

        # Valid limit
        req = TaskListRequest(limit=100)
        assert req.limit == 100

        # Invalid limit (too high)
        with pytest.raises(ValidationError):
            TaskListRequest(limit=200)

        # Invalid limit (too low)
        with pytest.raises(ValidationError):
            TaskListRequest(limit=0)

    def test_offset_validation(self):
        """Test offset must be non-negative."""
        from backend.consts.a2a_models import TaskListRequest

        # Valid offset
        req = TaskListRequest(offset=10)
        assert req.offset == 10

        # Invalid offset (negative)
        with pytest.raises(ValidationError):
            TaskListRequest(offset=-1)
