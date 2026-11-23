// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, test, vi } from "vitest";
import McpServiceDetailModal from "@/app/resource-space/mcp/components/McpServiceDetailModal";
import McpDeploymentCards from "@/app/resource-space/mcp/components/shared/McpDeploymentCards";
import AddMcpServiceLocalSection from "@/app/resource-space/mcp/components/add/local/AddMcpServiceLocalSection";
import {
  McpDeploymentType,
  McpHealthStatus,
  McpServiceStatus,
  McpSource,
  McpTransportType,
} from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";

const actions = vi.hoisted(() => ({
  loadTools: vi.fn(),
  refreshTools: vi.fn(),
  runHealthCheck: vi.fn(),
  save: vi.fn(),
  setDraft: vi.fn(),
  remove: vi.fn(),
  testConnection: vi.fn(),
  submit: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/mcpTools/useMcpServiceDetail", () => ({
  useMcpServiceDetail: ({
    selectedService,
  }: {
    selectedService: McpServiceItem;
  }) => ({
    ...actions,
    draft: selectedService,
    toolsState: {
      tools: Array.from({ length: 6 }, (_, index) => ({
        name: `tool-${index + 1}`,
        description: `Description ${index + 1}`,
      })),
    },
  }),
}));
vi.mock("@/hooks/mcpTools/useMcpAddLocal", () => ({
  useMcpAddLocal: () => ({ submit: actions.submit, submitting: false }),
}));
vi.mock("@/services/mcpToolsService", () => ({
  testMcpConnectionService: actions.testConnection,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { tenantId: "tenant-1" } }),
}));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({ isReady: true, can: () => true }),
}));
vi.mock("@/components/permission/Can", () => ({ Can: () => null }));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
}));
vi.mock("@/hooks/mcp/useMcpServerList", () => ({
  useMcpServerList: () => ({ enableUploadImage: false }),
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({}),
  useTagDefinitions: () => ({ refresh: vi.fn() }),
}));
vi.mock("@/components/tag/ResourceTagChips", () => ({ default: () => null }));
vi.mock("@/components/tag/ResourceTagAssignmentModal", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/TagDefinitionManagementModal", () => ({
  default: () => null,
}));
vi.mock("@/components/mcp/McpContainerLogsModal", () => ({
  McpContainerLogOutput: () => null,
  default: () => null,
}));

const savedService: McpServiceItem = {
  mcpId: 7,
  name: "test-mcp",
  description: "Example description",
  source: McpSource.LOCAL,
  enabled: McpServiceStatus.ENABLED,
  updatedAt: "",
  createTime: "",
  tags: [],
  transportType: McpTransportType.HTTP,
  serverUrl: "https://example.test/mcp",
  authorizationToken: "test-private-token",
  customHeaders: { "X-Test": "test-private-header" },
  tools: [],
  healthStatus: McpHealthStatus.UNCHECKED,
  permission: "EDIT",
};

function openDetail(overrides: Partial<McpServiceItem> = {}) {
  const onClose = vi.fn();
  render(
    <App>
      <McpServiceDetailModal
        selectedService={{ ...savedService, ...overrides }}
        onClose={onClose}
      />
    </App>
  );
  return onClose;
}

beforeEach(() => {
  vi.clearAllMocks();
  actions.save.mockResolvedValue(true);
});

function openCreate() {
  render(
    <App>
      <AddMcpServiceLocalSection active onAdded={vi.fn()} onClose={vi.fn()} />
    </App>
  );
  return screen.getByRole("button", {
    name: "mcpTools.editDetail.testConnection",
  });
}

test("puts connection testing in the edit footer in place of delete", () => {
  openDetail();
  const testButton = screen.getByRole("button", {
    name: "mcpTools.editDetail.testConnection",
  });
  expect(testButton.closest(".ant-drawer-footer")).toContainElement(
    screen.getByRole("button", { name: "mcpTools.addModal.next" })
  );
  expect(screen.queryByRole("button", { name: "common.delete" })).toBeNull();
});

test.each([
  [true, "mcpTools.registry.quickAddPicker.connectionSuccess"],
  [false, "mcpTools.add.error.connectionFailed"],
])(
  "tests an unsaved remote MCP and reports result %s",
  async (success, toast) => {
    actions.testConnection.mockResolvedValue({
      success: true,
      data: { success },
    });
    const testButton = openCreate();
    expect(testButton).toBeDisabled();
    expect(testButton.parentElement).toContainElement(
      screen.getByRole("button", { name: "mcpTools.addModal.next" })
    );
    fireEvent.change(screen.getByLabelText("mcpTools.addModal.serverUrl"), {
      target: { value: "https://example.test/mcp" },
    });
    fireEvent.change(screen.getByLabelText("mcpTools.addModal.customHeaders"), {
      target: { value: '{"X-Test":"sample"}' },
    });
    fireEvent.change(
      screen.getByLabelText("mcpTools.addModal.bearerTokenOptional"),
      {
        target: { value: "sample-token" },
      }
    );
    fireEvent.click(testButton);
    expect(await screen.findByText(toast)).toBeInTheDocument();
    expect(actions.testConnection).toHaveBeenCalledExactlyOnceWith({
      server_url: "https://example.test/mcp",
      authorization_token: "sample-token",
      custom_headers: { "X-Test": "sample" },
    });
    expect(actions.submit).not.toHaveBeenCalled();
  }
);

