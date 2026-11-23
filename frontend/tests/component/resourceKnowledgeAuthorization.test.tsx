// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, Tabs } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  AuthorizationProvider,
  useAuthorizationContext,
} from "@/components/providers/AuthorizationProvider";
import { ClientLayout } from "../../app/[locale]/layout.client";
import KnowledgeList from "../../app/[locale]/resource-manage/components/resources/KnowledgeList";
import { authEventUtils } from "@/lib/authEvents";

const state = vi.hoisted(() => ({ request: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => {
  const router = { replace: state.replace };
  return { useRouter: () => router, usePathname: () => "/zh/resource-manage" };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/lib/session", () => ({ checkSessionValid: () => true }));
vi.mock("@/services/authService", () => ({
  authService: { getCurrentUserInfo: () => state.request() },
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ isSpeedMode: false }),
}));
vi.mock("@/components/navigation/SideNavigation", () => ({
  SideNavigation: () => null,
}));
vi.mock("@/components/auth/AuthDialogs", () => ({ AuthDialogs: () => null }));
vi.mock("@/components/quota/QuotaWarningMonitor", () => ({
  QuotaWarningMonitor: () => null,
}));
vi.mock("@/components/memory/MemoryEmbeddingMonitor", () => ({
  MemoryEmbeddingMonitor: () => null,
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
}));
vi.mock("@/hooks/knowledge/useKnowledgeList", () => ({
  useKnowledgeList: () => ({ data: [], isLoading: false, refetch: vi.fn() }),
}));
vi.mock("@/hooks/tenant/useTenantList", () => ({
  useTenantList: () => ({ data: { data: [] }, isLoading: false }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));
vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: () => null,
}));
vi.mock(
  "../../app/[locale]/knowledges/components/knowledge/KnowledgeBaseEditModal",
  () => ({ KnowledgeBaseEditModal: () => null })
);
vi.mock(
  "../../app/[locale]/resource-manage/components/resources/QuotaSettingsModal",
  () => ({ QuotaSettingsModal: () => null })
);
vi.mock("@/services/quotaService", () => ({
  default: {
    getQuotaUsage: vi.fn().mockResolvedValue({}),
    listPersonalCapacityUsers: vi
      .fn()
      .mockResolvedValue({ items: [], total: 0 }),
    getPersonalCapacitySummary: vi.fn().mockResolvedValue(null),
    getPersonalDefaultQuota: vi.fn().mockResolvedValue(null),
  },
}));

const clients: QueryClient[] = [];
const response = {
  user: {
    id: "admin",
    email: "admin@example.com",
    role: "ADMIN",
    tenantId: "tenant",
    groupIds: [],
    permissions: ["kb.capacity:read", "kb.capacity:manage"],
    accessibleRoutes: ["/resource-manage"],
  },
};

function Refresh() {
  const { refetch } = useAuthorizationContext();
  return <button onClick={() => void refetch()}>refresh authorization</button>;
}
function ResourceTabs() {
  return (
    <Tabs
      defaultActiveKey="users"
      items={[
        { key: "users", label: "Users", children: <div>Users content</div> },
        {
          key: "knowledge",
          label: "Knowledge",
          children: <KnowledgeList tenantId="tenant" />,
        },
      ]}
    />
  );
}
function renderResources() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <App>
        <AuthorizationProvider>
          <Refresh />
          <ClientLayout>
            <ResourceTabs />
          </ClientLayout>
        </AuthorizationProvider>
      </App>
    </QueryClientProvider>
  );
}
beforeEach(() => {
  state.request.mockReset().mockResolvedValue(response);
  state.replace.mockClear();
});
afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
});

it("opens shared and personal knowledge without reinitializing authorization or resetting tabs", async () => {
  renderResources();
  fireEvent.click(await screen.findByRole("tab", { name: "Knowledge" }));
  await waitFor(() =>
    expect(screen.getByRole("tab", { name: "Knowledge" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
  );
  expect(state.request).toHaveBeenCalledTimes(1);
  expect(screen.getByText("quota.quotaManagement")).toBeVisible();
  fireEvent.click(
    screen.getByText("tenantResources.personalCapacity.personalKnowledgeBases")
  );
  await waitFor(() => expect(state.request).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("tab", { name: "Knowledge" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
});

it.each(["success", "failure"])(
  "keeps selected tab and mounted content through background authorization %s",
  async (outcome) => {
    renderResources();
    fireEvent.click(await screen.findByRole("tab", { name: "Knowledge" }));
    const tab = screen.getByRole("tab", { name: "Knowledge" });
    let resolve!: (value: typeof response) => void;
    let reject!: (reason: Error) => void;
    state.request.mockImplementationOnce(
      () =>
        new Promise((res, rej) => {
          resolve = res;
          reject = rej;
        })
    );
    fireEvent.click(screen.getByText("refresh authorization"));
    await waitFor(() => expect(state.request).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("tab", { name: "Knowledge" })).toBe(tab);
    expect(tab).toHaveAttribute("aria-selected", "true");
    await act(async () => {
      if (outcome === "success") resolve(response);
      else reject(new Error("Background authorization unavailable"));
    });
    expect(screen.getByRole("tab", { name: "Knowledge" })).toBe(tab);
    expect(tab).toHaveAttribute("aria-selected", "true");
    act(() => authEventUtils.emitLogout());
    expect(screen.queryByRole("tab", { name: "Knowledge" })).toBeNull();
  }
);
