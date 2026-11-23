// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { expect, test, vi } from "vitest";
import SkillBuildModal from "@/app/agents/components/capability/SkillBuildModal";
import type { MyEditableSkillItem } from "@/types/skillRepository";

const api = vi.hoisted(() => ({ save: vi.fn() }));
const skill = {
  skill_id: 7,
  name: "sample-skill",
  description: "Original description",
  source: "custom",
  tags: [],
  created_by: "owner",
  group_ids: [1, 3],
  ingroup_permission: "READ_ONLY",
  repository_info: [],
} satisfies MyEditableSkillItem;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { id: "owner", tenantId: "tenant" },
    getAccessibleGroupIds: () => [1, 2],
  }),
}));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({ isReady: true, can: () => true }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
  useGroupDetails: () => ({
    groups: [
      { group_id: 1, group_name: "Current group" },
      { group_id: 2, group_name: "Another group" },
    ],
  }),
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
vi.mock("@/app/newchat/assistant-ui/nl2skill-chat-panel", () => ({
  Nl2SkillChatPanel: () => <div>Skill chat</div>,
}));
vi.mock("@/app/agents/components/capability/SkillCodePreview", () => ({
  SkillCodePreview: () => null,
}));
vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: () => null,
}));
vi.mock("@/services/skillService", () => ({
  fetchSkillsList: async () => [],
  submitSkillForm: api.save,
  findSkillByName: () => undefined,
}));
vi.mock("@/services/agentConfigService", () => ({
  fetchSkillById: async () => ({ success: true, data: skill }),
  fetchSkillFiles: async () => [{ name: "SKILL.md", type: "file" }],
  fetchSkillFileContent: async () => ({ content: "# Skill instructions" }),
}));

test("edits a repository skill in the same two steps as creation", async () => {
  render(
    <App>
      <SkillBuildModal
        isOpen
        repositoryLayout
        editingSkill={skill}
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />
    </App>
  );

  const description = await screen.findByLabelText(
    "skillManagement.form.description"
  );
  expect(description).toHaveValue(skill.description);
  expect(screen.getByText("skillCreation.parameters")).toBeInTheDocument();
  expect(screen.getByLabelText("resourceCenter.search")).toBeVisible();
  expect(screen.queryByRole("checkbox", { name: "Current group" })).toBeNull();
  fireEvent.change(description, { target: { value: "Updated description" } });

  fireEvent.click(screen.getByRole("button", { name: "skillCreation.next" }));
  const anotherGroup = await screen.findByRole("checkbox", {
    name: "Another group",
  });
  expect(description).not.toBeVisible();
  expect(screen.getByRole("checkbox", { name: "Current group" })).toBeChecked();
  fireEvent.click(anotherGroup);
  fireEvent.click(
    screen.getByRole("button", { name: "skillCreation.previous" })
  );
  expect(description).toBeVisible();
  expect(description).toHaveValue("Updated description");

  fireEvent.click(screen.getByRole("button", { name: "skillCreation.next" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "skillManagement.mode.saveChanges",
    })
  );
  await waitFor(() => expect(api.save).toHaveBeenCalledOnce());
  const [values, , , , , options] = api.save.mock.calls[0];
  expect(values).toMatchObject({
    name: skill.name,
    description: "Updated description",
    content: "# Skill instructions",
    ingroup_permission: "READ_ONLY",
  });
  expect(values.group_ids).toEqual(expect.arrayContaining([1, 2, 3]));
  expect(options).toMatchObject({ mode: "edit", skillId: skill.skill_id });
});
