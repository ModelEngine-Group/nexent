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
  PencilIcon,
  XCircleIcon,
} from "lucide-react";
import type { Agent, PublishedAgent } from "@/types/agentConfig";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import type { ModelOption } from "../ui/model-selector";
import AutomationProposalMessage from "@/features/agentAutomation/components/AutomationProposalMessage";
import type { AgentAutomationProposalData } from "@/types/agentAutomation";
import {
  AssistantMessageAttachments,
  UserMessageAttachments,
} from "../ui/attachment";
import { DirectiveText } from "../ui/directive-text";
import { QuoteBlock } from "../ui/quote";
import { BranchPicker } from "../ui/branch-picker";
import { DotMatrix } from "../ui/dot-matrix";
import { MessageTiming } from "../ui/message-timing";
import { SingleTurnTokenUsage } from "../ui/token-usage";
import { ToolFallback } from "../ui/tool-fallback";
import { ToolRecommendations } from "../ui/tool-recommendations";
import { AgentDraftCard } from "../ui/agent-draft-card";
import {
  ToolGroupContent,
  ToolGroupRoot,
  ToolGroupTrigger,
} from "../ui/tool-group";
import {
  getAgentRunTime,
  skillFileUploadsRegistry,
  type Nl2aMessage,
} from "../adapter/remote-chat-model-adapter";
import { cn } from "@/lib/utils";

export interface ThreadProps {
  agent: Agent | PublishedAgent;
  generatedTitle?: string;
  onBack?: () => void;
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  showModelSelector?: boolean;
}

/**
 * Derives ModelOption[] from agent.model_ids and agent.model_names.
 * Falls back to model_name for single model scenarios.
 */
const useAgentModels = (agent: Agent | PublishedAgent): readonly ModelOption[] => {
  return useMemo(() => {
    const typedAgent = agent as PublishedAgent;
    const { model_ids, model_names } = typedAgent;

    if (model_ids && model_ids.length > 0 && model_names && model_names.length > 0) {
      return model_ids.map((id, i) => ({
        id: String(id),
        name: model_names[i] ?? `Model ${id}`,
      }));
    }

    // Fallback for single model: check model_name on typedAgent
    const modelName = (typedAgent as unknown as { model_name?: string }).model_name;
    if (modelName) {
      return [{ id: modelName, name: modelName }];
    }

    return [];
  }, [agent]);
};

export const Thread: FC<ThreadProps> = ({
  agent,
  generatedTitle,
  onBack,
  selectedModelId,
  onModelChange,
  chatMode,
  onChatModeChange,
  showModelSelector = true,
}) => {
  const { t } = useTranslation();
  const models = useAgentModels(agent);

  const messages = useAuiState((s) => s.thread.messages);
  const currentThreadTitle = useAuiState((s) => {
    const currentThread = s.threads.threadItems.find(
      (item) => item.id === s.threads.mainThreadId,
    );
    return currentThread?.title;
  });
  const hasMessages = messages.length > 0;
  const displayName = agent.display_name || agent.name;
  const conversationTitle = generatedTitle?.trim() || currentThreadTitle?.trim() || t("chat.thread.newChat");

  // Sources panel state lives at the Thread level so the right-hand panel and
  // each `group-source` button share a single source of truth. The selection
  // carries the snapshot of sources/images for the group that opened it,
  // letting the panel render even if the original message parts change.
  const [selection, setSelection] = useState<SourcesPanelSelection | null>(null);

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
    [selection, open, toggle, close],
  );

  return (
    <SourcesPanelProvider value={panelContextValue}>
      <ThreadView
        agent={agent}
        onBack={onBack}
        models={models}
        selectedModelId={selectedModelId}
        onModelChange={onModelChange}
        chatMode={chatMode}
        onChatModeChange={onChatModeChange}
        showModelSelector={showModelSelector}
        hasMessages={hasMessages}
        displayName={displayName}
        conversationTitle={conversationTitle}
        selection={selection}
        onPanelClose={close}
      />
    </SourcesPanelProvider>
  );
};

interface ThreadViewProps {
  agent: Agent | PublishedAgent;
  onBack?: () => void;
  models: readonly ModelOption[];
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  showModelSelector: boolean;
  hasMessages: boolean;
  displayName: string;
  conversationTitle: string;
  selection: SourcesPanelSelection | null;
  onPanelClose: () => void;
}

