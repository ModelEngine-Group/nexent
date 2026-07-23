"use client";

import { useCallback, useEffect, useMemo } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type AssistantRuntime,
} from "@assistant-ui/react";

import { Thread } from "../../app/[locale]/newchat/assistant-ui/thread";
import { compositeAttachmentAdapter } from "../../app/[locale]/newchat/adapter/attachment-adapter";
import { RemoteConversationHistoryAdapter } from "../../app/[locale]/newchat/adapter/conversation-thread-list-adapter";
import { remoteChatModelAdapter } from "../../app/[locale]/newchat/adapter/remote-chat-model-adapter";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";
import type { Nl2AgentSessionSummary } from "@/services/nl2agentService";
import { Nl2AgentWorkflowProvider } from "./Nl2AgentWorkflowContext";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import type { Nl2AgentContinuationRequest } from "./Nl2AgentWorkflowContext";
import { Button } from "antd";

interface Nl2AgentEmbeddedChatProps {
  session: Nl2AgentSessionSummary;
  onSessionResumed: (session: Nl2AgentSessionSummary) => void;
  onStateChanged: () => void;
}

const builderAgent: Agent = {
  id: "nl2agent",
  name: "nl2agent",
  display_name: "智能体生成助手",
  description: "通过对话生成智能体配置",
  model: "",
  max_step: 20,
  provide_run_summary: false,
  tools: [],
  greeting_message: "请描述你希望创建的智能体。",
  example_questions: [],
};

const EmbeddedRuntimeContent = ({
  runtime,
  session,
  onSessionResumed,
  onStateChanged,
}: Nl2AgentEmbeddedChatProps & { runtime: AssistantRuntime }) => {
  useEffect(() => {
    runtime.thread.composer.setRunConfig({
      custom: {
        agentId: String(session.nl2agent_agent_id),
        draftAgentId: session.draft_agent_id,
        threadId: String(session.conversation_id),
      },
    });
  }, [runtime, session]);

  const continueConversation = useCallback(
    async (request: Nl2AgentContinuationRequest) => {
      await runtime.thread.append({
        role: "user",
        content: [{ type: "text", text: request.context.displayText }],
        metadata: {
          custom: { nl2agentActionContext: request.context },
        },
        runConfig: runtime.thread.composer.getState().runConfig,
      });
    },
    [runtime]
  );

  return (
    <Nl2AgentWorkflowProvider
      enabled
      editable={session.status === "active"}
      scopeKey={`${session.conversation_id}:${session.draft_agent_id}`}
      agentId={session.draft_agent_id}
      onContinue={continueConversation}
      onSessionResumed={onSessionResumed}
      onStateChanged={onStateChanged}
    >
      <div className="flex h-full min-h-0 flex-col">
        <CompletedSessionBanner />
        <div className="min-h-0 flex-1">
          <Thread agent={builderAgent} onBack={() => {}} embedded />
        </div>
      </div>
    </Nl2AgentWorkflowProvider>
  );
};

const CompletedSessionBanner = () => {
  const workflow = useNl2AgentWorkflow();
  if (workflow.editable) return null;
  return (
    <div className="flex items-center justify-between gap-2 border-b bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
      <span>生成已完成，聊天记录为只读。</span>
      <Button
        size="small"
        loading={workflow.resuming}
        onClick={() => void workflow.resumeSession()}
      >
        继续调整
      </Button>
    </div>
  );
};

export const Nl2AgentEmbeddedChat = (props: Nl2AgentEmbeddedChatProps) => {
  const history = useMemo(
    () =>
      new RemoteConversationHistoryAdapter(() =>
        String(props.session.conversation_id)
      ),
    [props.session.conversation_id]
  );
  const runtime = useLocalRuntime(remoteChatModelAdapter, {
    adapters: { attachments: compositeAttachmentAdapter, history },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <EmbeddedRuntimeContent runtime={runtime} {...props} />
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};
