"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FC,
  type ReactElement,
  type ReactNode,
} from "react";
import type { CompleteAttachment } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import { MarkdownText } from "../ui/markdown-text";
import { Reasoning, GroupReasoningTrigger } from "../ui/reasoning";
import { SubAgentContainer } from "../ui/subagent";
import { TooltipIconButton } from "../ui/tooltip-icon-button";
import { Composer, type ChatMode } from "./composer";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ActionBarMorePrimitive,
  ActionBarPrimitive,
  AuiIf,
  ErrorPrimitive,
  groupPartByType,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import { Sources } from "../ui/sources";
import { SourcesPanel, type PanelSourceItem } from "../ui/sources-panel";
import {
  SourcesPanelProvider,
  useSourcesPanel,
  type SourcesPanelSelection,
} from "../ui/sources-panel-context";
import {
  ArrowDownIcon,
  CheckIcon,
  CopyIcon,
  DownloadIcon,
  FileTextIcon,
  ImageIcon,
  MoreHorizontalIcon,
  RefreshCwIcon,
  ArrowLeft,
  SparklesIcon,
  type LucideIcon,
  PencilIcon,
  Share2Icon,
  XCircleIcon,
  XIcon,
} from "lucide-react";
import { message } from "antd";
import type { Agent, PublishedAgent } from "@/types/agentConfig";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import type { ModelOption } from "../ui/model-selector";
import AutomationProposalMessage from "@/features/agentAutomation/components/AutomationProposalMessage";
import type { AgentAutomationProposalData } from "@/types/agentAutomation";
import {
  AssistantMessageAttachments,
  UserMessageAttachments,
} from "../ui/attachment";
import { DirectiveText, SkillDirectiveText } from "../ui/directive-text";
import { QuoteBlock } from "../ui/quote";
import { BranchPicker } from "../ui/branch-picker";
import { DotMatrix } from "../ui/dot-matrix";
import { MessageTiming } from "../ui/message-timing";
import { SingleTurnTokenUsage } from "../ui/token-usage";
import { ToolFallback } from "../ui/tool-fallback";
import { ToolRecommendations } from "../ui/tool-recommendations";
import { AgentDraftCard } from "../ui/agent-draft-card";
import { RequirementClarificationCard } from "../ui/requirement-clarification-card";
import { InstalledResourceBindingCard } from "../ui/installed-resource-binding-card";
import { SuggestedResourceInstallationCard } from "../ui/suggested-resource-installation-card";
import {
  ToolGroupContent,
  ToolGroupRoot,
  ToolGroupTrigger,
} from "../ui/tool-group";
import {
  searchSourcesRegistry,
  conversationSourcesRegistry,
  skillFileUploadsRegistry,
  type Nl2aMessage,
  type Nl2SkillFileCardData,
  type VerificationContent,
} from "../adapter/remote-chat-model-adapter";
import {
  formatMessageDate,
  formatMessageTime,
  shouldShowDateSeparator,
} from "@/lib/messageDate";
import { VerificationPanel } from "../ui/verification-panel";
import { cn } from "@/lib/utils";
import { AuthenticatedImage } from "../ui/authenticated-image";
import { copyToClipboard } from "@/lib/clipboard";
import { configService } from "@/services/configService";
import { conversationService } from "@/services/conversationService";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";
import { SkillFileCard } from "../ui/skill-file-card";
import type { SkillFileContent } from "@/types/skill";

export interface WelcomeSuggestion {
  id: string;
  title: string;
  description: string;
  prompt: string;
  icon: LucideIcon;
}

export interface ThreadProps {
  agent: Agent | PublishedAgent;
  generatedTitle?: string;
  welcomeTitle?: string;
  welcomeSuggestions?: readonly WelcomeSuggestion[];
  conversationId?: number;
  onBack?: () => void;
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  showModelSelector?: boolean;
  showConversationTitle?: boolean;
  isDictationConfigured?: boolean;
  knowledgeScope?: ConversationKnowledgeScope | null;
  knowledgePreview?: KnowledgeScopeEffectivePreview | null;
  knowledgeCapabilities?: KnowledgeCapabilities | null;
  onKnowledgeScopeChange?: (
    scope: ConversationKnowledgeScope | null,
    preview?: KnowledgeScopeEffectivePreview | null
  ) => Promise<void> | void;
  variant?: "default" | "embedded";
  skillFiles?: readonly SkillFileContent[];
  onSkillFileSelect?: (path: string) => void;
  runtimeMetadata?: Record<string, unknown>;
  onRuntimeMetadataChange?: (value: Record<string, unknown>) => void;
  readOnly?: boolean;
  showComposer?: boolean;
}

/**
 * Derives ModelOption[] from agent.model_ids and agent.model_names.
 * Falls back to model_name for single model scenarios.
 */
const useAgentModels = (
  agent: Agent | PublishedAgent
): readonly ModelOption[] => {
  return useMemo(() => {
    const typedAgent = agent as PublishedAgent;
    const { model_ids, model_names } = typedAgent;

    if (
      model_ids &&
      model_ids.length > 0 &&
      model_names &&
      model_names.length > 0
    ) {
      return model_ids.map((id, i) => ({
        id: String(id),
        name: model_names[i] ?? `Model ${id}`,
      }));
    }

    // Fallback for single model: check model_name on typedAgent
    const modelName = (typedAgent as unknown as { model_name?: string })
      .model_name;
    if (modelName) {
      return [{ id: modelName, name: modelName }];
    }

    // Fallback to the single model field (used by AgentDraft / debug panel)
    const singleModel = (typedAgent as unknown as { model?: string }).model;
    if (singleModel) {
      return [{ id: singleModel, name: singleModel }];
    }

    return [];
  }, [agent]);
};

