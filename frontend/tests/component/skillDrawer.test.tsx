// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { render, changePageSize } from "./resourceDrawerTestUtils";
import { SkillDrawer } from "@/components/resource-picker/SkillDrawer";
import type { Skill, SkillGroup } from "@/types/agentConfig";
import { tagManagementApi } from "@/services/tagManagementService";
import type { TagAssignment } from "@/types/tagManagement";

vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn(async () => []),
    listDefinitions: vi.fn(async () => []),
    getAssignments: vi.fn(async () => ({ assignments: [] })),
    filterResourceIds: vi.fn(async () => ({ matched_resource_ids: [] })),
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));
vi.mock("@/hooks/agent/useSkillList", () => ({
  useSkillList: () => ({ groupedSkills: [], invalidate: vi.fn() }),
}));
vi.mock("@/services/agentConfigService", () => ({
  fetchSkillInstances: vi.fn(),
}));
vi.mock("@/components/skill-config/SkillConfigModal", () => ({
  default: () => <div>Skill configuration modal</div>,
}));

const skill = {
  skill_id: 1,
  name: "Alpha skill",
  description: "Details",
  config_schemas: [],
} as unknown as Skill;
const groups: SkillGroup[] = [
  { key: "team", label: "Team skills", skills: [skill] },
];

describe("SkillDrawer external selection", () => {
  it("uses the chosen page size for skill rows and preserves draft selection", async () => {
    const skills = Array.from({ length: 21 }, (_, index) => ({
      ...skill,
      skill_id: index + 1,
      name: `Skill ${index + 1}`,
    }));
    render(
      <SkillDrawer
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        selectedSkills={[]}
        groups={[{ ...groups[0], skills }]}
      />
    );
    expect(screen.getAllByRole("option")).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    fireEvent.click(screen.getByRole("option", { name: "Skill 21" }));
    await changePageSize(20);
    expect(screen.getAllByRole("option")).toHaveLength(20);
    expect(screen.getByRole("option", { name: "Skill 1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    expect(screen.getByRole("option", { name: "Skill 21" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("loads unified assignments even when the catalog has no flat tags", async () => {
    vi.mocked(tagManagementApi.getAssignments).mockResolvedValueOnce({
      assignments: [
        {
          definition_id: 8,
          definition_key: "keywords",
          definition_name: "Keywords",
          selection_mode: "multi_select",
          value_id: 9,
          display_value: "Finance",
          value_status: "active",
        },
      ],
    } as TagAssignment);
    render(
      <SkillDrawer
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        selectedSkills={[]}
        groups={groups}
      />
    );
    expect(await screen.findByText("Finance")).toBeInTheDocument();
    expect(tagManagementApi.getAssignments).toHaveBeenCalledWith(
      "skill",
      "1",
      {}
    );
  });
  it("forwards edit without selecting and keeps unsupported configuration visible but disabled", () => {
    const edit = vi.fn();
    const confirm = vi.fn();
    const editable = { ...skill, permission: "EDIT" } as Skill;
    const props = {
      open: true,
      onClose: vi.fn(),
      onConfirm: confirm,
      selectedSkills: [],
      onEditSkill: edit,
      groups: [{ ...groups[0], skills: [editable] }],
    };
    const view = render(<SkillDrawer {...props} />);
    const option = screen.getByRole("option", { name: "Alpha skill" });
    fireEvent.click(
      screen.getByRole("button", { name: "skillManagement.edit.title" })
    );
    expect(edit).toHaveBeenCalledWith(editable);
    expect(option).toHaveAttribute("aria-selected", "false");
    expect(confirm).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "skillPool.configure" })
    ).toBeDisabled();
    view.rerender(<SkillDrawer {...props} isReadOnly />);
    expect(
      screen.getByRole("button", { name: "skillManagement.edit.title" })
    ).toBeDisabled();
  });
  it("keeps configuration independent and places optional tag management in the list header", () => {
    const manage = vi.fn();
    const configurable = {
      ...skill,
      permission: "EDIT",
      tags: ["Team"],
      config_schemas: [{ name: "token" }],
    } as Skill;
    const props = {
      open: true,
      onClose: vi.fn(),
      onConfirm: vi.fn(),
      selectedSkills: [],
      groups: [{ ...groups[0], skills: [configurable] }],
    };
    const view = render(<SkillDrawer {...props} />);
    expect(screen.queryByRole("button", { name: "管理标签" })).toBeNull();
    view.rerender(<SkillDrawer {...props} onOpenManageTags={manage} />);
    const heading = document.querySelector(
      '[data-picker-part="list-heading"]'
    ) as HTMLElement;
    fireEvent.click(within(heading).getByRole("button", { name: "管理标签" }));
    expect(manage).toHaveBeenCalledOnce();
    const option = screen.getByRole("option", { name: "Alpha skill" });
    expect(within(option).getByText("Team")).toBeInTheDocument();
    expect(option.firstElementChild).toHaveAttribute("data-resource-checkbox");
    fireEvent.click(
      screen.getByRole("button", { name: "skillPool.configure" })
    );
    expect(screen.getByText("Skill configuration modal")).toBeInTheDocument();
    expect(option).toHaveAttribute("aria-selected", "false");
    expect(props.onConfirm).not.toHaveBeenCalled();
  });

  it("does not commit on toggle/cancel and submits an empty selection to remove associations", async () => {
    const confirm = vi.fn();
    const close = vi.fn();
    render(
      <SkillDrawer
        open
        selectedSkills={[skill]}
        groups={groups}
        onConfirm={confirm}
        onClose={close}
      />
    );
    fireEvent.click(screen.getByRole("option", { name: "Alpha skill" }));
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { name: "关闭" })[0]);
    expect(close).toHaveBeenCalledOnce();
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith([]));
  });

  it("keeps the draft after a rejected confirm and accepts caller-defined categories", async () => {
    const confirm = vi
      .fn()
      .mockRejectedValueOnce(new Error("Save failed"))
      .mockResolvedValueOnce(undefined);
    const close = vi.fn();
    render(
      <SkillDrawer
        open
        selectedSkills={[]}
        groups={groups}
        onConfirm={confirm}
        onClose={close}
      />
    );
    expect(
      screen.getByRole("button", { name: "Team skills" })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "Alpha skill" }));
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await screen.findByText("Save failed");
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(confirm.mock.calls[1][0]).toEqual(confirm.mock.calls[0][0]);
    expect(confirm.mock.calls[1][0][0].skill_id).toBe(1);
  });
});
