// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ReactNode } from "react";
import { McpSpace } from "../../app/[locale]/mcp-space/agent-space";
import AddMcpServiceCommunitySection from "../../app/[locale]/mcp-space/components/add/community/AddMcpServiceCommunitySection";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { fetchCommunityMcpCards } from "@/services/mcpToolsService";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS, McpTransportType } from "@/const/mcpTools";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ locale: "en" }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/en/mcp-space",
}));
vi.mock("@/services/mcpToolsService", () => ({
  fetchCommunityMcpCards: vi.fn(),
  fetchCommunityMcpTagStats: vi.fn(async () => ({ success: true, data: [] })),
}));
vi.mock("@/hooks/mcpTools/useMcpCommunityQuickAdd", () => ({
  useMcpCommunityQuickAdd: () => ({ visible: false, open: vi.fn() }),
}));
vi.mock("../../app/[locale]/mcp-space/my-mcp", () => ({
  PlaceholderBox: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@/components/tag/RepositoryTagFilter", () => ({
  default: () => null,
}));
vi.mock(
  "../../app/[locale]/mcp-space/components/McpToolsSearchFilterBar",
  () => ({
    default: () => null,
  })
);
vi.mock("../../app/[locale]/mcp-space/components/RepositoryMcpCard", () => ({
  default: ({ service }: { service: CommunityMcpCard }) => (
    <p>{service.name}</p>
  ),
}));
vi.mock(
  "../../app/[locale]/mcp-space/components/add/community/McpCommunityCard",
  () => ({
    default: ({ service }: { service: CommunityMcpCard }) => (
      <p>{service.name}</p>
    ),
  })
);

const clients: QueryClient[] = [];
const card = (name: string): CommunityMcpCard => ({
  name,
  description: "MCP service",
  status: "active",
  createdAt: "2026-10-19",
  remotes: [],
  packages: [],
  transportType: McpTransportType.HTTP,
  serverUrl: "https://example.com/mcp",
});
const response = (name: string, total = 70) => ({
  success: true as const,
  data: { items: name ? [card(name)] : [], nextCursor: null, total },
});
function Repository() {
  const browser = useMcpCommunityBrowser(true, 12);
  return (
    <McpSpace
      browser={browser}
      localServices={[]}
      isAdmin={false}
      actions={null}
      onSelect={vi.fn()}
      onInstall={vi.fn()}
      onOffline={vi.fn()}
    />
  );
}
function setup(view: "repository" | "add") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      {view === "repository" ? (
        <Repository />
      ) : (
        <AddMcpServiceCommunitySection active onAdded={vi.fn()} />
      )}
    </QueryClientProvider>
  );
}
function nextPage(view: "repository" | "add") {
  fireEvent.click(
    view === "repository"
      ? screen.getByTitle("2")
      : screen.getByRole("button", { name: "mcpTools.community.nextPage" })
  );
}
const retryButton = () =>
  screen.findByRole("button", { name: "repository.common.retry" });

beforeEach(() => vi.mocked(fetchCommunityMcpCards).mockReset());
afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
});

test.each(["repository", "add"] as const)(
  "%s retries the failed second page and restores cards and pagination",
  async (view) => {
    let resolveRetry!: (value: ReturnType<typeof response>) => void;
    const retry = new Promise<ReturnType<typeof response>>((resolve) => {
      resolveRetry = resolve;
    });
    vi.mocked(fetchCommunityMcpCards)
      .mockResolvedValueOnce(response("First page"))
      .mockRejectedValueOnce(new Error("Network unavailable"))
      .mockImplementationOnce(() => retry);
    setup(view);
    await screen.findByText("First page");
    nextPage(view);
    const button = await retryButton();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "mcpTools.community.requestFailed"
    );
    expect(
      screen.queryByText("mcpTools.repository.empty")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("mcpTools.community.empty")
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("2")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "mcpTools.community.nextPage" })
    ).not.toBeInTheDocument();
    fireEvent.click(button);
    await waitFor(() =>
      expect(fetchCommunityMcpCards).toHaveBeenCalledTimes(3)
    );
    expect(
      screen.queryByRole("button", { name: "repository.common.retry" })
    ).not.toBeInTheDocument();
    expect(fetchCommunityMcpCards).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2 })
    );
    await act(async () => resolveRetry(response("Recovered second page")));
    await screen.findByText("Recovered second page");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    if (view === "repository") {
      expect(screen.getByTitle("2")).toHaveClass("ant-pagination-item-active");
    } else {
      expect(
        screen.getByRole("button", { name: "mcpTools.community.prevPage" })
      ).toBeEnabled();
    }
  }
);

test.each(["repository", "add"] as const)(
  "%s keeps recovery available after repeated failure",
  async (view) => {
    vi.mocked(fetchCommunityMcpCards)
      .mockResolvedValueOnce(response("First page"))
      .mockRejectedValueOnce(new Error("Network unavailable"))
      .mockRejectedValueOnce(new Error("Service unavailable"))
      .mockResolvedValueOnce(response("Recovered page"));
    setup(view);
    await screen.findByText("First page");
    nextPage(view);
    fireEvent.click(await retryButton());
    await waitFor(() =>
      expect(fetchCommunityMcpCards).toHaveBeenCalledTimes(3)
    );
    fireEvent.click(await retryButton());
    await screen.findByText("Recovered page");
    expect(fetchCommunityMcpCards).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2 })
    );
  }
);

test.each(["repository", "add"] as const)(
  "%s recovers initial failure to a successful empty result",
  async (view) => {
    vi.mocked(fetchCommunityMcpCards)
      .mockRejectedValueOnce(new Error("Network unavailable"))
      .mockResolvedValueOnce(response("", 0));
    setup(view);
    fireEvent.click(await retryButton());
    await screen.findByText(
      view === "repository"
        ? "mcpTools.repository.empty"
        : "mcpTools.community.empty"
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchCommunityMcpCards).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1 })
    );
  }
);

test.each(["repository", "add"] as const)(
  "%s shows failed refresh feedback even when cards are cached",
  async (view) => {
    vi.mocked(fetchCommunityMcpCards)
      .mockResolvedValueOnce(response("Cached page"))
      .mockRejectedValueOnce(new Error("Service unavailable"))
      .mockResolvedValueOnce(response("Refreshed page"));
    setup(view);
    await screen.findByText("Cached page");
    await act(async () => {
      await clients[0].refetchQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.communityList,
      });
    });
    const button = await retryButton();
    expect(screen.queryByText("Cached page")).not.toBeInTheDocument();
    expect(screen.queryByTitle("2")).not.toBeInTheDocument();
    fireEvent.click(button);
    await screen.findByText("Refreshed page");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  }
);