export const Thread: FC<ThreadProps> = ({
  agent,
  generatedTitle,
  welcomeTitle,
  welcomeSuggestions,
  conversationId,
  onBack,
  selectedModelId,
  onModelChange,
  chatMode,
  onChatModeChange,
  showModelSelector = true,
  showConversationTitle = true,
  isDictationConfigured = false,
  knowledgeScope = null,
  knowledgePreview = null,
  knowledgeCapabilities = null,
  onKnowledgeScopeChange,
  variant = "default",
  skillFiles,
  onSkillFileSelect,
  runtimeMetadata = {},
  onRuntimeMetadataChange,
  readOnly = false,
  showComposer = true,
}) => {
  const { t } = useTranslation();
  const models = useAgentModels(agent);

  const messages = useAuiState((s) => s.thread.messages);
  const currentThreadTitle = useAuiState((s) => {
    const currentThread = s.threads.threadItems.find(
      (item) => item.id === s.threads.mainThreadId
    );
    return currentThread?.title;
  });
  const hasMessages = messages.length > 0;
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const displayName = agent.display_name || agent.name;
  const conversationTitle =
    generatedTitle?.trim() ||
    currentThreadTitle?.trim() ||
    t("chat.thread.newChat");
  const [isShareMode, setIsShareMode] = useState(false);
  const [selectedShareMessageIds, setSelectedShareMessageIds] = useState<
    Set<number>
  >(new Set());
  const [backendMessageIdsByAuiId, setBackendMessageIdsByAuiId] = useState<
    Map<string, number>
  >(new Map());
  const [isCreatingShare, setIsCreatingShare] = useState(false);
  const [manualShareUrl, setManualShareUrl] = useState<string | null>(null);

  // Sources panel state lives at the Thread level so the right-hand panel and
  // each `group-source` button share a single source of truth. The selection
  // carries the snapshot of sources/images for the group that opened it,
  // letting the panel render even if the original message parts change.
  const [selection, setSelection] = useState<SourcesPanelSelection | null>(
    null
  );

  const open = useCallback((payload: SourcesPanelSelection) => {
    setSelection(payload);
  }, []);

  const toggle = useCallback((payload: SourcesPanelSelection) => {
    setSelection((current) => {
      if (
        current &&
        current.messageId === payload.messageId &&
        current.groupId === payload.groupId
      ) {
        return null;
      }
      return payload;
    });
  }, []);

  const close = useCallback(() => {
    setSelection(null);
  }, []);

  const panelContextValue = useMemo(
    () => ({ selection, isOpen: selection !== null, open, toggle, close }),
    [selection, open, toggle, close]
  );

  const shareableUserMessageIds = useMemo(
    () => Array.from(backendMessageIdsByAuiId.values()),
    [backendMessageIdsByAuiId]
  );

  const leaveShareMode = useCallback(() => {
    setIsShareMode(false);
    setSelectedShareMessageIds(new Set());
    setBackendMessageIdsByAuiId(new Map());
  }, []);

  const enterShareMode = useCallback(async () => {
    if (!conversationId || isRunning) return;
    const auiUserMessageIds = messages
      .filter((item) => item.role === "user")
      .map((item) => String(item.id));
    const directBackendMessageIds = auiUserMessageIds.map((id) => Number(id));
    if (
      directBackendMessageIds.length > 0 &&
      directBackendMessageIds.every(
        (id) => Number.isSafeInteger(id) && id > 0
      ) &&
      new Set(directBackendMessageIds).size === directBackendMessageIds.length
    ) {
      setBackendMessageIdsByAuiId(
        new Map(
          auiUserMessageIds.map((id, index) => [
            id,
            directBackendMessageIds[index],
          ])
        )
      );
      setSelectedShareMessageIds(new Set());
      setIsShareMode(true);
      return;
    }

    try {
      const response = await conversationService.getDetail(conversationId);
      const backendUserMessageIds = (response.data?.[0]?.message ?? [])
        .filter(
          (item) => item.role === "user" && Number.isInteger(item.message_id)
        )
        .map((item) => item.message_id as number);
      if (
        !backendUserMessageIds.length ||
        backendUserMessageIds.length !== auiUserMessageIds.length
      ) {
        message.error(t("chatInterface.shareCreateFailed", "创建分享链接失败"));
        return;
      }
      setBackendMessageIdsByAuiId(
        new Map(
          auiUserMessageIds.map((id, index) => [
            id,
            backendUserMessageIds[index],
          ])
        )
      );
      setSelectedShareMessageIds(new Set());
      setIsShareMode(true);
    } catch {
      message.error(t("chatInterface.shareCreateFailed", "创建分享链接失败"));
    }
  }, [conversationId, isRunning, messages, t]);

  const toggleShareMessage = useCallback((messageId: number) => {
    setSelectedShareMessageIds((previous) => {
      const next = new Set(previous);
      if (next.has(messageId)) next.delete(messageId);
      else next.add(messageId);
      return next;
    });
  }, []);

  const toggleShareAll = useCallback(() => {
    setSelectedShareMessageIds((previous) =>
      previous.size === shareableUserMessageIds.length
        ? new Set()
        : new Set(shareableUserMessageIds)
    );
  }, [shareableUserMessageIds]);

  const createShare = useCallback(async () => {
    if (!conversationId) return;
    if (!selectedShareMessageIds.size) {
      message.warning(
        t("chatInterface.selectShareMessages", "请至少选择一组问答")
      );
      return;
    }
    setIsCreatingShare(true);
    try {
      const result = await conversationService.createShare({
        conversationId,
        mode:
          selectedShareMessageIds.size === shareableUserMessageIds.length
            ? "all"
            : "selected",
        selected_user_message_ids: Array.from(selectedShareMessageIds),
        render_version: "newchat",
      });
      const runtimeConfig = await configService
        .fetchRuntimeFrontendConfig()
        .catch((): { shareBaseUrl?: string } => ({}));
      const baseUrl = (
        runtimeConfig.shareBaseUrl ||
        process.env.NEXT_PUBLIC_SHARE_BASE_URL ||
        window.location.origin
      ).replace(/\/$/, "");
      const locale =
        window.location.pathname.split("/").filter(Boolean)[0] || "zh";
      const shareUrl = `${baseUrl}/${locale}/share/${result.share_id}`;
      try {
        await copyToClipboard(shareUrl);
        message.success(t("chatInterface.shareLinkCopied", "分享链接已复制"));
      } catch {
        setManualShareUrl(shareUrl);
      }
      leaveShareMode();
    } catch {
      message.error(t("chatInterface.shareCreateFailed", "创建分享链接失败"));
    } finally {
      setIsCreatingShare(false);
    }
  }, [
    conversationId,
    leaveShareMode,
    selectedShareMessageIds,
    shareableUserMessageIds,
    t,
  ]);

  return (
    <SourcesPanelProvider value={panelContextValue}>
      <ThreadView
        agent={agent}
        welcomeTitle={welcomeTitle}
        welcomeSuggestions={welcomeSuggestions}
        onBack={onBack}
        models={models}
        selectedModelId={selectedModelId}
        onModelChange={onModelChange}
        chatMode={chatMode}
        onChatModeChange={onChatModeChange}
        showModelSelector={showModelSelector}
        showConversationTitle={showConversationTitle}
        isDictationConfigured={isDictationConfigured}
        knowledgeScope={knowledgeScope}
        knowledgePreview={knowledgePreview}
        knowledgeCapabilities={knowledgeCapabilities}
        onKnowledgeScopeChange={onKnowledgeScopeChange}
        variant={variant}
        skillFiles={skillFiles}
        onSkillFileSelect={onSkillFileSelect}
        runtimeMetadata={runtimeMetadata}
        onRuntimeMetadataChange={onRuntimeMetadataChange}
        readOnly={readOnly}
        showComposer={showComposer}
        hasMessages={hasMessages}
        displayName={displayName}
        conversationTitle={conversationTitle}
        conversationId={conversationId}
        isRunning={isRunning}
        isShareMode={isShareMode}
        selectedShareMessageIds={selectedShareMessageIds}
        backendMessageIdsByAuiId={backendMessageIdsByAuiId}
        isCreatingShare={isCreatingShare}
        onEnterShareMode={enterShareMode}
        onLeaveShareMode={leaveShareMode}
        onToggleShareAll={toggleShareAll}
        onToggleShareMessage={toggleShareMessage}
        onCreateShare={createShare}
        selection={selection}
        onPanelClose={close}
      />
      <Dialog
        open={Boolean(manualShareUrl)}
        onOpenChange={(open) => !open && setManualShareUrl(null)}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {t("chatInterface.shareLinkReady", "分享链接已生成")}
            </DialogTitle>
            <DialogDescription>
              {t(
                "chatInterface.shareCreatedCopyFailed",
                "分享链接已创建，但当前环境无法自动复制"
              )}
            </DialogDescription>
          </DialogHeader>
          <input
            value={manualShareUrl ?? ""}
            readOnly
            onFocus={(event) => event.currentTarget.select()}
            className="w-full rounded-md border bg-muted/30 px-3 py-2 text-sm"
          />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setManualShareUrl(null)}
            >
              {t("common.close", "关闭")}
            </Button>
            <Button
              type="button"
              onClick={async () => {
                if (!manualShareUrl) return;
                try {
                  await copyToClipboard(manualShareUrl);
                  message.success(
                    t("chatInterface.shareLinkCopied", "分享链接已复制")
                  );
                  setManualShareUrl(null);
                } catch {
                  message.warning(
                    t("chatInterface.shareManualCopyRequired", "请手动复制链接")
                  );
                }
              }}
            >
              {t("chatInterface.copyShareLink", "复制链接")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SourcesPanelProvider>
  );
};