const ThreadView: FC<ThreadViewProps> = ({
  agent,
  onBack,
  models,
  selectedModelId,
  onModelChange,
  chatMode,
  onChatModeChange,
  showModelSelector,
  hasMessages,
  displayName,
  conversationTitle,
  selection,
  onPanelClose,
}) => {
  const { t } = useTranslation();

  return (
    <ThreadPrimitive.Root className="flex h-full flex-row bg-background">
      <div className="flex h-full min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b px-3 py-2">
          {onBack && (
            <Button variant="ghost" size="icon" onClick={onBack}>
              <ArrowLeft className="size-4" />
            </Button>
          )}
          <div className="flex flex-col">
            <span className="text-sm font-medium text-foreground">
              {hasMessages ? conversationTitle : displayName}
            </span>
            {hasMessages && (
              <span className="text-xs text-muted-foreground">{t("chat.thread.conversation")}</span>
            )}
          </div>
        </header>

        <ThreadPrimitive.Viewport className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-auto py-6 max-w-4xl mx-auto w-full px-8">
          {hasMessages ? (
            <ThreadMessages agent={agent} />
          ) : (
            <ThreadWelcomeContent agent={agent} />
          )}
        </ThreadPrimitive.Viewport>

        <ThreadPrimitive.ViewportFooter className="sticky bottom-0 mx-auto flex w-full max-w-4xl flex-col gap-4 pb-8 px-8">
          <ThreadScrollToBottom />
          <Composer
            models={models}
            selectedModelId={selectedModelId}
            onModelChange={onModelChange}
            chatMode={chatMode}
            onChatModeChange={onChatModeChange}
            showModelSelector={showModelSelector}
          />
        </ThreadPrimitive.ViewportFooter>
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

interface ThreadWelcomeContentProps {
  agent: Agent | PublishedAgent;
}

const ThreadWelcomeContent: FC<ThreadWelcomeContentProps> = ({ agent }) => {
  const aui = useAui();
  const { t } = useTranslation();
  const Icon = getAgentIcon(agent);
  const displayName = agent.display_name || agent.name;
  const sampleQuestions = (agent.example_questions || []).slice(0, 4);

  const handleSampleQuestionClick = useCallback(
    (question: string) => {
      aui.composer().setText(question);
    },
    [aui],
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
              {t("chat.thread.helloAgent", { agent: displayName })}
            </h1>
            <p className="mx-auto mt-3 max-w-xl text-pretty text-sm leading-relaxed text-muted-foreground">
              {agent.greeting_message || agent.description}
            </p>
          </div>

          {sampleQuestions.length > 0 && (
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
          )}
        </div>
      </div>
    </div>
  );
};

const ThreadMessages: FC<{ agent: Agent | PublishedAgent }> = ({ agent }) => {
  return (
    <ThreadPrimitive.Messages>
      {({ message }) => {
        if (message.role === "user") return <UserMessage />;
        return <AssistantMessage agent={agent} />;
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
  const isComplete = useAuiState(
    (s) => s.message.status?.type === "complete",
  );

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

const AssistantMessage: FC<{ agent: Agent | PublishedAgent }> = ({ agent }) => {
  const { t } = useTranslation();
  // Reserves space for the action bar; `-mb` compensates so the action bar's
  // hover-revealed position does not shift the message spacing. For pt-[n]
  // use `-mb-[n + 6]` and `min-h-[n + 6]` to preserve the compensation.
  const ACTION_BAR_PT = "pt-1 pb-1 mb-1";
  const ACTION_BAR_HEIGHT = `-mb-7.5 min-h-7.5 ${ACTION_BAR_PT}`;

  const AgentIcon = getAgentIcon(agent);
  const agentName = agent.display_name || agent.name;

  const agentRunTime = getAgentRunTime();
  const nl2a = useAuiState(
    (s) =>
      (
        s.message.metadata?.custom as
          | { nl2a?: Nl2aMessage }
          | undefined
      )?.nl2a,
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
          {agentRunTime && (
            <span
              data-slot="aui_assistant-message-run-time"
              className="text-xs text-muted-foreground"
              aria-label={t("chat.thread.runStartedAt", { time: agentRunTime })}
              title={t("chat.thread.runStartedAt", { time: agentRunTime })}
            >
              {agentRunTime}
            </span>
          )}
        </header>
        <MessagePrimitive.GroupedParts
          groupBy={(part) => {
            // Sub-agent parts first enter a shared calls summary, then a
            // run-specific group. Distinct `runId` suffixes keep repeated or
            // parallel invocations as separate cards inside the summary.
            // Each card retains the same reasoning/tool grouping as the main
            // message.
            const meta = (part as { metadata?: { subagentId?: number | string; runId?: string } })
              .metadata;
            const subagentId = meta?.subagentId;
            const runId = meta?.runId;
            const chainPath: (`group-${string}`)[] =
              part.type === "reasoning"
                ? ["group-chainOfThought", "group-reasoning"]
                : part.type === "tool-call"
                  ? ["group-chainOfThought", "group-tool"]
                  : part.type === "source"
                    ? ["group-source"]
                    : ["group-default"];
            if (subagentId !== undefined) {
              const groupKey =
                `group-subagent-${subagentId}-${runId ?? "unknown"}` as const;
              return ["group-subagent-calls", groupKey, ...chainPath] as (
                `group-${string}`
              )[];
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
              // `GroupPart` always carries `indices`; the runtime check
              // above narrows the union so this cast is safe.
              const groupPart = part as unknown as {
                type: string;
                indices: readonly number[];
                status: { type: string };
              };
              return renderSubAgentGroup(groupPart, children);
            }
            switch (part.type) {
              case "group-chainOfThought":
                return <div data-slot="aui_chain-of-thought">{children}</div>;
              case "group-tool":
                return (
                  <ToolGroupRoot variant="ghost">
                    <ToolGroupTrigger
                      count={part.indices.length}
                      active={part.status.type === "running"}
                    />
                    <ToolGroupContent>{children}</ToolGroupContent>
                  </ToolGroupRoot>
                );
              case "group-reasoning": {
                const running = part.status.type === "running";
                return (
                  <Reasoning.Root defaultOpen={running} >
                    <GroupReasoningTrigger active={running} />
                    <Reasoning.Content aria-busy={running}>
                      <Reasoning.Text>{children}</Reasoning.Text>
                    </Reasoning.Content>
                  </Reasoning.Root>
                );
              }
              case "group-source":
                return <SourceGroupButton indices={part.indices} />;
              case "group-default":
                return <>{children}</>;
              case "text": {
                const textPart = part as typeof part & { isError?: boolean };
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
              case "reasoning":
                return <Reasoning {...part} /> ;
              case "tool-call":
                return part.toolUI ?? <ToolFallback {...part} />;
              case "indicator":
                return <AssistantWorkingIndicator />;
              case "source":
                if ((part as SourcePartLike).isImage) {
                  return <GlobalSearchImage source={part as SourcePartLike} />;
                }
                return <Sources {...part} />;
              case "data":
                if (part.name === "automation-proposal") {
                  return (
                    <AutomationProposalMessage
                      proposal={part.data as AgentAutomationProposalData}
                    />
                  );
                }
                // The `subagent-boundary` stamp part is the seat of the
                // group's header information. We let the header renderer
                // paint it instead of returning it inside the body, so
                // suppress here when it lands as a leaf of the chain.
                return part.dataRendererUI;
              default:
                return null;
            }
          }}
        </MessagePrimitive.GroupedParts>
        {nl2a?.content.subtype === "local_mcp_recommendation" ? (
          <ToolRecommendations payload={nl2a.content} />
        ) : nl2a?.content.subtype === "agent_draft" ? (
          <AgentDraftCard draft={nl2a.content} />
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
        <BranchPicker />
        <AssistantActionBar />
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

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root
      data-slot="aui_user-message-root"
      data-role="user"
      className="fade-in slide-in-from-bottom-1 animate-in mx-auto grid w-full max-w-(--thread-max-width) auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 duration-150 [&:where(>*)]:col-start-2"
    >
      <div className="col-start-2 flex flex-col gap-2">
        <UserMessageAttachments />

        <div className="aui-user-message-content-wrapper relative self-end inline-block min-w-0">
          <div className="aui-user-message-content peer bg-muted text-foreground rounded-xl px-4 py-2 wrap-break-word empty:hidden">
            <MessagePrimitive.Quote>
              {(quote) => <QuoteBlock {...quote} />}
            </MessagePrimitive.Quote>
            <MessagePrimitive.Parts components={{ Text: DirectiveText }} />
          </div>
          <div className="aui-user-action-bar-wrapper absolute top-1/2 left-0 -translate-x-full -translate-y-1/2 pr-2 peer-empty:hidden">
            <UserActionBar />
          </div>
        </div>
      </div>

      <BranchPicker
        data-slot="aui_user-branch-picker"
        className="col-span-full col-start-1 row-start-3 -mr-1 justify-end"
      />
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
        <TooltipIconButton tooltip={t("chat.thread.edit")} className="aui-user-action-edit">
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
}

/**
 * Renders a single image source as a thumbnail link, matching the
 * `ToolFallback.SearchContent` image cell so the global "检索结果:" block
 * and the per-tool Sources block share the same look for picture_web entries.
 */
const GlobalSearchImage: FC<{ source: SourcePartLike }> = ({ source }) => {
  const imageUrl = source.url || "";
  if (!imageUrl) return null;
  return (
    <a
      href={imageUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="aui-global-search-image block overflow-hidden rounded-md border bg-muted/50"
      title={imageUrl}
    >
      <img
        src={imageUrl}
        alt={imageUrl}
        loading="lazy"
        className="size-20 object-cover"
      />
    </a>
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
  children: ReactNode,
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
  children: ReactNode,
): ReactElement | null => {
  // We can't read s.message.content from inside the children callback
  // because the callback is not a component. Defer to a small inline
  // component so the selector re-runs on each streaming yield.
  return <SubAgentGroupRenderer indices={part.indices}>{children}</SubAgentGroupRenderer>;
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
    data?: { agentName?: string; task?: string; depth?: number; isRunning?: boolean };
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
      if (member?.type === "data" && member.name === "subagent-boundary" && member.data) {
        if (member.data.agentName) agentName = member.data.agentName;
        if (member.data.task) task = member.data.task;
        if (typeof member.data.depth === "number") depth = member.data.depth;
        if (typeof member.data.isRunning === "boolean") isRunning = member.data.isRunning;
        break;
      }
      if (meta?.agentName) agentName = meta.agentName;
      if (meta?.task) task = meta.task;
      if (typeof meta?.depth === "number") depth = meta.depth;
      if (typeof meta?.isRunning === "boolean") isRunning = isRunning || meta.isRunning;
    }
    if (indices.length > 0) {
      const lastMember = content[indices[indices.length - 1]];
      if (lastMember?.metadata && typeof lastMember.metadata.isRunning === "boolean") {
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
    for (const index of indices) {
      const raw = content[index] as SourcePartLike | undefined;
      if (!raw || raw.type !== "source") continue;
      const item: PanelSourceItem = {
        sourceType: raw.sourceType,
        url: raw.url,
        title: raw.title,
        text: raw.text,
        filename: raw.filename,
        downloadUrl: raw.downloadUrl,
        objectName: raw.objectName,
        isImage: raw.isImage,
        citeIndex: raw.citeIndex,
      };
      if (item.isImage) {
        imgs.push(item);
      } else {
        srcs.push(item);
      }
    }
    return { sources: srcs, images: imgs, total: srcs.length + imgs.length };
  }, [content, indices]);

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
    <div className="flex items-center gap-2 pt-3 pb-2">
      <button
        type="button"
        onClick={handleClick}
        aria-expanded={isActive}
        aria-pressed={isActive}
        className="aui-source-group-button inline-flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-accent/50"
      >
        <span aria-hidden className="inline-flex items-center gap-1 text-muted-foreground">
          <FileTextIcon className="size-3.5" />
          {t("chat.thread.searchResults")}
        </span>
        <span className="text-foreground">
          {sources.length > 0 ? t("chat.thread.sourceCount", { count: sources.length }) : ""}
          {sources.length > 0 && images.length > 0 ? ", " : ""}
          {images.length > 0 ? t("chat.thread.imageCount", { count: images.length }) : ""}
        </span>
        {images.length > 0 ? (
          <ImageIcon className="size-3.5 text-muted-foreground" aria-hidden />
        ) : null}
      </button>
    </div>
  );
};
