// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import type { ComponentProps } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { MyMcp } from "@/components/repository/mcp/my-mcp";
import {
  FILTER_ALL,
  McpHealthStatus,
  McpServiceStatus,
  McpSource,
  McpTransportType,
} from "@/const/mcpTools";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ locale: "en" }),
  usePathname: () => "/en/resource-space",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({}),
  useTagDefinitions: () => ({}),
}));
vi.mock("@/hooks/auth/useUserDisplayName", () => ({
  useUserDisplayName: () => (_cas: unknown, fallback: string) => fallback,
}));
vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

const local: McpServiceItem = {
  mcpId: 7,
  name: "Local MCP",
  description: "",
  source: McpSource.LOCAL,
  enabled: McpServiceStatus.DISABLED,
  updatedAt: "",
  createTime: "",
  tags: [],
  transportType: McpTransportType.HTTP,
  serverUrl: "",
  tools: [],
  healthStatus: McpHealthStatus.UNCHECKED,
  permission: "EDIT",
};

const shared: McpServiceItem = {
  ...local,
  mcpId: 8,
  name: "Shared MCP",
  permission: "READ_ONLY",
  groupIds: "group-1",
};

const published: CommunityMcpCard = {
  communityId: 7,
  name: "Published MCP",
  description: "",
  status: "active",
  createdAt: "",
  remotes: [],
  packages: [],
  transportType: McpTransportType.HTTP,
  serverUrl: "",
};

function renderMine() {
  const queryClient = new QueryClient();
  const services = [local, shared];
  const items = [published];
  const filters = {
    search: "",
    transport: FILTER_ALL,
    tag: FILTER_ALL,
  } as const;
  const localList: ComponentProps<typeof MyMcp>["localList"] = {
    services,
    filteredServices: services,
    tagStats: [],
    filters: { ...filters, source: FILTER_ALL },
    updateFilter: vi.fn(),
    loading: false,
    refetch: vi.fn(),
  };
  const myPublished: ComponentProps<typeof MyMcp>["myPublished"] = {
    items,
    filteredItems: items,
    tagStats: [],
    filters,
    updateFilter: vi.fn(),
    search: "",
    setSearch: vi.fn(),
    loading: false,
    refetch: vi.fn(),
  };
  render(
    <QueryClientProvider client={queryClient}>
      <App>
        <RepositoryPresentationContext.Provider
          value={{
            layout: "cards",
            resourceType: "mcp",
            query: new URLSearchParams(),
          }}
        >
          <MyMcp
            localList={localList}
            myPublished={myPublished}
            actions={null}
            reviewDeepLink={null}
            onReviewDeepLinkConsumed={vi.fn()}
            onAdd={vi.fn()}
            onEditLocal={vi.fn()}
            onEditCommunity={vi.fn()}
            onToggled={vi.fn()}
          />
        </RepositoryPresentationContext.Provider>
      </App>
    </QueryClientProvider>
  );
  return {
    localRefetch: localList.refetch,
    publishedRefetch: myPublished.refetch,
  };
}

beforeEach(() => vi.mocked(fetchWithAuth).mockReset());

async function submitSelectedPage() {
  fireEvent.click(
    screen.getByRole("button", { name: "mcpTools.mine.batchActions" })
  );
  expect(screen.getByRole("checkbox", { name: shared.name })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "resourceCenter.selectPage" })
  );
  fireEvent.click(
    screen.getByRole("button", { name: "resourceCenter.deleteSelected (2)" })
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "common.confirm" })
  );
}

test("submits one mixed MCP batch and retains only failed selections", async () => {
  vi.mocked(fetchWithAuth).mockResolvedValueOnce(
    Response.json({
      status: "success",
      data: [
        { kind: "community", id: 7, success: true },
        { kind: "local", id: 7, success: false, message: "Permission denied" },
      ],
    })
  );
  const { localRefetch, publishedRefetch } = renderMine();
  await submitSelectedPage();
  expect(await screen.findByText("Permission denied")).toBeInTheDocument();
  expect(fetchWithAuth).toHaveBeenCalledTimes(1);
  expect(fetchWithAuth).toHaveBeenCalledWith(
    API_ENDPOINTS.mcpTools.batchDelete,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: [
          { kind: "local", id: 7 },
          { kind: "community", id: 7 },
        ],
      }),
    }
  );
  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: local.name })).toBeChecked()
  );
  expect(
    screen.getByRole("checkbox", { name: published.name })
  ).not.toBeChecked();
  expect(localRefetch).toHaveBeenCalledTimes(1);
  expect(publishedRefetch).toHaveBeenCalledTimes(1);
});

test("keeps both selections available for retry when the batch request fails", async () => {
  vi.mocked(fetchWithAuth).mockRejectedValueOnce(
    new Error("Network unavailable")
  );
  const { localRefetch, publishedRefetch } = renderMine();
  await submitSelectedPage();

  expect(await screen.findByText("Network unavailable")).toBeInTheDocument();
  expect(fetchWithAuth).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("checkbox", { name: local.name })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: published.name })).toBeChecked();
  expect(
    screen.getByRole("button", { name: "resourceCenter.deleteSelected (2)" })
  ).toBeEnabled();
  expect(localRefetch).not.toHaveBeenCalled();
  expect(publishedRefetch).not.toHaveBeenCalled();
});