interface ThreadViewProps {
  agent: Agent | PublishedAgent;
  welcomeTitle?: string;
  welcomeSuggestions?: readonly WelcomeSuggestion[];
  onBack?: () => void;
  models: readonly ModelOption[];
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  showModelSelector: boolean;
  showConversationTitle: boolean;
  isDictationConfigured: boolean;
  knowledgeScope: ConversationKnowledgeScope | null;
  knowledgePreview: KnowledgeScopeEffectivePreview | null;
  knowledgeCapabilities: KnowledgeCapabilities | null;
  onKnowledgeScopeChange?: (
    scope: ConversationKnowledgeScope | null,
    preview?: KnowledgeScopeEffectivePreview | null
  ) => Promise<void> | void;
  hasMessages: boolean;
  displayName: string;
  conversationTitle: string;
  conversationId?: number;
  isRunning: boolean;
  isShareMode: boolean;
  selectedShareMessageIds: Set<number>;
  backendMessageIdsByAuiId: Map<string, number>;
  isCreatingShare: boolean;
  onEnterShareMode: () => void;
  onLeaveShareMode: () => void;
  onToggleShareAll: () => void;
  onToggleShareMessage: (messageId: number) => void;
  onCreateShare: () => void;
  selection: SourcesPanelSelection | null;
  onPanelClose: () => void;
  variant: "default" | "embedded";
  skillFiles?: readonly SkillFileContent[];
  onSkillFileSelect?: (path: string) => void;
  runtimeMetadata: Record<string, unknown>;
  onRuntimeMetadataChange?: (value: Record<string, unknown>) => void;
  readOnly: boolean;
  showComposer: boolean;
}

const ThreadView: FC<ThreadViewProps> = ({
  agent,
  welcomeTitle,
  welcomeSuggestions,
  onBack,
  models,
  selectedModelId,
  onModelChange,
  chatMode,
  onChatModeChange,
  showModelSelector,
  showConversationTitle,
  isDictationConfigured,
  knowledgeScope,
  knowledgePreview,
  knowledgeCapabilities,
  onKnowledgeScopeChange,
  hasMessages,
  displayName,
  conversationTitle,
  conversationId,
  isRunning,
  isShareMode,
  selectedShareMessageIds,
  backendMessageIdsByAuiId,
  isCreatingShare,
  onEnterShareMode,
  onLeaveShareMode,
  onToggleShareAll,
  onToggleShareMessage,
  onCreateShare,
  selection,
  onPanelClose,
  variant,
  skillFiles,
  onSkillFileSelect,
  runtimeMetadata,
  onRuntimeMetadataChange,
  readOnly,
  showComposer,
}) => {
  const { t } = useTranslation();

  return (
    <ThreadPrimitive.Root
      className={cn(
        "flex h-full flex-row bg-background",
        variant === "embedded" &&
          "[&_.aui-assistant-action-bar-root]:hidden [&_.aui-user-action-bar-root]:hidden"
      )}
    >
      <div className="flex h-full min-w-0 flex-1 flex-col">
        {showConversationTitle && (
          <header className="flex items-center gap-2 border-b px-3 py-2">
            {isShareMode ? (
              <>
                <div className="flex min-w-0 flex-1 justify-center text-sm font-medium text-foreground">
                  {conversationTitle}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onLeaveShareMode}
                  aria-label={t("common.close", "关闭")}
                >
                  <XIcon className="size-4" />
                </Button>
              </>
            ) : (
              <>
                {onBack && (
                  <Button variant="ghost" size="icon" onClick={onBack}>
                    <ArrowLeft className="size-4" />
                  </Button>
                )}
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="text-sm font-medium text-foreground">
                    {hasMessages ? conversationTitle : displayName}
                  </span>
                  {hasMessages && variant !== "embedded" && (
                    <span className="text-xs text-muted-foreground">
                      {t("chat.thread.conversation")}
                    </span>
                  )}
                </div>
                {hasMessages && conversationId && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t(
                      "chatInterface.shareConversation",
                      "分享对话"
                    )}
                    disabled={isRunning}
                    onClick={onEnterShareMode}
                  >
                    <Share2Icon className="size-4" />
                  </Button>
                )}
              </>
            )}
          </header>
        )}

        {isShareMode && (
          <div className="flex items-center justify-between border-b bg-muted/30 px-4 py-2">
            <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={
                  backendMessageIdsByAuiId.size > 0 &&
                  selectedShareMessageIds.size === backendMessageIdsByAuiId.size
                }
                onChange={onToggleShareAll}
              />
              {t("common.selectAll", "全选")}
            </label>
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">
                {t("chatInterface.selectedShareCount", {
                  count: selectedShareMessageIds.size,
                  defaultValue: "已选择 {{count}}",
                })}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onLeaveShareMode}
              >
                {t("common.cancel", "取消")}
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={onCreateShare}
                disabled={isCreatingShare}
              >
                {isCreatingShare
                  ? t("common.loading", "处理中...")
                  : t("chatInterface.copyShareLink", "复制链接")}
              </Button>
            </div>
          </div>
        )}

        <ThreadPrimitive.Viewport
          className={cn(
            "mx-auto flex min-h-0 min-w-0 w-full max-w-4xl flex-1 flex-col overflow-x-hidden overflow-y-auto",
            variant === "embedded" ? "px-4 py-4" : "px-8 py-6"
          )}
        >
          {hasMessages ? (
            <ThreadMessages
              agent={agent}
              readOnly={readOnly}
              enableSkillDirectives={Boolean(skillFiles)}
              onSkillFileSelect={onSkillFileSelect}
              shareMode={isShareMode}
              selectedShareMessageIds={selectedShareMessageIds}
              backendMessageIdsByAuiId={backendMessageIdsByAuiId}
              onToggleShareMessage={onToggleShareMessage}
            />
          ) : (
            <ThreadWelcomeContent
              agent={agent}
              title={welcomeTitle}
              suggestions={welcomeSuggestions}
            />
          )}
        </ThreadPrimitive.Viewport>

        {showComposer && (
          <ThreadPrimitive.ViewportFooter
            className={cn(
              "sticky bottom-0 mx-auto flex w-full max-w-4xl flex-col",
              variant === "embedded" ? "gap-2 px-4 pb-4" : "gap-4 px-8 pb-8"
            )}
          >
            <ThreadScrollToBottom />
            <Composer
              models={models}
              selectedModelId={selectedModelId}
              onModelChange={onModelChange}
              chatMode={chatMode}
              onChatModeChange={onChatModeChange}
              showModelSelector={showModelSelector}
              isDictationConfigured={isDictationConfigured}
              knowledgeScope={knowledgeScope}
              knowledgePreview={knowledgePreview}
              knowledgeCapabilities={knowledgeCapabilities}
              onKnowledgeScopeChange={onKnowledgeScopeChange}
              compact={variant === "embedded"}
              skillFiles={skillFiles}
              runtimeMetadata={runtimeMetadata}
              onRuntimeMetadataChange={onRuntimeMetadataChange}
              allowRuntimeMetadata={agent.allow_chat_metadata === true}
              disabled={readOnly}
            />
          </ThreadPrimitive.ViewportFooter>
        )}
      </div>

      <SourcesPanel
        sources={selection?.sources ?? []}
        images={selection?.images ?? []}
        open={selection !== null}
        selectedCiteIndex={selection?.selectedCiteIndex}
        onClose={onPanelClose}
      />
    </ThreadPrimitive.Root>
  );
};

