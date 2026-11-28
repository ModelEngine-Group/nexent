// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import zh from "@/public/locales/zh/common.json";
import AddMcpServiceLocalSection from "@/app/mcp-space/components/add/local/AddMcpServiceLocalSection";
import { addMcpToolService } from "@/services/mcpToolsService";

const services = vi.hoisted(() => ({
  addMcpToolService: vi.fn(),
  addContainerMcpToolServiceStream: vi.fn(),
  parseContainerMcpConfigJson: vi.fn(),
  refreshToolListWithToast: vi.fn(),
  useGroupList: vi.fn(),
}));
vi.mock("@/services/mcpToolsService", () => services);
vi.mock("@/services/mcpService", () => ({ uploadMcpImageStream: vi.fn() }));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: "tenant-1", email: "creator@example.com" },
  }),
}));
vi.mock("@/components/permission/Can", () => ({
  Can: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/mcp/McpContainerLogsModal", () => ({
  default: () => null,
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: services.useGroupList,
}));
vi.mock("@/hooks/mcpTools/useRefreshToolListWithToast", () => ({
  refreshToolListWithToast: services.refreshToolListWithToast,
}));
services.useGroupList.mockReturnValue({ data: { groups: [] } });
services.refreshToolListWithToast.mockResolvedValue(undefined);

beforeEach(async () => {
  services.addMcpToolService.mockReset();
  services.addMcpToolService.mockResolvedValue({ success: true, mcpId: 9 });
  await i18n.use(initReactI18next).init({
    lng: "zh",
    keySeparator: false,
    resources: { zh: { common: zh } },
    defaultNS: "common",
  });
});

const t = (key: string) => i18n.t(key);

function setup() {
  const onAdded = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <App>
        <AddMcpServiceLocalSection active onAdded={onAdded} />
      </App>
    </QueryClientProvider>
  );
  return onAdded;
}

function fillRemoteLinkForm() {
  fireEvent.change(
    screen.getByPlaceholderText(t("mcpConfig.addServer.namePlaceholder")),
    { target: { value: "ssl-svc" } }
  );
  fireEvent.change(
    screen.getByPlaceholderText(t("mcpConfig.addServer.urlPlaceholder")),
    {
      target: { value: "https://remote.example/mcp" },
    }
  );
}

it.each([true, false])(
  "submits the SSL verification choice %s from the remote-link form",
  async (verify) => {
    const onAdded = setup();
    fillRemoteLinkForm();
    const checkbox = screen.getByRole("checkbox", {
      name: t("mcpConfig.addServer.sslVerify"),
    });
    // The remote-link tab enables certificate verification by default.
    expect((checkbox as HTMLInputElement).checked).toBe(true);
    if (!verify) fireEvent.click(checkbox);

    fireEvent.click(
      screen.getByRole("button", { name: t("mcpTools.addModal.saveAndAdd") })
    );

    await waitFor(() => expect(addMcpToolService).toHaveBeenCalledTimes(1));
    expect(addMcpToolService).toHaveBeenCalledWith(
      expect.objectContaining({
        server_url: "https://remote.example/mcp",
        ssl_verify: verify,
      })
    );
    await waitFor(() => expect(onAdded).toHaveBeenCalledWith("ssl-svc", 9));
  }
);
