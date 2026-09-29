// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { Form } from 'antd';
import AgentPrompt from '@/app/[locale]/agents/components/agent-prompt';
import DebugConfig from '@/app/[locale]/agents/components/agentInfo/DebugConfig';
import { Thread } from '@/app/[locale]/newchat/assistant-ui/thread';

const h = vi.hoisted(() => ({
  modelList: { models: [] as any[], availableLlmModels: [] as any[], isSuccess: false },
  agentStore: {} as Record<string, any>,
  agentConfigStore: {} as Record<string, any>,
  agentInfo: { agentInfo: null as any },
  auiState: {
    thread: { messages: [], isRunning: false },
    threads: { threadItems: [], mainThreadId: '' },
    message: { content: [], index: 0, metadata: {}, status: { type: 'complete' } },
  },
  chatModelSelectorProps: undefined as any,
  composerProps: undefined as any,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: any) => (opts && typeof opts === 'object' && 'defaultValue' in opts ? opts.defaultValue : key),
    i18n: { language: 'zh', resolvedLanguage: 'zh' },
  }),
}));

vi.mock('@/hooks/model/useModelList', () => ({
  useModelList: () => ({
    models: h.modelList.models,
    llmModels: [],
    availableModels: h.modelList.models.filter((m: any) => m.connect_status === 'available'),
    availableLlmModels: h.modelList.availableLlmModels,
    embeddingModels: [],
    availableEmbeddingModels: [],
    vlmModels: [],
    availableVlmModels: [],
    isSuccess: h.modelList.isSuccess,
    invalidate: vi.fn(),
  }),
}));

vi.mock('@/hooks/model/useInferenceFieldSpecs', () => ({
  useInferenceFieldSpecs: () => ({ data: [], isLoading: false }),
}));

vi.mock('@/stores/agentStore', () => ({
  useAgentStore: (selector: (s: any) => any) => selector(h.agentStore),
}));

vi.mock('@/stores/agentConfigStore', () => {
  const useAgentConfigStore: any = (selector: (s: any) => any) => selector(h.agentConfigStore);
  useAgentConfigStore.getState = () => ({ ...h.agentConfigStore, updateAgentConfig: vi.fn() });
  return { useAgentConfigStore };
});