export const ReadOnlyConversation: FC<{
  agent: Agent | PublishedAgent;
  title: string;
}> = ({ agent, title }) => {
  const { t } = useTranslation();
  const [selection, setSelection] = useState<SourcesPanelSelection | null>(
    null
  );
  const open = useCallback(
    (payload: SourcesPanelSelection) => setSelection(payload),
    []
  );
  const toggle = useCallback((payload: SourcesPanelSelection) => {
    setSelection((current) =>
      current &&
      current.messageId === payload.messageId &&
      current.groupId === payload.groupId
        ? null
        : payload
    );
  }, []);
  const close = useCallback(() => setSelection(null), []);
  const panelContextValue = useMemo(
    () => ({ selection, isOpen: selection !== null, open, toggle, close }),
    [selection, open, toggle, close]
  );

  return (
    <SourcesPanelProvider value={panelContextValue}>
      <ThreadPrimitive.Root className="flex h-full flex-row bg-background">
        <main className="flex min-w-0 flex-1 flex-col">
          <header className="border-b px-6 py-4">
            <h1 className="text-lg font-semibold text-foreground">{title}</h1>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("chatInterface.shareReadOnly", "分享对话仅可查看")}
            </p>
          </header>
          <ThreadPrimitive.Viewport className="mx-auto flex w-full max-w-4xl flex-1 flex-col overflow-y-auto px-8 py-6">
            <ThreadMessages agent={agent} readOnly />
          </ThreadPrimitive.Viewport>
        </main>
        <SourcesPanel
          sources={selection?.sources ?? []}
          images={selection?.images ?? []}
          open={selection !== null}
          selectedCiteIndex={selection?.selectedCiteIndex}
          onClose={close}
        />
      </ThreadPrimitive.Root>
    </SourcesPanelProvider>
  );
};

interface ThreadWelcomeContentProps {
  agent: Agent | PublishedAgent;
  title?: string;
  suggestions?: readonly WelcomeSuggestion[];
}

