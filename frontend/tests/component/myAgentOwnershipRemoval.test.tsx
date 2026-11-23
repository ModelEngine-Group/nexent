// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MyAgent } from "@/app/agent-space/my-agent";
import { useAgentList } from "@/hooks/agent/useAgentList";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ locale: "zh" }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { id: "me", tenantId: "tenant" } }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));
vi.mock("@/hooks/agent/useAgentList", () => {
  const agents = [
    { agent_id: 1, name: "Created", permission: "EDIT" },
    { agent_id: 2, name: "Shared", permission: "READ_ONLY" },
  ];
  return {
    useAgentList: vi.fn(() => ({
      agents,
      pagination: { total: 15 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })),
  };
});
vi.mock("@/hooks/agentRepository/useAgentRepositoryListings", () => ({
  AGENTS_LIST_QUERY_KEY: [],
  invalidateAgentRepositoryCaches: vi.fn(),
  useCreateAgentRepositoryListing: () => ({}),
  useUpdateAgentRepositoryStatus: () => ({}),
  useAgentRepositoryListings: () => ({}),
  useMyEditableAgents: () => ({}),
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({}),
  useTagDefinitions: () => ({}),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({ tools: [] }),
}));
vi.mock("@/hooks/agent/useSkillList", () => ({
  useSkillList: () => ({ skills: [] }),
}));
vi.mock("@/hooks/agent/useAgentVersionDetail", () => ({
  useAgentVersionDetail: () => ({}),
}));
vi.mock("@/components/agent/CreateAgentModal", () => ({ default: () => null }));
vi.mock("@/components/agent/agent-detail", () => ({ AgentDetail: () => null }));
vi.mock("@/components/tag/TagFilterPopover", () => ({ default: () => null }));
vi.mock("@/app/agent-space/components/AgentUsageGuideModal", () => ({
  AgentUsageGuideModal: () => null,
}));
vi.mock("@/app/agent-space/components/MineApplyListingModal", () => ({
  MineApplyListingModal: () => null,
}));
vi.mock("@/app/agent-space/components/MineReviewStatusModal", () => ({
  MineReviewStatusModal: () => null,
}));
vi.mock("@/app/agent-space/components/MyAgentCard", () => ({
  MyAgentCard: ({ agent }: { agent: { name: string } }) => (
    <div>{agent.name}</div>
  ),
}));

describe("mine ownership controls", () => {
  it("lists all accessible agents and preserves search and pagination without creator filters", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App>
          <MyAgent active />
        </App>
      </QueryClientProvider>
    );
    for (const key of ["all", "created", "others"]) {
      expect(
        screen.queryByRole("button", {
          name: new RegExp(`repository.mine.filter.${key}`),
        })
      ).toBeNull();
    }
    expect(screen.getByText("Created")).toBeVisible();
    expect(screen.getByText("Shared")).toBeVisible();
    fireEvent.click(screen.getByTitle("2"));
    await waitFor(() =>
      expect(vi.mocked(useAgentList).mock.lastCall?.[0]).toMatchObject({
        page: 2,
        pageSize: 11,
      })
    );
    fireEvent.change(
      screen.getByPlaceholderText("agentRepository.mine.searchPlaceholder"),
      { target: { value: "Find" } }
    );
    await waitFor(() =>
      expect(vi.mocked(useAgentList).mock.lastCall?.[0]).toMatchObject({
        page: 1,
        search: "Find",
      })
    );
    for (const [filters] of vi.mocked(useAgentList).mock.calls) {
      expect(filters).not.toHaveProperty("createdBy");
      expect(filters).not.toHaveProperty("createdByNot");
    }
  });
});