vi.mock('@/hooks/agent/useAgentInfo', () => ({
  useAgentInfo: () => ({
    agentInfo: h.agentInfo.agentInfo,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock('@/lib/auth', () => ({ canManageModels: () => true }));
vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: () => ({ user: { role: 'admin' } }),
}));
vi.mock('@/components/providers/deploymentProvider', () => ({
  useDeployment: () => ({ isSpeedMode: false }),
}));
vi.mock('@/contexts/nl2AgentFlow', () => ({
  useNl2AgentFlow: () => ({ configFocusRequest: null }),
}));
vi.mock('@/components/ui/tabs', () => ({
  Tabs: (p: any) => p.children,
  TabsList: (p: any) => p.children,
  TabsTrigger: (p: any) => p.children,
  TabsContent: (p: any) => p.children,
}));
vi.mock('@/components/common/ExpandEditModal', () => ({ default: () => null }));
vi.mock('@/components/chat/RuntimeMetadataEditor', () => ({ RuntimeMetadataEditor: () => null }));

vi.mock('@/app/chat/components/chatModelSelector', () => ({
  ChatModelSelector: (props: any) => {
    h.chatModelSelectorProps = props;
    return null;
  },
}));

vi.mock('@/app/[locale]/agents/components/agentInfo/DebugMessageList', () => ({ default: () => null }));
vi.mock('@/app/[locale]/agents/components/agentInfo/DebugOptimizeModal', () => ({ default: () => null }));
vi.mock('@/app/[locale]/agents/components/agentInfo/useCompareStream', () => ({
  useCompareStream: () => ({
    leftMessages: [],
    rightMessages: [],
    isCompareStreaming: false,
    compareStreamingLeft: false,
    compareStreamingRight: false,
    runCompare: vi.fn(),
    stopCompare: vi.fn(),
    resetCompareState: vi.fn(),
  }),
}));

vi.mock('@/services/conversationService', () => ({
  conversationService: { stop: vi.fn(), runAgent: vi.fn(), getDetail: vi.fn(), createShare: vi.fn() },
}));
vi.mock('@/services/configService', () => ({
  configService: { fetchRuntimeFrontendConfig: () => Promise.resolve({}) },
}));
vi.mock('@/app/chat/streaming/chatStreamHandler', () => ({ handleStreamResponse: vi.fn() }));
vi.mock('@/const/chatConfig', () => ({
  MESSAGE_ROLES: { USER: 'user', ASSISTANT: 'assistant', SYSTEM: 'system' },
  chatConfig: {
    filePreviewTypes: { image: 'image', file: 'file' },
    imageExtensions: [],
    documentExtensions: [],
    supportedTextExtensions: [],
    audioExtensions: [],
    videoExtensions: [],
    fileIcons: {},
    messageTypes: {},
  },
}));
vi.mock('@/lib/logger', () => ({ default: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() } }));
vi.mock('@/lib/agentDebugErrorCache', () => ({
  getCachedDebugError: () => undefined,
  cacheDebugError: vi.fn(),
  clearCachedDebugError: vi.fn(),
}));
vi.mock('@/lib/chat/chatAttachmentUtils', () => ({
  cleanupAttachmentUrls: vi.fn(),
  buildMinioFilePayload: vi.fn(),
}));
vi.mock('@/lib/chat/fileIconUtils', () => ({
  getFileExtension: () => '',
  getFileIcon: () => null,
  MAX_FILE_COUNT: 10,
  MAX_FILE_SIZE: 1048576,
}));
vi.mock('@/lib/utils', () => ({
  safeUUID: () => 'test-uuid',
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  safeStringify: (v: any) => JSON.stringify(v),
}));
vi.mock('@/lib/messageDate', () => ({
  formatMessageDate: () => '',
  formatMessageTime: () => '',
  shouldShowDateSeparator: () => false,
}));
vi.mock('@/lib/clipboard', () => ({ copyToClipboard: () => Promise.resolve() }));
vi.mock('@/lib/warningText', () => ({ formatWarningText: (s: string) => s }));
vi.mock('@/lib/chat/agentIconUtils', () => ({ getAgentIcon: () => () => null }));

vi.mock('@/components/ui/button', () => ({ Button: (p: any) => p.children }));
vi.mock('@/components/ui/dialog', () => ({
  Dialog: (p: any) => (p.open ? p.children : null),
  DialogContent: (p: any) => p.children,
  DialogHeader: (p: any) => p.children,
  DialogTitle: (p: any) => p.children,
  DialogDescription: (p: any) => p.children,
  DialogFooter: (p: any) => p.children,
}));

vi.mock('@assistant-ui/react', () => ({
  useAui: () => ({ composer: () => ({ setText: () => {} }) }),
  useAuiState: (selector: any) => selector(h.auiState),
  ThreadPrimitive: {
    Root: (p: any) => p.children,
    Viewport: (p: any) => p.children,
    ViewportFooter: (p: any) => p.children,
    Messages: (p: any) => (typeof p.children === 'function' ? p.children({}) : p.children),
    MessageByIndex: () => null,
    ScrollToBottom: (p: any) => p.children,
  },
  MessagePrimitive: {
    Root: (p: any) => p.children,
    Error: (p: any) => p.children,
    GroupedParts: (p: any) => p.children,
  },
  ActionBarMorePrimitive: { Root: (p: any) => p.children },
  ActionBarPrimitive: { Root: (p: any) => p.children },
  AuiIf: (p: any) => p.children,
  ErrorPrimitive: { Root: (p: any) => p.children, Message: (p: any) => p.children },
  groupPartByType: () => [],
}));

vi.mock('@/app/[locale]/newchat/assistant-ui/composer', () => ({
  Composer: (props: any) => {
    h.composerProps = props;
    return null;
  },
}));

vi.mock('@/app/[locale]/newchat/ui/markdown-text', () => ({ MarkdownText: () => null }));
vi.mock('@/app/[locale]/newchat/ui/reasoning', () => ({
  Reasoning: { Root: () => null, Content: () => null, Text: () => null },
  GroupReasoningTrigger: () => null,
}));
vi.mock('@/app/[locale]/newchat/ui/execution-code-block', () => ({ ExecutionCodeBlock: () => null }));
vi.mock('@/app/[locale]/newchat/ui/subagent', () => ({ SubAgentContainer: () => null }));
vi.mock('@/app/[locale]/newchat/ui/tooltip-icon-button', () => ({ TooltipIconButton: (p: any) => p.children }));
vi.mock('@/app/[locale]/newchat/ui/sources', () => ({ Sources: () => null }));
vi.mock('@/app/[locale]/newchat/ui/sources-panel', () => ({ SourcesPanel: () => null }));
vi.mock('@/app/[locale]/newchat/ui/sources-panel-context', () => ({
  SourcesPanelProvider: (p: any) => p.children,
  useSourcesPanel: () => ({ selection: null, isOpen: false, open: () => {}, toggle: () => {}, close: () => {} }),
}));
vi.mock('@/app/[locale]/newchat/ui/attachment', () => ({
  AssistantMessageAttachments: () => null,
  UserMessageAttachments: () => null,
}));
vi.mock('@/app/[locale]/newchat/ui/directive-text', () => ({ DirectiveText: () => null, SkillDirectiveText: () => null }));
vi.mock('@/app/[locale]/newchat/ui/quote', () => ({ QuoteBlock: () => null }));
vi.mock('@/app/[locale]/newchat/ui/branch-picker', () => ({ BranchPicker: () => null }));
vi.mock('@/app/[locale]/newchat/ui/dot-matrix', () => ({ DotMatrix: () => null }));
vi.mock('@/app/[locale]/newchat/ui/message-timing', () => ({ MessageTiming: () => null }));
vi.mock('@/app/[locale]/newchat/ui/token-usage', () => ({ SingleTurnTokenUsage: () => null }));
vi.mock('@/app/[locale]/newchat/ui/tool-fallback', () => ({ ToolFallback: () => null }));
vi.mock('@/app/[locale]/newchat/ui/tool-recommendations', () => ({ ToolRecommendations: () => null }));
vi.mock('@/app/[locale]/newchat/ui/agent-draft-card', () => ({ AgentDraftCard: () => null }));
vi.mock('@/app/[locale]/newchat/ui/requirement-clarification-card', () => ({ RequirementClarificationCard: () => null }));
vi.mock('@/app/[locale]/newchat/ui/installed-resource-binding-card', () => ({ InstalledResourceBindingCard: () => null }));
vi.mock('@/app/[locale]/newchat/ui/suggested-resource-installation-card', () => ({ SuggestedResourceInstallationCard: () => null }));
vi.mock('@/app/[locale]/newchat/ui/tool-group', () => ({
  ToolGroupContent: (p: any) => p.children,
  ToolGroupRoot: (p: any) => p.children,
  ToolGroupTrigger: () => null,
}));
vi.mock('@/app/[locale]/newchat/adapter/remote-chat-model-adapter', () => ({
  searchSourcesRegistry: new Map(),
  conversationSourcesRegistry: new Map(),
  skillFileUploadsRegistry: new Map(),
}));
vi.mock('@/app/[locale]/newchat/ui/verification-panel', () => ({ VerificationPanel: () => null }));
vi.mock('@/app/[locale]/newchat/ui/authenticated-image', () => ({ AuthenticatedImage: () => null }));
vi.mock('@/app/[locale]/newchat/ui/skill-file-card', () => ({ SkillFileCard: () => null }));
vi.mock('@/features/agentAutomation/components/AutomationProposalMessage', () => ({ default: () => null }));

if (typeof window !== 'undefined') {
  if (!(window as any).matchMedia) {
    (window as any).matchMedia = () => ({
      matches: false,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
  }
  if (!(window as any).ResizeObserver) {
    (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  }
}

const model = (id: number, name: string, connect_status = 'available') => ({
  id, name, displayName: name, type: 'llm', connect_status,
});

const buildEditedAgent = (overrides: Record<string, any> = {}) => ({
  model_ids: [],
  model: '',
  model_names: [],
  duty_prompt: '',
  constraint_prompt: '',
  few_shots_prompt: '',
  ...overrides,
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  h.modelList.models = [];
  h.modelList.availableLlmModels = [];
  h.modelList.isSuccess = false;
  h.agentInfo.agentInfo = null;
  h.chatModelSelectorProps = undefined;
  h.composerProps = undefined;
});

describe(' 模型可用性过滤与主模型回退', () => {
  it('UT-FE-AUTO-A60EF4DAA250E60E  AgentPrompt 过滤失效 model_ids 并同步 model/model_names', async () => {
    h.modelList.availableLlmModels = [model(1, 'Model A'), model(2, 'Model B')];
    h.modelList.models = h.modelList.availableLlmModels;
    h.modelList.isSuccess = true;
    h.agentStore.editedAgent = buildEditedAgent({
      model_ids: [1, 3],
      model: 'Model A',
      model_names: ['Model A', 'Model C'],
    });
    h.agentStore.agentId = 1;
    h.agentStore.defaultLlmConfig = { id: 1, name: 'Model A', displayName: 'Model A' };
    h.agentStore.updateAgentConfig = vi.fn();
    h.agentStore.updateDraft = vi.fn();
    h.agentStore.flushDraft = vi.fn();

    render(React.createElement(Form, null, React.createElement(AgentPrompt)));

    await waitFor(() => {
      expect(h.agentStore.updateAgentConfig).toHaveBeenCalledWith({
        model_ids: [1],
        model: 'Model A',
        model_names: ['Model A'],
      });
    });
    expect(screen.queryByText('Model C')).toBeNull();
  });

  it(' AgentPrompt 空 model_ids 回退 defaultLlmConfig.id', async () => {
    h.modelList.availableLlmModels = [model(1, 'Model A'), model(2, 'Model B')];
    h.modelList.models = h.modelList.availableLlmModels;
    h.modelList.isSuccess = true;
    h.agentStore.editedAgent = buildEditedAgent({ model_ids: [], model: '', model_names: [] });
    h.agentStore.agentId = 1;
    h.agentStore.defaultLlmConfig = { id: 1, name: 'Model A', displayName: 'Model A' };
    h.agentStore.updateAgentConfig = vi.fn();

    render(React.createElement(Form, null, React.createElement(AgentPrompt)));

    expect(h.agentStore.updateAgentConfig).not.toHaveBeenCalled();
  });

  it(' AgentPrompt defaultLlmConfig.id 不可用时 selectedModelIds 为空', async () => {
    h.modelList.availableLlmModels = [model(1, 'Model A'), model(2, 'Model B')];
    h.modelList.models = h.modelList.availableLlmModels;
    h.modelList.isSuccess = true;
    h.agentStore.editedAgent = buildEditedAgent({ model_ids: [], model: '', model_names: [] });
    h.agentStore.agentId = 1;
    h.agentStore.defaultLlmConfig = { id: 999, name: 'Missing', displayName: 'Missing' };
    h.agentStore.updateAgentConfig = vi.fn();

    render(React.createElement(Form, null, React.createElement(AgentPrompt)));

    await waitFor(() => {
      expect(screen.getByText('agent.field.modelPlaceholder')).toBeTruthy();
    });
    expect(screen.queryByText('Model A')).toBeNull();
  });

  it(' DebugConfig 过滤失效 model_ids 并回退 defaultModelId', async () => {
    h.modelList.availableLlmModels = [model(1, 'Model A'), model(2, 'Model B')];
    h.modelList.models = h.modelList.availableLlmModels;
    h.agentConfigStore.editedAgent = { allow_chat_metadata: false, model: '' };
    h.agentInfo.agentInfo = { model_ids: [1, 3] };

    render(React.createElement(DebugConfig, { agentId: 1 }));

    await waitFor(() => {
      expect(h.chatModelSelectorProps).toBeTruthy();
    });
    expect(h.chatModelSelectorProps.modelIds).toEqual([1]);
    expect(h.chatModelSelectorProps.modelNames).toEqual(['Model A']);
    await waitFor(() => {
      expect(h.chatModelSelectorProps.selectedModelId).toBe(1);
    });
  });

  it(' DebugConfig 全部不可用时 selectedModelId 为 null 且不崩溃', async () => {
    h.modelList.availableLlmModels = [model(1, 'Model A'), model(2, 'Model B')];
    h.modelList.models = h.modelList.availableLlmModels;
    h.agentConfigStore.editedAgent = { allow_chat_metadata: false, model: '' };
    h.agentInfo.agentInfo = { model_ids: [3] };

    render(React.createElement(DebugConfig, { agentId: 1 }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText('agent.debug.placeholder')).toBeTruthy();
    });
    expect(h.chatModelSelectorProps).toBeUndefined();
  });

  it(' DebugConfig 当前 selectedModelId 失效时回退到 defaultModelId', async () => {
    h.modelList.availableLlmModels = [model(1, 'Model A'), model(2, 'Model B')];
    h.modelList.models = h.modelList.availableLlmModels;
    h.agentConfigStore.editedAgent = { allow_chat_metadata: false, model: '' };
    h.agentInfo.agentInfo = { model_ids: [2, 3] };

    const view = render(React.createElement(DebugConfig, { agentId: 1 }));
    await waitFor(() => {
      expect(h.chatModelSelectorProps?.selectedModelId).toBe(2);
    });

    h.agentInfo.agentInfo = { model_ids: [1] };
    view.rerender(React.createElement(DebugConfig, { agentId: 1 }));
    await waitFor(() => {
      expect(h.chatModelSelectorProps?.selectedModelId).toBe(1);
    });
  });

  it(' Thread useAgentModels 仅保留 connect_status=available 并回退首个可用模型', async () => {
    h.modelList.models = [model(1, 'Model A'), model(3, 'Model C', 'unavailable')];
    const agent = {
      id: 1,
      name: 'test-agent',
      display_name: 'Test Agent',
      description: '',
      model_ids: [1, 3],
      model_names: ['Model A', 'Model C'],
      example_questions: [],
      greeting_message: '',
      allow_chat_metadata: false,
    };

    render(React.createElement(Thread, { agent: agent as any, chatMode: 'default' as any, onChatModeChange: () => {} }));

    await waitFor(() => {
      expect(h.composerProps).toBeTruthy();
    });
    expect(h.composerProps.models.map((m: any) => m.id)).toEqual(['1']);
    expect(h.composerProps.selectedModelId).toBe('1');
  });

  it(' Thread useAgentModels 全部不可用时返回空列表', async () => {
    h.modelList.models = [model(1, 'Model A', 'unavailable'), model(3, 'Model C', 'unavailable')];
    const agent = {
      id: 1,
      name: 'test-agent',
      display_name: 'Test Agent',
      description: '',
      model_ids: [1, 3],
      model_names: ['Model A', 'Model C'],
      example_questions: [],
      greeting_message: '',
      allow_chat_metadata: false,
    };

    render(React.createElement(Thread, { agent: agent as any, chatMode: 'default' as any, onChatModeChange: () => {} }));

    await waitFor(() => {
      expect(h.composerProps).toBeTruthy();
    });
    expect(h.composerProps.models).toEqual([]);
    expect(h.composerProps.selectedModelId).toBeUndefined();
  });
});
