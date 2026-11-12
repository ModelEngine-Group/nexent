// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Nl2AgentFlowProvider } from "@/contexts/nl2AgentFlow";
import { RequirementClarificationCard } from "@/app/newchat/ui/requirement-clarification-card";
import { SuggestedResourceInstallationCard } from "@/app/newchat/ui/suggested-resource-installation-card";
import { InstalledResourceBindingCard } from "@/app/newchat/ui/installed-resource-binding-card";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { initializeTestI18n } from "./i18n";

const doubles = vi.hoisted(() => ({
  append: vi.fn(),
  idle: vi.fn(async () => true),
  replace: vi.fn(() => true),
}));
vi.mock("@assistant-ui/react", async (original) => ({
  ...(await original<object>()),
  useAui: () => ({
    thread: () => ({
      append: doubles.append,
      composer: () => ({ getState: () => ({ runConfig: {} }) }),
    }),
  }),
  useAuiState: () => false,
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({
    availableTools: [],
    isFetching: false,
    isError: false,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (select: (state: unknown) => unknown) =>
    select({
      currentAgentId: 42,
      editedAgent: null,
      waitForIdle: doubles.idle,
      replaceServerSnapshot: doubles.replace,
    }),
}));
vi.mock("@/services/agentConfigService", async (original) => ({
  ...(await original<object>()),
  searchAgentInfo: vi.fn(async () => ({
    success: true,
    data: { tools: [], skills: [] },
  })),
}));
beforeEach(() => doubles.append.mockClear());

const variants = ["zh", "en"].flatMap((locale) =>
  [
    "requirement_clarification",
    "suggested_resource_installation",
    "installed_resource_binding",
  ].map((subtype) => ({ locale, subtype }))
);
it.each(variants)(
  "$locale $subtype real card submission agrees with historical display",
  async ({ locale, subtype }) => {
    await initializeTestI18n(locale);
    const isChinese = locale === "zh";
    const expected =
      subtype === "requirement_clarification"
        ? isChinese
          ? "已提交需求信息"
          : "Requirements submitted"
        : subtype === "suggested_resource_installation"
          ? isChinese
            ? "已完成资源安装选择"
            : "Resource installation completed"
          : isChinese
            ? "已完成资源选择"
            : "Resource selection completed";
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <App>
          <Nl2AgentFlowProvider>
            {subtype === "requirement_clarification" ? (
              <RequirementClarificationCard
                payload={{
                  subtype,
                  agent_id: 42,
                  questions: [
                    {
                      question_id: "goal",
                      title: "Goal",
                      question_type: "text",
                      required: true,
                      options: [],
                      allow_other: false,
                      other_input_expanded: false,
                    },
                  ],
                }}
              />
            ) : subtype === "suggested_resource_installation" ? (
              <SuggestedResourceInstallationCard
                payload={{ subtype, agent_id: 42, resources: [] }}
              />
            ) : (
              <InstalledResourceBindingCard
                payload={{
                  subtype: "installed_resource_binding",
                  agent_id: 42,
                  resources: [],
                }}
              />
            )}
          </Nl2AgentFlowProvider>
        </App>
      </QueryClientProvider>
    );
    if (subtype === "requirement_clarification")
      fireEvent.change(screen.getByRole("textbox", { name: "Goal" }), {
        target: { value: "Preserve this answer" },
      });
    const label =
      subtype === "requirement_clarification"
        ? isChinese
          ? "提交"
          : "Submit"
        : isChinese
          ? "跳过"
          : "Skip";
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(doubles.append).toHaveBeenCalledOnce());
    const live = doubles.append.mock.calls[0][0];
    expect(live.content).toEqual([{ type: "text", text: expected }]);
    const action = live.metadata.custom.nl2agentCardAction;
    const restored = await new RemoteConversationHistoryAdapter(
      () => "91",
      async () => ({ remoteId: "91", externalId: "91" }),
      async () => ({
        conversation_id: 91,
        create_time: 0,
        message: [
          { role: "user", message_id: 11, message: JSON.stringify(action) },
        ],
      })
    ).load();
    expect(restored.messages[0].message.content).toEqual(live.content);
    expect(
      restored.messages[0].message.metadata?.custom?.nl2agentCardAction
    ).toEqual(action);
    client.clear();
  }
);
