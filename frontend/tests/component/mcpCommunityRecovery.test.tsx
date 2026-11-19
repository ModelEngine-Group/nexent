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
import { McpSpace } from "@/app/resource-space/components/mcp/agent-space";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { fetchCommunityMcpCards } from "@/services/mcpToolsService";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS, McpTransportType } from "@/const/mcpTools";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/hooks/auth/useUserDisplayName", () => ({
  useUserDisplayName: () => (_cas: unknown, fallback: string) => fallback,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ locale: "en" }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/en/resource-space",
}));
vi.mock("@/services/mcpToolsService", () => ({
  fetchCommunityMcpCards: vi.fn(),
  fetchCommunityMcpTagStats: vi.fn(async () => ({ success: true, data: [] })),
}));
vi.mock("@/hooks/mcpTools/useMcpCommunityQuickAdd", () => ({
  useMcpCommunityQuickAdd: () => ({ visible: false, open: vi.fn() }),
}));
vi.mock("@/app/resource-space/components/mcp/my-mcp", () => ({
  PlaceholderBox: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@/components/tag/RepositoryTagFilter", () => ({
  default: () => null,
}));
vi.mock(
  "@/app/resource-space/components/mcp/components/McpToolsSearchFilterBar",
  () => ({
    default: () => null,
  })
);
vi.mock("@/app/resource-space/components/mcp/components/RepositoryMcpCard", () => ({
  default: ({ service }: { service: CommunityMcpCard }) => (
    <p>{service.name}</p>
  ),
}));

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
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <Repository />
    </QueryClientProvider>
  );
}
function nextPage() {
  fireEvent.click(screen.getByTitle("2"));
}
const retryButton = () =>
  screen.findByRole("button", { name: "repository.common.retry" });

beforeEach(() => vi.mocked(fetchCommunityMcpCards).mockReset());
afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
});

test("retries the failed second page and restores cards and pagination", async () => {
  let resolveRetry!: (value: ReturnType<typeof response>) => void;
  const retry = new Promise<ReturnType<typeof response>>((resolve) => {
    resolveRetry = resolve;
  });
  vi.mocked(fetchCommunityMcpCards)
    .mockResolvedValueOnce(response("First page"))
    .mockRejectedValueOnce(new Error("Network unavailable"))
    .mockImplementationOnce(() => retry);
  setup();
  await screen.findByText("First page");
  nextPage();
  const button = await retryButton();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "mcpTools.community.requestFailed"
  );
  expect(
    screen.queryByText("mcpTools.repository.empty")
  ).not.toBeInTheDocument();
  expect(screen.queryByTitle("2")).not.toBeInTheDocument();
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
  expect(screen.getByTitle("2")).toHaveClass("ant-pagination-item-active");
});

test("keeps recovery available after repeated failure", async () => {
  vi.mocked(fetchCommunityMcpCards)
    .mockResolvedValueOnce(response("First page"))
    .mockRejectedValueOnce(new Error("Network unavailable"))
    .mockRejectedValueOnce(new Error("Service unavailable"))
    .mockResolvedValueOnce(response("Recovered page"));
  setup();
  await screen.findByText("First page");
  nextPage();
  fireEvent.click(await retryButton());
  await waitFor(() =>
    expect(fetchCommunityMcpCards).toHaveBeenCalledTimes(3)
  );
  fireEvent.click(await retryButton());
  await screen.findByText("Recovered page");
  expect(fetchCommunityMcpCards).toHaveBeenLastCalledWith(
    expect.objectContaining({ page: 2 })
  );
});

test("recovers initial failure to a successful empty result", async () => {
  vi.mocked(fetchCommunityMcpCards)
    .mockRejectedValueOnce(new Error("Network unavailable"))
    .mockResolvedValueOnce(response("", 0));
  setup();
  fireEvent.click(await retryButton());
  await screen.findByText("mcpTools.repository.empty");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(fetchCommunityMcpCards).toHaveBeenLastCalledWith(
    expect.objectContaining({ page: 1 })
  );
});

test("shows failed refresh feedback even when cards are cached", async () => {
  vi.mocked(fetchCommunityMcpCards)
    .mockResolvedValueOnce(response("Cached page"))
    .mockRejectedValueOnce(new Error("Service unavailable"))
    .mockResolvedValueOnce(response("Refreshed page"));
  setup();
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
});
