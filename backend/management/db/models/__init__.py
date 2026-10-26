# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Register every domain table on the shared SQLAlchemy metadata."""

from management.db.base import (
    PROTOCOL_GRPC,
    PROTOCOL_HTTP_JSON,
    PROTOCOL_JSONRPC,
    SCHEMA,
    SimpleTableBase,
    TableBase,
    _INGROUP_PERMISSION_DOC,
    _MCP_NAME_DOC,
    _PRIMARY_KEY_DOC,
    _PUBLISHER_TENANT_ID_DOC,
    _PUBLISHER_USER_ID_DOC,
    _TENANT_ID_DOC,
)
from management.db.conversation.models import (
    ConversationRecord,
    ConversationMessage,
    ConversationMessageUnit,
    ConversationSourceImage,
    ConversationSourceSearch,
    ConversationShare,
    ConversationShareAsset,
)
from management.db.automation.models import AgentAutomationTask, AgentAutomationRun, AgentAutomationProposal
from management.db.model.models import ModelRecord
from management.db.monitoring.models import ModelMonitoringRecord
from management.db.tool.models import ToolInfo, ToolInstance, OuterApiService, OuterApiTool
from management.db.agent.models import AgentInfo, AgentRelation, AgentVersion, AgentRepository
from management.db.knowledge_base.models import KnowledgeRecord, KnowledgeStorageObject, KnowledgeFileLifecycle
from management.db.configuration.models import TenantConfig
from management.db.memory.models import (
    MemoryUserConfig,
    MemoryRecord,
    MemoryLongTermVersion,
    MemoryRetrievalHit,
    MemoryDreamingAudit,
    MemoryDreamingDecision,
    MemoryDreamingSchedule,
    MemoryProviderConfig,
    MemoryProviderConfigParam,
    MemoryExternalIngestEventLog,
)
from management.db.mcp.models import McpRecord, McpCommunityRecord, McpMarketRecord
from management.db.identity.models import (
    UserTenant,
    PartnerMappingId,
    TenantInvitationCode,
    TenantInvitationRecord,
    TenantGroupInfo,
    TenantGroupUser,
    RolePermission,
    UserTokenInfo,
    UserTokenUsageLog,
    UserOAuthAccount,
    UserCasSession,
)
from management.db.skill.models import SkillRepository, SkillInfo, SkillToolRelation, SkillInstance
from management.db.a2a.models import (
    A2ANacosConfig,
    A2AExternalAgent,
    A2AExternalAgentRelation,
    A2AServerAgent,
    A2ATask,
    A2AMessage,
    A2AArtifact,
)
from management.db.evaluation.models import (
    EvaluationSet,
    EvaluationSetCase,
    Evaluator,
    EvaluationAnnotationSchema,
    EvaluationAnnotation,
)
from management.db.notification.models import Notification, NotificationReceiver
from management.db.tag.models import (
    TagBucket,
    DocumentTagProjection,
    TagBucketResourceType,
    TagDefinition,
    TagValue,
    ResourceTagAssignment,
)

from management.db.evaluation.models import AgentEvaluation, AgentEvaluationCase