const ThreadWelcomeContent: FC<ThreadWelcomeContentProps> = ({
  agent,
  title,
  suggestions = [],
}) => {
  const aui = useAui();
  const { t } = useTranslation();
  const Icon = getAgentIcon(agent);
  const displayName = agent.display_name || agent.name;
  const sampleQuestions = (agent.example_questions || []).slice(0, 4);
  const displayedSuggestions = suggestions.slice(0, 4);

  const handleSampleQuestionClick = useCallback(
    (question: string) => {
      aui.composer().setText(question);
    },
    [aui]
  );

  return (
    <div className="flex h-full flex-col overflow-y-auto px-8 py-8">
      <div className="flex flex-1 items-center justify-center">
        <div className="flex w-full max-w-2xl flex-col items-center gap-6">
          <div className="flex size-16 items-center justify-center rounded-full bg-primary/10 ring-4 ring-primary/10">
            <Icon className="size-8 text-primary" />
          </div>

          <div className="text-center">
            <h1 className="text-balance text-2xl font-bold text-foreground md:text-3xl">
              {title ?? t("chat.thread.helloAgent", { agent: displayName })}
            </h1>
            <p className="mx-auto mt-3 max-w-xl text-pretty text-sm leading-relaxed text-muted-foreground">
              {agent.greeting_message || agent.description}
            </p>
          </div>

          {displayedSuggestions.length > 0 ? (
            <div className="grid w-full auto-rows-fr grid-cols-1 gap-2 sm:grid-cols-2">
              {displayedSuggestions.map((suggestion) => {
                const SuggestionIcon = suggestion.icon;
                return (
                  <button
                    key={suggestion.id}
                    type="button"
                    onClick={() =>
                      handleSampleQuestionClick(suggestion.prompt)
                    }
                    className="flex h-full min-h-20 items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-left transition-colors hover:border-primary/40 hover:bg-accent/50"
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <SuggestionIcon className="size-5" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium leading-5 text-foreground">
                        {suggestion.title}
                      </span>
                      <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                        {suggestion.description}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          ) : sampleQuestions.length > 0 ? (
            <div className="w-full">
              <p className="mb-4 flex items-center justify-center gap-1.5 text-xs font-medium text-muted-foreground">
                <SparklesIcon className="size-3.5 text-primary" />
                {t("chat.thread.tryQuestions")}
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {sampleQuestions.map((q, index) => (
                  <button
                    key={index}
                    type="button"
                    onClick={() => handleSampleQuestionClick(q)}
                    className="truncate rounded-xl border border-border bg-card px-4 py-3 text-left text-sm text-foreground transition-colors hover:border-primary/40 hover:bg-accent/50"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};

export const ThreadMessages: FC<{
  agent: Agent | PublishedAgent;
  readOnly?: boolean;
  shareMode?: boolean;
  selectedShareMessageIds?: Set<number>;
  backendMessageIdsByAuiId?: Map<string, number>;
  onToggleShareMessage?: (messageId: number) => void;
  enableSkillDirectives?: boolean;
  onSkillFileSelect?: (path: string) => void;
}> = ({
  agent,
  readOnly = false,
  shareMode = false,
  selectedShareMessageIds,
  backendMessageIdsByAuiId,
  onToggleShareMessage,
  enableSkillDirectives = false,
  onSkillFileSelect,
}) => {
  const { t } = useTranslation();
  const messages = useAuiState((s) => s.thread.messages);
  const shareMessageGroups = useMemo(() => {
    const groups: {
      key: string;
      messageIndexes: number[];
      userMessageId?: number;
    }[] = [];

    messages.forEach((message, index) => {
      if (message.role === "user") {
        groups.push({
          key: String(message.id),
          messageIndexes: [index],
          userMessageId: backendMessageIdsByAuiId?.get(String(message.id)),
        });
        return;
      }

      const currentGroup = groups.at(-1);
      if (currentGroup) currentGroup.messageIndexes.push(index);
      else groups.push({ key: String(message.id), messageIndexes: [index] });
    });

    return groups;
  }, [backendMessageIdsByAuiId, messages]);

  const messageComponents = useMemo(
    () => ({
      UserMessage: () => (
        <UserMessage
          readOnly={readOnly}
          enableSkillDirectives={enableSkillDirectives}
        />
      ),
      AssistantMessage: () => (
        <AssistantMessage
          agent={agent}
          readOnly={readOnly}
          onSkillFileSelect={onSkillFileSelect}
        />
      ),
    }),
    [agent, enableSkillDirectives, onSkillFileSelect, readOnly]
  );

  if (shareMode) {
    return (
      <>
        {shareMessageGroups.map((group) => {
          const shareSelected =
            group.userMessageId !== undefined &&
            (selectedShareMessageIds?.has(group.userMessageId) ?? false);
          return (
            <div
              key={group.key}
              className={`relative mb-4 w-full rounded-xl px-2 pt-1 pb-2 ${
                shareSelected
                  ? "bg-blue-100/80 shadow-[0_4px_18px_rgba(37,99,235,0.28)]"
                  : ""
              }`}
            >
              {group.userMessageId !== undefined && (
                <label className="absolute -left-6 top-3 z-10 flex cursor-pointer items-center justify-center">
                  <input
                    type="checkbox"
                    aria-label={t(
                      "chatInterface.selectShareMessages",
                      "请选择要分享的问答"
                    )}
                    checked={shareSelected}
                    onChange={() =>
                      onToggleShareMessage?.(group.userMessageId!)
                    }
                  />
                </label>
              )}
              {group.messageIndexes.map((index) => (
                <ThreadPrimitive.MessageByIndex
                  key={index}
                  index={index}
                  components={messageComponents}
                />
              ))}
            </div>
          );
        })}
      </>
    );
  }

  return (
    <ThreadPrimitive.Messages>
      {({ message }) => {
        if (message.role === "user") {
          return (
            <UserMessage
              readOnly={readOnly}
              enableSkillDirectives={enableSkillDirectives}
              shareMode={shareMode}
              selectedShareMessageIds={selectedShareMessageIds}
              backendMessageIdsByAuiId={backendMessageIdsByAuiId}
              onToggleShareMessage={onToggleShareMessage}
            />
          );
        }
        return (
          <AssistantMessage
            agent={agent}
            readOnly={readOnly}
            onSkillFileSelect={onSkillFileSelect}
          />
        );
      }}
    </ThreadPrimitive.Messages>
  );
};

const ThreadScrollToBottom: FC = () => {
  const { t } = useTranslation();

  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <TooltipIconButton
        tooltip={t("chat.thread.scrollToBottom")}
        className="absolute -top-12 self-center rounded-full p-4"
      >
        <ArrowDownIcon />
      </TooltipIconButton>
    </ThreadPrimitive.ScrollToBottom>
  );
};

const MessageError: FC = () => {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="aui-message-error-root border-destructive bg-destructive/10 text-destructive dark:bg-destructive/5 mt-2 rounded-md border p-3 text-sm dark:text-red-200">
        <ErrorPrimitive.Message className="aui-message-error-message line-clamp-2" />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
};

const AssistantWorkingIndicator: FC = () => {
  const { t } = useTranslation();
  const isEmpty = useAuiState((s) => s.message.content.length === 0);
  if (isEmpty) {
    return (
      <span
        data-slot="aui_assistant-message-indicator"
        className="text-muted-foreground inline-flex items-center gap-2 align-middle"
      >
        <DotMatrix state="connecting" aria-hidden />
        <span className="text-sm">{t("chat.thread.connecting")}</span>
      </span>
    );
  }
  return (
    <span
      data-slot="aui_assistant-message-indicator"
      className="animate-pulse font-sans"
      aria-label={t("chat.thread.working")}
    >
      {"●"}
    </span>
  );
};

const AssistantCompletionIndicator: FC = () => {
  const { t } = useTranslation();
  const isComplete = useAuiState((s) => s.message.status?.type === "complete");

  if (!isComplete) return null;

  return (
    <span
      data-slot="aui_assistant-message-completion-indicator"
      className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400"
      role="status"
    >
      <DotMatrix state="success" aria-hidden />
      <span>{t("chat.thread.complete")}</span>
    </span>
  );
};

type DatabaseTimeMetadata = {
  databaseCreateTime?: number;
};

const getDatabaseCreateTime = (metadata: unknown): number | undefined => {
  if (!metadata || typeof metadata !== "object") return undefined;
  const custom = (metadata as { custom?: DatabaseTimeMetadata }).custom;
  return custom?.databaseCreateTime;
};

const MessageTimestamp: FC<{ className?: string }> = ({ className }) => {
  const createTime = useAuiState((s) =>
    getDatabaseCreateTime(s.message.metadata)
  );
  const displayTime = formatMessageTime(createTime);

  if (!displayTime) return null;

  return (
    <time
      dateTime={new Date(createTime!).toISOString()}
      className={cn("text-xs text-muted-foreground", className)}
    >
      {displayTime}
    </time>
  );
};

const MessageDateSeparator: FC = () => {
  const { i18n } = useTranslation();
  const createTime = useAuiState((s) =>
    getDatabaseCreateTime(s.message.metadata)
  );
  const previousCreateTime = useAuiState((s) => {
    if (s.message.index <= 0) return undefined;
    return getDatabaseCreateTime(
      s.thread.messages.at(s.message.index - 1)?.metadata
    );
  });

  if (!shouldShowDateSeparator(createTime, previousCreateTime)) return null;

  const label = formatMessageDate(
    createTime,
    i18n.resolvedLanguage ?? i18n.language
  );
  if (!label) return null;

  return (
    <div
      role="separator"
      aria-label={label}
      className="col-span-full !col-start-1 mx-auto my-4 flex w-full max-w-(--thread-max-width) items-center gap-3 px-2 text-xs text-muted-foreground"
    >
      <span className="h-px flex-1 bg-border" aria-hidden />
      <time dateTime={new Date(createTime!).toISOString()}>{label}</time>
      <span className="h-px flex-1 bg-border" aria-hidden />
    </div>
  );
};

const AssistantMessage: FC<{
  agent: Agent | PublishedAgent;
  readOnly?: boolean;
  onSkillFileSelect?: (path: string) => void;
}> = ({ agent, readOnly = false, onSkillFileSelect }) => {
  const { t } = useTranslation();
  // Reserves space for the action bar; `-mb` compensates so the action bar's
  // hover-revealed position does not shift the message spacing. For pt-[n]
  // use `-mb-[n + 6]` and `min-h-[n + 6]` to preserve the compensation.
  const ACTION_BAR_PT = "pt-1 pb-1 mb-1";
  const ACTION_BAR_HEIGHT = `-mb-7.5 min-h-7.5 ${ACTION_BAR_PT}`;

  const AgentIcon = getAgentIcon(agent);
  const agentName = agent.display_name || agent.name;

  const nl2a = useAuiState(
    (s) =>
      (s.message.metadata?.custom as { nl2a?: Nl2aMessage } | undefined)?.nl2a
  );
  const messageId = useAuiState((s) => s.message.id as string | undefined);
  const content = useAuiState((s) => s.message.content) as ReadonlyArray<{
    type?: string;
    skillFileAttachments?: CompleteAttachment[];
  }>;
  const streamedSkillFileAttachments = useMemo(() => {
    for (let index = content.length - 1; index >= 0; index -= 1) {
      const part = content[index];
      if (part.type === "text" && part.skillFileAttachments?.length) {
        return part.skillFileAttachments;
      }
    }
    return undefined;
  }, [content]);
  const skillFileAttachments =
    streamedSkillFileAttachments ??
    (messageId ? skillFileUploadsRegistry.get(messageId) : undefined);

  return (
    <MessagePrimitive.Root
      data-slot="aui_assistant-message-root"
      data-role="assistant"
      className="fade-in slide-in-from-bottom-1 animate-in relative mx-auto min-w-0 w-full max-w-(--thread-max-width) duration-150"
    >
      <MessageDateSeparator />
      <div
        data-slot="aui_assistant-message-content"
        className="text-foreground min-w-0 px-2 pt-3 pb-1 leading-relaxed wrap-break-word"
      >
        <header className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div
              data-slot="aui_assistant-message-avatar"
              className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 ring-1 ring-primary/10"
              aria-hidden
            >
              <AgentIcon className="size-4 text-primary" />
            </div>
            <span className="text-sm font-medium text-foreground">
              {agentName}
            </span>
            <AssistantCompletionIndicator />
          </div>
          <MessageTimestamp />
        </header>
        <MessagePrimitive.GroupedParts
          groupBy={(part) => {
            // Sub-agent parts first enter a shared calls summary, then a
            // run-specific group. Distinct `runId` suffixes keep repeated or
            // parallel invocations as separate cards inside the summary.
            // Each card retains the same reasoning/tool grouping as the main
            // message.
            const meta = (
              part as {
                metadata?: { subagentId?: number | string; runId?: string };
              }
            ).metadata;
            const subagentId = meta?.subagentId;
            const runId = meta?.runId;
            const isImagePart =
              (part.type === "image" &&
                Boolean((part as { image?: string }).image)) ||
              (part.type === "text" &&
                Boolean(
                  (part as {
                    isSearchImage?: boolean;
                    imageSource?: SourcePartLike;
                  }).isSearchImage &&
                    (part as { imageSource?: SourcePartLike }).imageSource
                ));
            const chainPath: `group-${string}`[] = isImagePart
              ? ["group-image"]
              : part.type === "reasoning"
                ? ["group-chainOfThought", "group-reasoning"]
                : part.type === "tool-call"
                  ? ["group-chainOfThought", "group-tool"]
                  : part.type === "source"
                    ? ["group-source"]
                    : ["group-default"];
            if (subagentId !== undefined) {
              const groupKey =
                `group-subagent-${subagentId}-${runId ?? "unknown"}` as const;
              return [
                "group-subagent-calls",
                groupKey,
                ...chainPath,
              ] as `group-${string}`[];
            }
            return chainPath;
          }}
        >
          {({ part, children }) => {
            const partType = (part as { type?: string }).type;
            if (partType === "group-subagent-calls") {
              const groupPart = part as unknown as {
                indices: readonly number[];
                status: { type: string };
              };
              return renderSubAgentCallsGroup(groupPart, children);
            }
            if (
              typeof partType === "string" &&
              partType.startsWith("group-subagent-")
            ) {
              const groupPart = part as unknown as {
                type: string;
                indices: readonly number[];
                status: { type: string };
              };
              return renderSubAgentGroup(groupPart, children);
            }

            if (partType === "verification-panel") {
              const verificationPanel = part as typeof part & {
                results?: VerificationContent[];
                completed?: boolean;
              };
              return (
                <VerificationPanel
                  results={verificationPanel.results ?? []}
                  completed={verificationPanel.completed === true}
                />
              );
            }

            switch (part.type) {
              case "group-image":
                return (
                  <div className="grid grid-cols-1 gap-3 py-2 sm:grid-cols-3">
                    {children}
                  </div>
                );
              case "group-chainOfThought":
                return <div data-slot="aui_chain-of-thought">{children}</div>;
              case "group-tool":
                return (
                  <ToolGroupRoot variant="ghost">
                    <ToolGroupTrigger
                      count={
                        (part as typeof part & { indices?: unknown[] }).indices
                          ?.length ?? 0
                      }
                      active={
                        (part as typeof part & { status?: { type?: string } })
                          .status?.type === "running"
                      }
                    />
                    <ToolGroupContent>{children}</ToolGroupContent>
                  </ToolGroupRoot>
                );
              case "group-reasoning": {
                const running =
                  (part as typeof part & { status?: { type?: string } }).status
                    ?.type === "running";
                return (
                  <Reasoning.Root defaultOpen={running}>
                    <GroupReasoningTrigger active={running} />
                    <Reasoning.Content aria-busy={running}>
                      <Reasoning.Text>{children}</Reasoning.Text>
                    </Reasoning.Content>
                  </Reasoning.Root>
                );
              }
              case "group-source":
                return (
                  <SourceGroupButton
                    indices={
                      (part as typeof part & { indices?: unknown[] }).indices ??
                      []
                    }
                  />
                );
              case "group-default":
                return <>{children}</>;
              case "text": {
                const textPart = part as typeof part & {
                  isError?: boolean;
                  text?: string;
                  isSearchImage?: boolean;
                  imageSource?: SourcePartLike;
                };
                if (textPart.isSearchImage && textPart.imageSource) {
                  return <GlobalSearchImage source={textPart.imageSource} />;
                }
                if (textPart.isError) {
                  return (
                    <div className="mt-2 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                      <XCircleIcon className="mt-0.5 size-4 shrink-0 text-red-500 dark:text-red-400" />
                      <span className="break-all">{textPart.text}</span>
                    </div>
                  );
                }
                return <MarkdownText />;
              }
              case "image": {
                const imageUrl = (part as typeof part & { image?: string })
                  .image;
                return imageUrl ? (
                  <GlobalSearchImage
                    source={{
                      type: "source",
                      sourceType: "url",
                      url: imageUrl,
                      title: imageUrl,
                    }}
                  />
                ) : null;
              }
              case "reasoning":
                return <Reasoning {...part} />;
              case "tool-call":
                return (
                  (part as typeof part & { toolUI?: unknown }).toolUI ?? (
                    <ToolFallback {...part} />
                  )
                );
              case "indicator":
                return <AssistantWorkingIndicator />;
              case "source":
                if ((part as SourcePartLike).isImage) {
                  return <GlobalSearchImage source={part as SourcePartLike} />;
                }
                return <Sources {...part} />;
              case "data":
                if (
                  (part as typeof part & { name?: string }).name ===
                  "nl2skill-file"
                ) {
                  return (
                    <SkillFileCard
                      data={
                        (part as typeof part & { data?: unknown })
                          .data as Nl2SkillFileCardData
                      }
                      onSkillFileSelect={onSkillFileSelect}
                    />
                  );
                }
                if (
                  (part as typeof part & { name?: string }).name ===
                  "automation-proposal"
                ) {
                  return (
                    <AutomationProposalMessage
                      proposal={
                        (part as typeof part & { data?: unknown })
                          .data as AgentAutomationProposalData
                      }
                    />
                  );
                }
                return (
                  ((part as typeof part & { dataRendererUI?: unknown })
                    .dataRendererUI as ReactNode) ?? null
                );
              default:
                return null;
            }
          }}
        </MessagePrimitive.GroupedParts>
        {nl2a?.content.subtype === "requirement_clarification" ? (
          <RequirementClarificationCard
            payload={nl2a.content}
            disabled={readOnly}
          />
        ) : nl2a?.content.subtype === "local_mcp_recommendation" ? (
          <ToolRecommendations payload={nl2a.content} disabled={readOnly} />
        ) : nl2a?.content.subtype === "agent_draft" ? (
          <AgentDraftCard draft={nl2a.content} disabled={readOnly} />
        ) : nl2a?.content.subtype === "suggested_resource_installation" ? (
          <SuggestedResourceInstallationCard
            payload={nl2a.content}
            disabled={readOnly}
          />
        ) : nl2a?.content.subtype === "installed_resource_binding" ? (
          <InstalledResourceBindingCard
            payload={nl2a.content}
            disabled={readOnly}
          />
        ) : null}
        {skillFileAttachments?.length ? (
          <AssistantMessageAttachments attachments={skillFileAttachments} />
        ) : null}
        <MessageError />
      </div>

      <div
        data-slot="aui_assistant-message-footer"
        className={cn("ml-2 flex items-center", ACTION_BAR_HEIGHT)}
      >
        {!readOnly && <BranchPicker />}
        {!readOnly && <AssistantActionBar />}
      </div>
    </MessagePrimitive.Root>
  );
};

const AssistantActionBar: FC = () => {
  const { t } = useTranslation();

  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="never"
      className="aui-assistant-action-bar-root text-muted-foreground animate-in fade-in col-start-3 row-start-2 -ml-1 flex w-full items-center gap-1 duration-200"
    >
      <div className="flex items-center gap-1">
        <ActionBarPrimitive.Copy asChild>
          <TooltipIconButton tooltip={t("chat.thread.copy")}>
            <AuiIf condition={(s) => s.message.isCopied}>
              <CheckIcon className="animate-in zoom-in-50 fade-in duration-200 ease-out" />
            </AuiIf>
            <AuiIf condition={(s) => !s.message.isCopied}>
              <CopyIcon className="animate-in zoom-in-75 fade-in duration-150" />
            </AuiIf>
          </TooltipIconButton>
        </ActionBarPrimitive.Copy>
        <ActionBarPrimitive.Reload asChild>
          <TooltipIconButton tooltip={t("chat.thread.refresh")}>
            <RefreshCwIcon />
          </TooltipIconButton>
        </ActionBarPrimitive.Reload>
        <ActionBarMorePrimitive.Root>
          <ActionBarMorePrimitive.Trigger asChild>
            <TooltipIconButton
              tooltip={t("chat.thread.more")}
              className="data-[state=open]:bg-accent"
            >
              <MoreHorizontalIcon />
            </TooltipIconButton>
          </ActionBarMorePrimitive.Trigger>
          <ActionBarMorePrimitive.Content
            side="bottom"
            align="start"
            sideOffset={6}
            className="aui-action-bar-more-content bg-popover/95 text-popover-foreground data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:animate-out data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 min-w-[8rem] overflow-hidden rounded-xl border p-1.5 shadow-lg backdrop-blur-sm"
          >
            <ActionBarPrimitive.ExportMarkdown asChild>
              <ActionBarMorePrimitive.Item className="aui-action-bar-more-item hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none select-none">
                <DownloadIcon className="size-4" />
                {t("chat.thread.exportMarkdown")}
              </ActionBarMorePrimitive.Item>
            </ActionBarPrimitive.ExportMarkdown>
          </ActionBarMorePrimitive.Content>
        </ActionBarMorePrimitive.Root>
      </div>
      <div className="flex items-center gap-1 ml-auto">
        <MessageTiming />
        <SingleTurnTokenUsage />
      </div>
    </ActionBarPrimitive.Root>
  );
};

const UserMessage: FC<{
  readOnly?: boolean;
  shareMode?: boolean;
  selectedShareMessageIds?: Set<number>;
  backendMessageIdsByAuiId?: Map<string, number>;
  onToggleShareMessage?: (messageId: number) => void;
  enableSkillDirectives?: boolean;
}> = ({
  readOnly = false,
  shareMode = false,
  selectedShareMessageIds,
  backendMessageIdsByAuiId,
  onToggleShareMessage,
  enableSkillDirectives = false,
}) => {
  const { t } = useTranslation();
  const auiMessageId = useAuiState((s) => String(s.message.id));
  const backendMessageId = backendMessageIdsByAuiId?.get(auiMessageId);
  return (
    <MessagePrimitive.Root
      data-slot="aui_user-message-root"
      data-role="user"
      className="relative fade-in slide-in-from-bottom-1 animate-in mx-auto grid w-full max-w-(--thread-max-width) auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 duration-150 [&:where(>*)]:col-start-2"
    >
      <MessageDateSeparator />
      {shareMode && backendMessageId !== undefined && (
        <label className="absolute left-2 top-1/2 z-10 flex -translate-y-1/2 cursor-pointer items-center justify-center">
          <input
            type="checkbox"
            aria-label={t(
              "chatInterface.selectShareMessages",
              "请选择要分享的问答"
            )}
            checked={selectedShareMessageIds?.has(backendMessageId) ?? false}
            onChange={() => onToggleShareMessage?.(backendMessageId)}
          />
        </label>
      )}
      <div className="col-start-2 flex flex-col gap-2">
        <UserMessageAttachments />

        <div className="aui-user-message-content-wrapper relative self-end inline-block min-w-0">
          <div className="aui-user-message-content peer bg-muted text-foreground rounded-xl px-4 py-2 wrap-break-word empty:hidden">
            <MessagePrimitive.Quote>
              {(quote) => <QuoteBlock {...quote} />}
            </MessagePrimitive.Quote>
            <MessagePrimitive.Parts
              components={{
                Text: enableSkillDirectives
                  ? SkillDirectiveText
                  : DirectiveText,
              }}
            />
          </div>
          {!readOnly && (
            <div className="aui-user-action-bar-wrapper absolute top-1/2 left-0 -translate-x-full -translate-y-1/2 pr-2 peer-empty:hidden">
              <UserActionBar />
            </div>
          )}
        </div>
        <MessageTimestamp className="self-end" />
      </div>

      {!readOnly && (
        <BranchPicker
          data-slot="aui_user-branch-picker"
          className="col-span-full col-start-1 row-start-3 -mr-1 justify-end"
        />
      )}
    </MessagePrimitive.Root>
  );
};

const UserActionBar: FC = () => {
  const { t } = useTranslation();

  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-user-action-bar-root flex flex-col items-end"
    >
      <ActionBarPrimitive.Edit asChild>
        <TooltipIconButton
          tooltip={t("chat.thread.edit")}
          className="aui-user-action-edit"
        >
          <PencilIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Edit>
    </ActionBarPrimitive.Root>
  );
};

/**
 * Loose typing for source parts emitted by remote-chat-model-adapter so we can
 * detect the synthetic `isImage` flag on picture_web entries. The base shape
 * stays compatible with `@assistant-ui/react`'s `SourceMessagePartComponent`.
 */
interface SourcePartLike {
  type: "source";
  sourceType?: "url" | "document";
  url?: string;
  title?: string;
  text?: string;
  filename?: string;
  downloadUrl?: string;
  objectName?: string;
  isImage?: boolean;
  citeIndex?: number;
  messageId?: string;
}

/**
 * Renders a single image source as a thumbnail link, matching the
 * `ToolFallback.SearchContent` image cell so the global "检索结果:" block
 * and the per-tool Sources block share the same look for picture_web entries.
 */
const GlobalSearchImage: FC<{ source: SourcePartLike }> = ({ source }) => {
  const imageUrl = source.url || "";
  if (!imageUrl) return null;
  const displayTitle =
    source.title && source.title !== imageUrl ? source.title : undefined;
  return (
    <figure
      className="aui-global-search-image min-w-0 overflow-hidden rounded-md border bg-muted/30"
      title={imageUrl}
    >
      <AuthenticatedImage
        src={imageUrl}
        alt={displayTitle || imageUrl}
        loading="lazy"
        preview
        proxy
        className="aspect-[4/3] max-h-56 w-full bg-muted/50 object-cover"
      />
      {displayTitle || source.text ? (
        <figcaption className="border-t bg-card px-3 py-2">
          {displayTitle ? (
            <div className="text-sm font-medium text-foreground">
              {displayTitle}
            </div>
          ) : null}
          {source.text ? (
            <div className="mt-1 line-clamp-4 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
              {source.text}
            </div>
          ) : null}
        </figcaption>
      ) : null}
    </figure>
  );
};

/**
 * Trigger button rendered in place of the inline source chips. The actual
 * content is hidden until the user opens the side panel so a search run that
 * produced many sources doesn't push the assistant message around.
 */
interface SourceGroupButtonProps {
  indices: readonly number[];
}

/**
 * Renders the tool-style summary for all sub-agent invocations in a message.
 * Each invocation is counted once by runId while its existing nested card
 * remains responsible for the task details and streamed execution content.
 */
const renderSubAgentCallsGroup = (
  part: {
    indices: readonly number[];
    status: { type: string };
  },
  children: ReactNode
): ReactElement => (
  <SubAgentCallsGroupRenderer indices={part.indices}>
    {children}
  </SubAgentCallsGroupRenderer>
);

const SubAgentCallsGroupRenderer: FC<{
  indices: readonly number[];
  children: ReactNode;
}> = ({ indices, children }) => {
  const content = useAuiState((s) => s.message.content) as ReadonlyArray<{
    metadata?: { runId?: string; isRunning?: boolean };
  }>;
  const { count, active } = useMemo(() => {
    const runIds = new Set<string>();
    let hasRunningCall = false;
    for (const index of indices) {
      const metadata = content[index]?.metadata;
      if (metadata?.runId) runIds.add(metadata.runId);
      if (metadata?.isRunning) hasRunningCall = true;
    }
    return { count: runIds.size, active: hasRunningCall };
  }, [content, indices]);
  const label = `${count} subagent ${count === 1 ? "call" : "calls"}`;

  return (
    <ToolGroupRoot variant="ghost" defaultOpen={active}>
      <ToolGroupTrigger count={count} active={active} label={label} />
      <ToolGroupContent>{children}</ToolGroupContent>
    </ToolGroupRoot>
  );
};

/**
 * Renders the collapsible card for a `group-subagent-<id>-<runId>` cluster.
 * Reads agent name / task / running state from the group's member parts:
 * the streaming adapter stamps a `data` boundary part on `subagent_start`
 * with the canonical descriptor, and every member part carries matching
 * `metadata` (incl. `isRunning`).
 *
 * `part.indices` indexes into the assistant-ui content array; the first
 * member is the boundary stamp because the adapter pushes it first.
 */
const renderSubAgentGroup = (
  part: {
    type: string;
    indices: readonly number[];
    status: { type: string };
  },
  children: ReactNode
): ReactElement | null => {
  // We can't read s.message.content from inside the children callback
  // because the callback is not a component. Defer to a small inline
  // component so the selector re-runs on each streaming yield.
  return (
    <SubAgentGroupRenderer indices={part.indices}>
      {children}
    </SubAgentGroupRenderer>
  );
};

const SubAgentGroupRenderer: FC<{
  indices: readonly number[];
  children: ReactNode;
}> = ({ indices, children }) => {
  const content = useAuiState((s) => s.message.content) as ReadonlyArray<{
    type?: string;
    metadata?: {
      subagentId?: number | string;
      runId?: string;
      agentName?: string;
      depth?: number;
      task?: string;
      isRunning?: boolean;
    };
    data?: {
      agentName?: string;
      task?: string;
      depth?: number;
      isRunning?: boolean;
    };
    name?: string;
  }>;
  const descriptor = useMemo(() => {
    let agentName = "subagent";
    let task: string | undefined;
    let depth = 1;
    let isRunning = false;
    let runId: string | undefined;
    let subagentId: number | string | undefined;
    for (const index of indices) {
      const member = content[index];
      const meta = member?.metadata;
      if (runId === undefined && meta?.runId) runId = meta.runId;
      if (subagentId === undefined && meta?.subagentId !== undefined) {
        subagentId = meta.subagentId;
      }
      // The first member is the boundary stamp; prefer its `data` field.
      if (
        member?.type === "data" &&
        member.name === "subagent-boundary" &&
        member.data
      ) {
        if (member.data.agentName) agentName = member.data.agentName;
        if (member.data.task) task = member.data.task;
        if (typeof member.data.depth === "number") depth = member.data.depth;
        if (typeof member.data.isRunning === "boolean")
          isRunning = member.data.isRunning;
        break;
      }
      if (meta?.agentName) agentName = meta.agentName;
      if (meta?.task) task = meta.task;
      if (typeof meta?.depth === "number") depth = meta.depth;
      if (typeof meta?.isRunning === "boolean")
        isRunning = isRunning || meta.isRunning;
    }
    if (indices.length > 0) {
      const lastMember = content[indices[indices.length - 1]];
      if (
        lastMember?.metadata &&
        typeof lastMember.metadata.isRunning === "boolean"
      ) {
        isRunning = lastMember.metadata.isRunning;
      }
    }
    return { agentName, task, depth, isRunning, runId, subagentId };
  }, [content, indices]);

  return (
    <SubAgentContainer
      agentName={descriptor.agentName}
      depth={descriptor.depth}
      isRunning={descriptor.isRunning}
      task={descriptor.task}
      runId={descriptor.runId}
      subagentId={descriptor.subagentId}
    >
      {children}
    </SubAgentContainer>
  );
};

const SourceGroupButton: FC<SourceGroupButtonProps> = ({ indices }) => {
  const { t } = useTranslation();
  // Subscribe to the current message so we can split the indices into image
  // vs. regular sources — `useAuiState` re-runs the selector on every change,
  // which keeps the counts accurate while a streaming run appends parts.
  const content = useAuiState((s) => s.message.content) as ReadonlyArray<{
    type?: string;
    [key: string]: unknown;
  }>;
  const messageId = useAuiState((s) => s.message.id as string | undefined);

  const { sources, images, total } = useMemo(() => {
    const srcs: PanelSourceItem[] = [];
    const imgs: PanelSourceItem[] = [];
    const groupedSources = indices.flatMap((index) => {
      const raw = content[index] as SourcePartLike | undefined;
      return raw?.type === "source" ? [raw] : [];
    });
    const registryMessageId =
      groupedSources.find((source) => source.messageId)?.messageId ?? messageId;
    const registeredSources = registryMessageId
      ? (searchSourcesRegistry.get(registryMessageId) ??
        conversationSourcesRegistry.get(registryMessageId))
      : undefined;
    const displaySources: PanelSourceItem[] = registeredSources?.length
      ? registeredSources.map((source) => ({
          sourceType:
            source.sourceType === "file" || source.sourceType === "document"
              ? "document"
              : "url",
          url: source.url,
          title: source.title,
          text: source.text,
          filename: source.filename,
          downloadUrl: source.downloadUrl,
          objectName: source.objectName,
          isImage: source.isImage,
          citeIndex: source.citeIndex,
        }))
      : groupedSources;
    for (const item of displaySources) {
      if (item.isImage) {
        imgs.push(item);
      } else {
        srcs.push(item);
      }
    }
    return { sources: srcs, images: imgs, total: srcs.length + imgs.length };
  }, [content, indices, messageId]);

  const { toggle, selection, isOpen } = useSourcesPanel();
  const groupId = indices.length > 0 ? indices.join(",") : "default";
  const isActive =
    isOpen &&
    selection !== null &&
    selection.messageId === messageId &&
    selection.groupId === groupId;

  const handleClick = useCallback(() => {
    if (!messageId) return;
    toggle({
      messageId,
      groupId,
      sources,
      images,
    });
  }, [messageId, groupId, sources, images, toggle]);

  if (total === 0) return null;

  return (
    <div className="pt-3 pb-2">
      <button
        type="button"
        onClick={handleClick}
        aria-expanded={isActive}
        aria-pressed={isActive}
        className="aui-source-group-button inline-flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-accent/50"
      >
        <span
          aria-hidden
          className="inline-flex items-center gap-1 text-muted-foreground"
        >
          <FileTextIcon className="size-3.5" />
          {t("chat.thread.searchResults")}
        </span>
        <span className="text-foreground">
          {sources.length > 0
            ? t("chat.thread.sourceCount", { count: sources.length })
            : ""}
          {sources.length > 0 && images.length > 0 ? ", " : ""}
          {images.length > 0
            ? t("chat.thread.imageCount", { count: images.length })
            : ""}
        </span>
        {images.length > 0 ? (
          <ImageIcon className="size-3.5 text-muted-foreground" aria-hidden />
        ) : null}
      </button>
    </div>
  );
};
