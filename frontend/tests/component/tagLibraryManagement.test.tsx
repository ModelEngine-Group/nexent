// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { render } from "./resourceDrawerTestUtils";
import TagList from "../../app/[locale]/resource-manage/components/resources/TagList";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { tagManagementApi } from "@/services/tagManagementService";
import type { TagDefinition, TagLibrary } from "@/types/tagManagement";

const auth = vi.hoisted(() => ({
  user: { tenantId: "tenant-a", role: "ADMIN" },
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => auth,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn(),
    listDefinitions: vi.fn(),
    createDefinition: vi.fn(),
    updateDefinitionStatus: vi.fn(),
    moveDefinitionToTop: vi.fn(),
    deleteDefinition: vi.fn(),
    updateValue: vi.fn(),
  },
}));

const libraries = [
  { bucket_id: 1, bucket_key: "default_resource", bucket_name: "Resources" },
  { bucket_id: 2, bucket_key: "knowledge_content", bucket_name: "Content" },
] as TagLibrary[];
const definition: TagDefinition = {
  definition_id: 10,
  bucket_id: 1,
  definition_key: "department",
  definition_name: "Department",
  selection_mode: "multi_select",
  sort_order: 1,
  status: "active",
  active_value_count: 1,
  value_capacity: 1000,
  values: [
    {
      value_id: 20,
      display_value: "Finance",
      normalized_value: "finance",
      sort_order: 1,
      status: "active",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  auth.user = { tenantId: "tenant-a", role: "ADMIN" };
  vi.mocked(tagManagementApi.listLibraries).mockResolvedValue(libraries);
  vi.mocked(tagManagementApi.listDefinitions).mockImplementation(async (id) =>
    id === 1
      ? [definition]
      : [
          {
            ...definition,
            definition_id: 11,
            bucket_id: 2,
            definition_name: "Content label",
          },
        ]
  );
});

function showTags(tenantId = "tenant-a") {
  return render(
    <App>
      <TagList tenantId={tenantId} />
    </App>
  );
}

it("renders the management table inline, searches and switches libraries", async () => {
  const user = userEvent.setup();
  showTags();
  expect(await screen.findByText("Department")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const search = screen.getByPlaceholderText("tagManagement.form.searchTags");
  await user.type(search, "missing");
  expect(screen.queryByText("Department")).not.toBeInTheDocument();
  await user.clear(search);
  expect(screen.getByText("Department")).toBeInTheDocument();
  await user.click(
    screen.getByRole("combobox", { name: "tagManagement.library" })
  );
  await user.click(
    screen.getByText("tagManagement.libraries.knowledge_content", {
      selector: ".ant-select-item-option-content",
    })
  );
  expect(await screen.findByText("Content label")).toBeInTheDocument();
  expect(screen.queryByText("Department")).not.toBeInTheDocument();
  expect(tagManagementApi.listDefinitions).toHaveBeenLastCalledWith(2);
});

it("creates a no-value tag and refreshes the inline list", async () => {
  const user = userEvent.setup();
  showTags();
  await user.click(
    await screen.findByRole("button", {
      name: "tagManagement.action.addDefinition",
    })
  );
  const dialog = screen.getByRole("dialog");
  await user.type(
    within(dialog).getByRole("textbox", {
      name: "tagManagement.form.definitionName",
    }),
    "Reviewed"
  );
  await user.click(within(dialog).getByRole("switch"));
  vi.mocked(tagManagementApi.listDefinitions).mockResolvedValue([
    definition,
    {
      ...definition,
      definition_id: 12,
      definition_name: "Reviewed",
      definition_key: "reviewed",
      selection_mode: "no_value",
      values: [],
    },
  ]);
  expect(
    within(dialog).getByRole("button", { name: "common.cancel" })
  ).toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: "tagManagement.action.confirm" })
  );
  await waitFor(() =>
    expect(tagManagementApi.createDefinition).toHaveBeenCalledWith(1, {
      definition_name: "Reviewed",
      selection_mode: "no_value",
      initial_values: [],
    })
  );
  expect(await screen.findByText("Reviewed")).toBeInTheDocument();
});

