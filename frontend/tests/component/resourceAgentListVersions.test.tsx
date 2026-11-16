// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import AgentList from "@/app/resource-manage/components/resources/AgentList";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { fetchAgentVersionList } from "@/services/agentVersionService";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/agent/useAgentList", () => ({ useAgentList: vi.fn() }));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { roles: ["ADMIN"] } }),
}));
vi.mock("@/services/agentVersionService", () => ({
  fetchAgentVersionList: vi.fn(),
}));
vi.mock("@/services/agentConfigService", () => ({
  deleteAgent: vi.fn(),
  searchAgentInfo: vi.fn(),
}));
vi.mock("@/components/common/ExpandEditModal", () => ({ default: () => null }));
vi.mock("@/components/agent/ManageOfficialAgentsModal", () => ({
  default: () => null,
}));

it("keeps the current label without eager history requests and loads history when opened", async () => {
  vi.mocked(useAgentList).mockReturnValue({
    agents: [
      {
        id: "7",
        name: "agent",
        display_name: "Agent",
        description: "description",
        is_published: true,
        current_version_no: 3,
        version_label: "Release three",
        group_ids: [],
        model_names: ["LLM"],
        is_available: true,
      },
    ],
    isLoading: false,
    refetch: vi.fn(),
  } as never);
  vi.mocked(fetchAgentVersionList).mockResolvedValue({
    success: true,
    message: "",
    data: {
      total: 2,
      items: [
        { version_no: 3, version_name: "Release three" },
        { version_no: 1, version_name: "Earlier release" },
      ],
    },
  } as never);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <App>
        <AgentList tenantId="a" />
      </App>
    </QueryClientProvider>
  );
  expect(screen.getByText("Release three")).toBeVisible();
  expect(fetchAgentVersionList).not.toHaveBeenCalled();
  expect(useAgentList).toHaveBeenCalledWith("a", true);
  const select = screen.getByText("Release three").closest(".ant-select");
  expect(select).not.toBeNull();
  fireEvent.mouseDown(select!.querySelector("input")!);
  await waitFor(() =>
    expect(fetchAgentVersionList).toHaveBeenCalledExactlyOnceWith(7, "a")
  );
  await waitFor(() =>
    expect(screen.getByText("Earlier release")).toBeVisible()
  );
  view.unmount();
  client.clear();
});
