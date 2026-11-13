// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, test, vi } from "vitest";
import SkillChatEditor from "@/components/skill/SkillChatEditor";
import { buildEditedSkillFiles } from "@/lib/skillChatDraft";
import {
  buildSkillSavePayload,
  initialSkillCreationDraft,
} from "@/lib/skillChatDraft";

const api = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
  fetch: vi.fn(),
  list: vi.fn(),
  tags: vi.fn(),
  allowed: true,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: "t" },
    hasPermission: () => api.allowed,
    getAccessibleGroupIds: () => [7],
  }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({
    data: {
      groups: [
        { group_id: 7, group_name: "Allowed" },
        { group_id: 8, group_name: "Other" },
      ],
    },
    isLoading: false,
  }),
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({
    data: [{ bucket_key: "default_resource", bucket_id: 1 }],
    loading: false,
  }),
  useTagDefinitions: () => ({
    data: [
      {
        definition_id: 10,
        definition_name: "Topic",
        status: "active",
        selection_mode: "single_select",
        values: [
          { value_id: 20, display_value: "Finance", status: "active" },
          { value_id: 21, display_value: "Analysis", status: "active" },
        ],
      },
    ],
    loading: false,
  }),
}));
vi.mock("@/services/agentConfigService", () => ({
  createSkill: api.create,
  updateSkillById: api.update,
  fetchSkillById: api.fetch,
}));
vi.mock("@/services/skillRepositoryService", () => ({
  fetchMyEditableSkills: api.list,
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: { replaceAssignments: api.tags },
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("@/components/skill/SkillCreationFiles", () => ({
  default: ({
    files,
    disabled,
    onChange,
  }: {
    files: { path: string; content: string }[];
    disabled: boolean;
    onChange: (files: { path: string; content: string }[]) => void;
  }) => (
    <button
      disabled={disabled}
      onClick={() =>
        onChange(
          files.map((file) =>
            file.path === "SKILL.md"
              ? { ...file, content: "Edited instructions" }
              : file
          )
        )
      }
    >
      Edit file
    </button>
  ),
}));
vi.mock("@/components/skill/SkillGroupSelection", () => ({
  default: ({
    groups,
    onChange,
    disabled,
  }: {
    groups: { group_id: number; group_name: string }[];
    onChange?: (ids: number[]) => void;
    disabled: boolean;
  }) => (
    <div>
      {groups.map((group) => (
        <button
          key={group.group_id}
          disabled={disabled}
          onClick={() => onChange?.([group.group_id])}
        >
          {group.group_name}
        </button>
      ))}
    </div>
  ),
}));

const payload = {
  name: "workspace-summary",
  description: "Summarize workspace",
  source: "custom",
  tags: ["Finance", "Analysis"],
  content: "# Instructions",
  files: [{ path: "references/a.txt", content: "Reference" }],
};
beforeEach(() => {
  sessionStorage.clear();
  api.allowed = true;
  api.create
    .mockReset()
    .mockResolvedValue({ success: true, data: { skill_id: 42 } });
  api.update.mockReset().mockResolvedValue({ success: true });
  api.fetch
    .mockReset()
    .mockResolvedValue({ success: true, data: { skill_id: 42 } });
  api.list
    .mockReset()
    .mockResolvedValue({ items: [], pagination: { total_pages: 1 } });
  api.tags.mockReset().mockResolvedValue({});
});
function show(
  overrides: Partial<React.ComponentProps<typeof SkillChatEditor>> = {}
) {
  const props = {
    scopeKey: "t:u:thread-a",
    payload,
    rawFiles: {},
    running: false,
    open: true,
    onClose: vi.fn(),
    onNew: vi.fn(),
    onDraftChange: vi.fn(),
    onSaved: vi.fn(),
    ...overrides,
  };
  const result = render(
    <App>
      <SkillChatEditor {...props} />
    </App>
  );
  return { ...result, props };
}
async function confirm() {
  const button = screen.getByRole("button", { name: "common.confirm" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
}
test("serializes edited metadata and supplementary files for the next generation", () => {
  const edited = {
    ...payload,
    name: 'name: with "quotes"',
    description: "First line\nSecond line",
  };
  expect(
    buildSkillSavePayload({
      ...initialSkillCreationDraft,
      complete: true,
      files: buildEditedSkillFiles(edited),
    })
  ).toEqual(edited);
});
test("confirms a new skill with actual edited files, accessible groups and canonical tags", async () => {
  const { props } = show();
  fireEvent.click(await screen.findByRole("button", { name: "Edit file" }));
  expect(props.onDraftChange).toHaveBeenCalledWith(
    expect.objectContaining({
      content: "Edited instructions",
      files: payload.files,
    })
  );
  await confirm();
  await waitFor(() => expect(props.onSaved).toHaveBeenCalled());
  expect(api.create).toHaveBeenCalledWith(
    expect.objectContaining({
      name: payload.name,
      content: "Edited instructions",
      group_ids: [7],
      ingroup_permission: "READ_ONLY",
      tags: [],
      files: payload.files,
    })
  );
  expect(api.tags).toHaveBeenCalledWith("skill", "42", { value_ids: [20] });
});
test("updates an already generated saved skill while preserving its ACL and tag assignments", async () => {
  api.list.mockResolvedValue({
    items: [
      {
        skill_id: 99,
        name: payload.name,
        group_ids: [9],
        ingroup_permission: "PRIVATE",
      },
    ],
    pagination: { total_pages: 1 },
  });
  show();
  await confirm();
  await waitFor(() => expect(api.update).toHaveBeenCalled());
  expect(api.create).not.toHaveBeenCalled();
  expect(api.update.mock.calls[0][0]).toBe(99);
  expect(api.update.mock.calls[0][1]).not.toHaveProperty("group_ids");
  expect(api.tags).not.toHaveBeenCalled();
});
test("retries a failed tag write using the newly created ID instead of creating another skill", async () => {
  api.tags.mockRejectedValueOnce(new Error("Tag write failed"));
  const { props } = show();
  await confirm();
  expect(await screen.findByText("Tag write failed")).toBeVisible();
  expect(props.onSaved).not.toHaveBeenCalled();
  await confirm();
  await waitFor(() => expect(props.onSaved).toHaveBeenCalled());
  expect(api.create).toHaveBeenCalledTimes(1);
  expect(api.update).toHaveBeenCalledWith(42, expect.anything());
  expect(api.tags).toHaveBeenCalledTimes(2);
});
test("keeps failed save edits and requires a successful existing-resource lookup before saving", async () => {
  api.list.mockRejectedValueOnce(new Error("Network"));
  show();
  expect(await screen.findByText("skillChat.lookupFailed")).toBeVisible();
  expect(screen.getByRole("button", { name: "common.confirm" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "repository.common.retry" })
  );
  api.create.mockResolvedValueOnce({ success: false, message: "Save failed" });
  fireEvent.change(screen.getByLabelText("skillManagement.form.description"), {
    target: { value: "Manual description" },
  });
  await confirm();
  expect(await screen.findByText("Save failed")).toBeVisible();
  expect(screen.getByLabelText("skillManagement.form.description")).toHaveValue(
    "Manual description"
  );
});
test("restores local edits for the same conversation and never restores them into another scope", async () => {
  const first = show();
  fireEvent.change(screen.getByLabelText("skillManagement.form.description"), {
    target: { value: "Local edit" },
  });
  first.unmount();
  const second = show();
  await waitFor(() =>
    expect(
      screen.getByLabelText("skillManagement.form.description")
    ).toHaveValue("Local edit")
  );
  expect(second.props.onDraftChange).toHaveBeenCalledWith(
    expect.objectContaining({ description: "Local edit" })
  );
  second.unmount();
  show({ scopeKey: "t:u:thread-b" });
  expect(screen.getByLabelText("skillManagement.form.description")).toHaveValue(
    payload.description
  );
});
test("does not save incomplete generation, missing required fields or a forbidden creation", async () => {
  const result = show({ running: true });
  expect(screen.getByRole("button", { name: "common.confirm" })).toBeDisabled();
  result.unmount();
  const next = show();
  fireEvent.change(screen.getByLabelText("skillManagement.form.name"), {
    target: { value: " " },
  });
  await confirm();
  expect(
    await screen.findByText("skillManagement.form.nameRequired")
  ).toBeVisible();
  expect(api.create).not.toHaveBeenCalled();
  next.unmount();
  api.allowed = false;
  show();
  expect(screen.getByRole("button", { name: "common.confirm" })).toBeDisabled();
});
test("switches to user groups and exposes only accessible groups", async () => {
  show();
  fireEvent.click(screen.getByText("skillCreation.groups"));
  expect(screen.getByRole("button", { name: "Allowed" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Other" })
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Allowed" }));
  await confirm();
  await waitFor(() =>
    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({ group_ids: [7] })
    )
  );
});
