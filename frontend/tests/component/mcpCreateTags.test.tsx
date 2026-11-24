// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { McpDeploymentType, McpTransportType } from "@/const/mcpTools";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import type { LocalAddMcpDraft } from "@/types/mcpTools";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  createContainer: vi.fn(),
  list: vi.fn(),
  assign: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
}));

vi.mock("antd", () => ({
  App: {
    useApp: () => ({
      message: { success: vi.fn(), warning: mocks.warning, error: mocks.error },
    }),
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { tenantId: "tenant-1" } }),
}));
vi.mock("@/hooks/mcp/useMcpServerList", () => ({
  MCP_SERVERS_QUERY_KEY: ["mcp-servers"],
}));
vi.mock("@/services/mcpToolsService", () => ({
  addMcpToolService: mocks.create,
  addContainerMcpToolServiceStream: mocks.createContainer,
  parseContainerMcpConfigJson: () => ({}),
}));
vi.mock("@/services/mcpService", () => ({
  getMcpServerList: mocks.list,
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: { replaceAssignments: mocks.assign },
}));
vi.mock("@/hooks/mcpTools/useContainerPortAvailability", () => ({
  checkContainerPortAvailable: async () => true,
}));
vi.mock("@/hooks/mcpTools/useRefreshToolListWithToast", () => ({
  refreshToolListWithToast: async () => undefined,
}));

const draft: LocalAddMcpDraft = {
  name: "Charts",
  serverUrl: "https://example.com/mcp",
  transportType: McpTransportType.URL,
  deploymentType: McpDeploymentType.REMOTE_LINK,
  containerConfigJson: "",
  tags: [],
};

const created = {
  mcp_id: 17,
  service_name: draft.name,
  mcp_url: draft.serverUrl,
};

beforeEach(() => {
  vi.resetAllMocks();
  mocks.create.mockResolvedValue(undefined);
  mocks.list.mockResolvedValue({ success: true, data: [created] });
  mocks.assign.mockResolvedValue(undefined);
});

async function submit(tagIds: number[], configuration = draft) {
  const onSuccess = vi.fn();
  const { result } = renderHook(() => useMcpAddLocal({ onSuccess }));
  await act(async () => {
    await result.current.submit(configuration, tagIds);
  });
  expect(onSuccess).toHaveBeenCalledOnce();
}

test("saves selected values against the created remote service", async () => {
  await submit([9, 11]);
  expect(mocks.list).toHaveBeenCalledWith("tenant-1");
  expect(mocks.assign).toHaveBeenCalledWith("mcp_service", "17", {
    value_ids: [9, 11],
  });
});

test("creates an untagged service without looking up tag assignments", async () => {
  await submit([]);
  expect(mocks.create).toHaveBeenCalledOnce();
  expect(mocks.list).not.toHaveBeenCalled();
  expect(mocks.assign).not.toHaveBeenCalled();
});

test("uses the container identity when assigning tags after deployment", async () => {
  mocks.createContainer.mockResolvedValue({
    service_name: "deployed-charts",
    container_id: "container-1",
  });
  mocks.list.mockResolvedValue({
    success: true,
    data: [
      {
        ...created,
        service_name: "deployed-charts",
        container_id: "container-1",
      },
      { ...created, mcp_id: 18, service_name: "deployed-charts" },
    ],
  });
  await submit([9], {
    ...draft,
    deploymentType: McpDeploymentType.CONTAINER,
    containerPort: 3001,
  });
  expect(mocks.assign).toHaveBeenCalledExactlyOnceWith("mcp_service", "17", {
    value_ids: [9],
  });
});

test("reports a tag write failure without repeating the MCP creation", async () => {
  mocks.assign.mockRejectedValue(new Error("Tag is inactive"));
  await submit([9]);
  expect(mocks.create).toHaveBeenCalledOnce();
  expect(mocks.warning).toHaveBeenCalledWith(
    "mcpTools.add.warning.tagAssignmentFailed"
  );
  expect(mocks.error).not.toHaveBeenCalled();
});