test("rejects malformed headers before making a connection request", async () => {
  const testButton = openCreate();
  fireEvent.change(screen.getByLabelText("mcpTools.addModal.serverUrl"), {
    target: { value: "https://example.test/mcp" },
  });
  fireEvent.change(screen.getByLabelText("mcpTools.addModal.customHeaders"), {
    target: { value: "[]" },
  });
  fireEvent.click(testButton);
  expect(
    await screen.findByText("mcpConfig.message.invalidCustomHeaders")
  ).toBeInTheDocument();
  expect(actions.testConnection).not.toHaveBeenCalled();
});

test("the edit drawer follows the creation field order with the saved type selected", () => {
  openDetail();
  const fields = [
    screen.getByRole("radiogroup"),
    screen.getByLabelText("mcpTools.addModal.name"),
    screen.getByLabelText("common.description"),
    screen.getByLabelText("mcpTools.addModal.serverUrl"),
    screen.getByLabelText("mcpTools.editDetail.headerName"),
    screen.getByLabelText("mcpTools.addModal.bearerTokenOptional"),
    screen.getByRole("button", { name: "tagManagement.action.editTags" }),
  ];
  fields.slice(1).forEach((field, index) => {
    expect(
      fields[index].compareDocumentPosition(field) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });
  const options = screen.getAllByRole("radio");
  expect(options).toHaveLength(3);
  expect(options[0]).toHaveAccessibleName(/mcpConfig.addServer.title/);
  expect(options[1]).toHaveAccessibleName(/mcpTools.addModal.mode.container/);
  expect(options[2]).toHaveAccessibleName(/mcpTools.addModal.mode.api/);
  expect(options[0]).toBeChecked();
  expect(options[1]).not.toBeChecked();
  options.forEach((option) => expect(option).toBeDisabled());
});

test("the creation options can change the deployment type", () => {
  const onChange = vi.fn();
  render(
    <McpDeploymentCards
      ariaLabel="MCP configuration"
      value={McpDeploymentType.REMOTE_LINK}
      onChange={onChange}
    />
  );
  const option = screen.getByRole("radio", {
    name: /mcpTools.addModal.mode.api/,
  });
  expect(option).toBeEnabled();
  fireEvent.click(option);
  expect(onChange).toHaveBeenCalledWith(McpDeploymentType.API);
});

test("shows the protocol, collapsed tool results and a credential-free JSON preview", async () => {
  openDetail();
  expect(screen.getByLabelText("mcpTools.editDetail.protocol")).toHaveValue(
    "Streamable HTTP"
  );
  expect(actions.loadTools).toHaveBeenCalled();
  expect(screen.getByText("tool-4")).toBeInTheDocument();
  expect(screen.queryByText("tool-5")).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "mcpTools.editDetail.showMoreTools" })
  );
  expect(screen.getByText("tool-6")).toBeInTheDocument();

  const preview = screen.getByText(/"remotes"/);
  expect(preview).toHaveTextContent(savedService.serverUrl);
  expect(preview).not.toHaveTextContent("test-private");
});

test.each([true, false])(
  "refreshes tools after a connection test only if it succeeds (%s)",
  async (healthy) => {
    actions.runHealthCheck.mockResolvedValue(healthy);
    openDetail();
    fireEvent.click(
      screen.getByRole("button", { name: "mcpTools.editDetail.testConnection" })
    );
    await waitFor(() => expect(actions.runHealthCheck).toHaveBeenCalledOnce());
    expect(actions.refreshTools).toHaveBeenCalledTimes(healthy ? 1 : 0);
  }
);

test("saves header edits through the permissions step and cannot test unsaved credentials", async () => {
  const onClose = openDetail();
  fireEvent.change(screen.getByLabelText("mcpTools.editDetail.headerValue"), {
    target: { value: "edited-header" },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "mcpTools.editDetail.testConnection" })
    ).toBeDisabled()
  );
  fireEvent.click(
    screen.getByRole("button", { name: "mcpTools.addModal.next" })
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "mcpTools.detail.save" })
  );
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(actions.save).toHaveBeenCalledWith(
    expect.objectContaining({
      customHeaders: { "X-Test": "edited-header" },
      authorizationToken: savedService.authorizationToken,
    })
  );
});

test("a read-only service has no delete action and cannot edit or test its configuration", () => {
  openDetail({ permission: "READ_ONLY" });
  expect(
    screen.getByLabelText("mcpTools.editDetail.headerValue")
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "mcpTools.editDetail.testConnection" })
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "common.delete" })
  ).not.toBeInTheDocument();
});

test("rejects duplicate header names regardless of case", async () => {
  openDetail();
  fireEvent.click(
    screen.getByRole("button", { name: "mcpTools.editDetail.addHeader" })
  );
  fireEvent.change(
    screen.getAllByLabelText("mcpTools.editDetail.headerName")[1],
    {
      target: { value: "x-test" },
    }
  );
  fireEvent.click(
    screen.getByRole("button", { name: "mcpTools.addModal.next" })
  );
  expect(
    await screen.findByText("mcpTools.editDetail.duplicateHeader")
  ).toBeInTheDocument();
  expect(actions.save).not.toHaveBeenCalled();
});
