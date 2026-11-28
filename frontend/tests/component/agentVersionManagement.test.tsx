// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useAuiState } from "@assistant-ui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import AgentVersion from "@/app/agents/agent-version";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import type { ThreadProps } from "@/app/newchat/assistant-ui/thread";
import {
  compareVersions,
  type AgentVersionDetail,
} from "@/services/agentVersionService";

const versions = vi.hoisted(() =>
  [1, 2].map((versionNo) => ({
    version_no: versionNo,
    version_name: `Version ${versionNo}`,
    release_note: "",
    source_type: "",
    source_version_no: 0,
    status: "published",
    create_time: "",
    update_time: "",
  }))
);

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { id: "user", tenantId: "fixture" },
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({
    enableAidpKnowledge: false,
    isDeploymentReady: true,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: { currentAgentId: number }) => number) =>
    selector({ currentAgentId: 42 }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({
    availableLlmModels: [
      {
        id: 11,
        name: "default-model",
        displayName: "Default Model",
        type: "llm",
        connect_status: "available",
      },
      {
        id: 22,
        name: "shared-model",
        displayName: "Shared Model",
        type: "llm",
        connect_status: "available",
      },
    ],
  }),
}));
vi.mock("@/hooks/agent/useAgentVersionList", () => ({
  useAgentVersionList: () => ({
    agentVersionList: versions,
    total: versions.length,
    isLoading: false,
  }),
}));
vi.mock("@/app/agents/versions/agent-version-card", () => ({
  VersionCardItem: ({ version }: { version: (typeof versions)[number] }) => (
    <div>{version.version_name}</div>
  ),
}));
vi.mock("@/services/agentVersionService", () => ({ compareVersions: vi.fn() }));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  remoteChatModelAdapter: { run: vi.fn() },
}));
vi.mock("@/app/newchat/assistant-ui/thread", () => ({
  Thread: function ThreadProbe({
    debugLayout,
    showComposer,
    readOnly,
    welcomeContent,
  }: ThreadProps) {
    const messages = useAuiState((state) => state.thread.messages);
    return (
      <div
        data-testid="shared-conversation-thread"
        data-debug-layout={String(debugLayout)}
        data-show-composer={String(showComposer)}
        data-read-only={String(readOnly)}
      >
        {messages.length === 0 && welcomeContent}
        {messages
          .filter(({ role }) => role === "assistant")
          .flatMap(({ content }) =>
            content.map((part) => (part.type === "text" ? part.text : ""))
          )
          .join("")}
      </div>
    );
  },
}));

