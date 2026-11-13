// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { File as NativeFile } from "node:buffer";
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import JSZip from "jszip";
import { beforeEach, expect, test, vi } from "vitest";
import SkillCreateModal from "@/components/skill/SkillCreateModal";

const api = vi.hoisted(() => ({
  create: vi.fn(),
  upload: vi.fn(),
  update: vi.fn(),
  tags: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/common/StandardModal", () => ({
  StandardModal: ({
    children,
    footer,
    open,
  }: {
    children: ReactNode;
    footer: ReactNode;
    open: boolean;
  }) =>
    open ? (
      <div>
        {children}
        {footer}
      </div>
    ) : null,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: "tenant" },
    getAccessibleGroupIds: () => [7],
  }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({
    data: {
      groups: [
        { group_id: 7, group_name: "Allowed group" },
        { group_id: 8, group_name: "Other group" },
      ],
    },
    isLoading: false,
  }),
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({
    data: [{ bucket_key: "default_resource", bucket_id: 1 }],
  }),
  useTagDefinitions: () => ({
    loading: false,
    data: [
      {
        definition_id: 10,
        definition_name: "Topic",
        selection_mode: "multi_select",
        status: "active",
        values: [{ value_id: 20, display_value: "Finance", status: "active" }],
      },
    ],
  }),
}));
vi.mock("@/services/agentConfigService", () => ({
  createSkill: api.create,
  createSkillFromFile: api.upload,
  updateSkillById: api.update,
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: { replaceAssignments: api.tags },
}));
vi.mock("@/const/errorMessageI18n", () => ({
  getTenantResourceLimitMessage: () => null,
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("@/components/skill/SkillCreationFiles", () => ({
  default: () => <div>Draft files</div>,
}));

beforeEach(() => {
  api.create
    .mockReset()
    .mockResolvedValue({ success: true, data: { skill_id: 42 } });
  api.upload
    .mockReset()
    .mockResolvedValue({ success: true, data: { skill_id: 43 } });
  api.update.mockReset().mockResolvedValue({ success: true });
  api.tags.mockReset().mockResolvedValue({});
});
function show() {
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  render(
    <App>
      <SkillCreateModal open onClose={onClose} onSuccess={onSuccess} />
    </App>
  );
  return { onClose, onSuccess };
}
function fill() {
  fireEvent.change(screen.getByLabelText("skillManagement.form.name"), {
    target: { value: "manual-skill" },
  });
  fireEvent.change(screen.getByLabelText("skillManagement.form.description"), {
    target: { value: "Description" },
  });
}

test("preserves a dirty draft when creation-mode switching is cancelled", async () => {
  show();
  fill();
  fireEvent.click(
    screen.getByRole("button", {
      name: /skillCreation.import skillCreation.importHint/,
    })
  );
  await waitFor(() =>
    expect(screen.getByText("skillCreation.discardDraft")).toBeVisible()
  );
  const cancelButtons = screen.getAllByRole("button", {
    name: "common.cancel",
  });
  fireEvent.click(cancelButtons[cancelButtons.length - 1]);
  expect(screen.getByLabelText("skillManagement.form.name")).toHaveValue(
    "manual-skill"
  );
  expect(api.create).not.toHaveBeenCalled();
});

test("validates configuration before progressing and creates only after group confirmation", async () => {
  const { onSuccess } = show();
  fireEvent.click(screen.getByRole("button", { name: "skillCreation.next" }));
  expect(
    await screen.findByText("skillManagement.form.nameRequired")
  ).toBeVisible();
  expect(api.create).not.toHaveBeenCalled();
  fill();
  fireEvent.click(screen.getByRole("button", { name: "skillCreation.next" }));
  await screen.findByRole("button", { name: "skillCreation.previous" });
  expect(screen.getByRole("checkbox", { name: "Allowed group" })).toBeChecked();
  expect(screen.queryByText("Other group")).not.toBeInTheDocument();
  expect(api.create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  expect(api.create).toHaveBeenCalledWith(
    expect.objectContaining({
      name: "manual-skill",
      group_ids: [7],
      ingroup_permission: "READ_ONLY",
      tags: [],
    })
  );
});

test("retries tag configuration against the created skill instead of creating a duplicate", async () => {
  api.tags.mockRejectedValueOnce(new Error("Tag write failed"));
  const { onSuccess } = show();
  fill();
  fireEvent.mouseDown(screen.getByLabelText("skillManagement.form.tags"));
  fireEvent.click(await screen.findByText("Finance"));
  fireEvent.click(screen.getByRole("button", { name: "skillCreation.next" }));
  await screen.findByRole("button", { name: "skillCreation.previous" });
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  expect(await screen.findByText("Tag write failed")).toBeVisible();
  expect(onSuccess).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  expect(api.create).toHaveBeenCalledTimes(1);
  expect(api.tags).toHaveBeenLastCalledWith("skill", "42", { value_ids: [20] });
});

test("parses imports locally and submits the original ZIP only at final confirmation", async () => {
  const { onSuccess } = show();
  const zip = new JSZip();
  zip.file(
    "SKILL.md",
    "---\nname: imported\ndescription: Imported skill\n---\nBody"
  );
  zip.file("asset.png", new Uint8Array([255]));
  const file = new NativeFile(
    [await zip.generateAsync({ type: "uint8array" })],
    "skill.zip"
  ) as unknown as File;
  fireEvent.click(
    screen.getByRole("button", {
      name: /skillCreation.import skillCreation.importHint/,
    })
  );
  fireEvent.change(screen.getByLabelText("skillCreation.uploadFile"), {
    target: { files: [file] },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "skillCreation.parseFile" })
  );
  await waitFor(() =>
    expect(screen.getByLabelText("skillManagement.form.name")).toHaveValue(
      "imported"
    )
  );
  expect(api.upload).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "skillCreation.next" }));
  await screen.findByRole("button", { name: "skillCreation.previous" });
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  expect(api.upload).toHaveBeenCalledWith("imported", file, false);
  expect(api.update).toHaveBeenCalledWith(
    43,
    expect.objectContaining({ group_ids: [7], content: "Body" })
  );
});

test("blocks resubmission when creation succeeds without a usable ID", async () => {
  api.create.mockResolvedValueOnce({ success: true, data: {} });
  show();
  fill();
  fireEvent.click(screen.getByRole("button", { name: "skillCreation.next" }));
  await screen.findByRole("button", { name: "skillCreation.previous" });
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  expect(
    await screen.findByText("skillCreation.missingCreatedId")
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "common.confirm" })).toBeDisabled();
  expect(api.create).toHaveBeenCalledTimes(1);
});