it("preserves expanded value editing and status actions", async () => {
  const user = userEvent.setup();
  showTags();
  await screen.findByText("Department");
  await user.click(screen.getByRole("button", { name: "Expand row" }));
  const valueRow = screen.getByText("Finance").closest("tr")!;
  await user.click(
    within(valueRow).getByRole("button", { name: "tagManagement.action.edit" })
  );
  const dialog = screen.getByRole("dialog");
  const input = within(dialog).getByRole("textbox", {
    name: "tagManagement.form.displayValue",
  });
  await user.clear(input);
  await user.type(input, "Operations");
  expect(
    within(dialog).getByRole("button", { name: "common.cancel" })
  ).toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: "tagManagement.action.confirm" })
  );
  await waitFor(() =>
    expect(tagManagementApi.updateValue).toHaveBeenCalledWith(1, 10, 20, {
      display_value: "Operations",
    })
  );
  await user.click(
    screen.getAllByRole("button", { name: "tagManagement.action.disable" })[0]
  );
  await waitFor(() =>
    expect(tagManagementApi.updateDefinitionStatus).toHaveBeenCalledWith(
      1,
      10,
      { status: "disabled" }
    )
  );
});

it("keeps a readonly list usable and blocks management actions", async () => {
  auth.user.role = "USER";
  showTags();
  await screen.findByText("Department");
  expect(
    screen.queryByRole("button", { name: "tagManagement.action.addDefinition" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "tagManagement.action.edit" })
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "tagManagement.action.delete" })
  ).toBeDisabled();
  expect(tagManagementApi.createDefinition).not.toHaveBeenCalled();
});

it("never requests or displays the signed-in tenant's labels for another selected tenant", () => {
  showTags("tenant-b");
  expect(
    screen.getByText("tagManagement.currentTenantOnly")
  ).toBeInTheDocument();
  expect(tagManagementApi.listLibraries).not.toHaveBeenCalled();
  expect(tagManagementApi.listDefinitions).not.toHaveBeenCalled();
});

it("shows library failures with retry and handles an empty library list", async () => {
  vi.mocked(tagManagementApi.listLibraries).mockRejectedValueOnce(
    new Error("Library unavailable")
  );
  showTags();
  expect(await screen.findByText("Library unavailable")).toBeInTheDocument();
  vi.mocked(tagManagementApi.listLibraries).mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  expect(
    await screen.findByText("tagManagement.empty.noLibraries")
  ).toBeInTheDocument();
  expect(tagManagementApi.listDefinitions).not.toHaveBeenCalled();
});

it("reports definition failures and retries without showing a false empty success", async () => {
  vi.mocked(tagManagementApi.listDefinitions).mockRejectedValueOnce(
    new Error("Definitions unavailable")
  );
  showTags();
  expect(
    await screen.findByText("Definitions unavailable")
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  expect(await screen.findByText("Department")).toBeInTheDocument();
});

it("keeps existing modal callers working and resets nested forms on close", async () => {
  const user = userEvent.setup();
  const props = {
    open: true,
    onClose: vi.fn(),
    bucketId: 1,
    bucketName: "Resources",
    canManage: true,
  };
  const view = render(
    <App>
      <TagDefinitionManagementModal {...props} />
    </App>
  );
  await screen.findByText("Department");
  await user.click(
    screen.getByRole("button", { name: "tagManagement.action.addDefinition" })
  );
  expect(screen.getAllByRole("dialog")).toHaveLength(2);
  view.rerender(
    <App>
      <TagDefinitionManagementModal {...props} open={false} />
    </App>
  );
  view.rerender(
    <App>
      <TagDefinitionManagementModal {...props} />
    </App>
  );
  await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
  expect(await screen.findByText("Department")).toBeInTheDocument();
});