it("opens comparison from the drawer and sends a shared question to both version threads", async () => {
  const [left, right] = versions.map((version): AgentVersionDetail => ({
    version,
    agent_id: 42,
    name: "Fixture Agent",
    description: "",
    model_name: "Fixture Model",
    model_ids: [11],
    max_steps: 5,
    tenant_id: "fixture",
    enabled: true,
    provide_run_summary: false,
    tools: [],
  }));
  vi.mocked(compareVersions).mockResolvedValue({
    success: true,
    message: "",
    data: { version_a: left, version_b: right, differences: [] },
  });
  const answers = Promise.withResolvers<void>();
  const followup = Promise.withResolvers<void>();
  vi.mocked(remoteChatModelAdapter.run).mockImplementation(async function* ({
    runConfig,
    messages,
  }) {
    await (messages.length > 1 ? followup : answers).promise;
    yield {
      content: [
        {
          type: "text",
          text: `Answer from ${runConfig.custom?.agentVersionNo}`,
        },
      ],
    };
  });

  const closeDrawer = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AgentVersion
        open
        currentVersionNo={2}
        onClose={closeDrawer}
        onRefreshAgentInfo={async () => null}
      />
    </QueryClientProvider>
  );
  const drawer = screen.getByRole("dialog", { name: "agent.version.manage" });
  expect(drawer).toHaveClass("ant-drawer-section");
  expect(within(drawer).getByText("Version 1")).toBeInTheDocument();
  fireEvent.click(
    within(drawer).getByRole("button", { name: "agent.version.compare" })
  );

  const configurationTab = await screen.findByRole("tab", {
    name: "agent.version.compareBasicTitle",
  });
  const modal = configurationTab.closest<HTMLElement>('[role="dialog"]')!;
  expect(modal).toHaveClass("ant-modal");
  expect(
    within(modal).queryByRole("button", { name: "common.button.close" })
  ).not.toBeInTheDocument();
  expect(configurationTab).toHaveAttribute("aria-selected", "true");
  expect(within(modal).queryByRole("textbox")).not.toBeInTheDocument();
  expect(await within(modal).findByRole("table")).toBeInTheDocument();

  fireEvent.click(
    within(modal).getByRole("tab", { name: "agent.version.compareQaTitle" })
  );
  const [input] = within(modal).getAllByRole("textbox");
  expect(within(modal).getAllByRole("textbox")).toHaveLength(1);
  const comparison = within(modal).getByTestId("compare-results");
  expect(comparison.parentElement).toContainElement(input);
  expect(
    within(comparison).queryByText(/^Version [12]$/)
  ).not.toBeInTheDocument();
  const threads = within(modal).getAllByTestId("shared-conversation-thread");
  expect(threads).toHaveLength(2);
  for (const thread of threads) {
    expect(thread).toHaveAttribute("data-debug-layout", "true");
    expect(thread).toHaveAttribute("data-show-composer", "false");
    expect(thread).toHaveAttribute("data-read-only", "true");
    expect(
      within(thread)
        .getByTestId("agent-debug-welcome")
        .querySelector(".ant-avatar svg")
    ).toBeInTheDocument();
  }
  await waitFor(() => expect(input).toBeEnabled());
  const user = userEvent.setup();
  const modelPicker = within(comparison.parentElement!).getByRole("combobox");
  expect(modelPicker).toHaveTextContent("Default Model");
  await user.click(modelPicker);
  await user.click(await screen.findByText("Shared Model"));
  fireEvent.change(input, { target: { value: "Compare this question" } });
  fireEvent.click(
    within(modal).getByRole("button", { name: "chat.composer.send" })
  );

  await waitFor(() =>
    expect(remoteChatModelAdapter.run).toHaveBeenCalledTimes(2)
  );
  const requests = vi
    .mocked(remoteChatModelAdapter.run)
    .mock.calls.map(([options]) => ({
      version: options.runConfig.custom?.agentVersionNo,
      modelId: options.runConfig.custom?.modelId,
      content: options.messages.at(-1)?.content,
    }));
  expect(requests).toEqual(
    expect.arrayContaining([
      {
        version: 1,
        modelId: "22",
        content: [{ type: "text", text: "Compare this question" }],
      },
      {
        version: 2,
        modelId: "22",
        content: [{ type: "text", text: "Compare this question" }],
      },
    ])
  );
  answers.resolve();
  expect(await within(modal).findByText("Answer from 1")).toBeInTheDocument();
  expect(await within(modal).findByText("Answer from 2")).toBeInTheDocument();

  await waitFor(() =>
    expect(
      within(modal).queryByRole("button", {
        name: "chat.composer.stopGenerating",
      })
    ).not.toBeInTheDocument()
  );
  fireEvent.change(input, { target: { value: "Follow-up question" } });
  fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
  await waitFor(() =>
    expect(remoteChatModelAdapter.run).toHaveBeenCalledTimes(4)
  );
  const stop = within(modal).getByRole("button", {
    name: "chat.composer.stopGenerating",
  });
  fireEvent.click(stop);
  const followupRequests = vi
    .mocked(remoteChatModelAdapter.run)
    .mock.calls.slice(2);
  expect(
    followupRequests.every(([options]) => options.abortSignal.aborted)
  ).toBe(true);
  followup.resolve();

  fireEvent.click(within(modal).getByRole("button", { name: "Close" }));
  expect(closeDrawer).not.toHaveBeenCalled();
  expect(
    screen.getByRole("dialog", { name: "agent.version.manage" })
  ).toBeVisible();
});
