// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, test, vi } from "vitest";
import SelectedSkillManagement from "@/app/agents/[agentId]/components/capability/SelectedSkillManagement";

const state = vi.hoisted(() => ({
  agentId: 42,
  editedAgent: {
    skills: [{ skill_id: 7, name: "existing-skill", source: "custom" }],
  },
  updateSkills: vi.fn(),
  isReadOnly: false,
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(
    (select: (value: typeof state) => unknown) => select(state),
    { getState: () => state }
  ),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/agent/useSkillList", () => ({
  useSkillList: () => ({
    skills: [
      {
        skill_id: 7,
        name: "existing-skill",
        source: "custom",
        blocked_by_denylist: true,
        config_schemas: [{ name: "query", type: "string" }],
      },
    ],
    availableSkills: [],
  }),
}));
vi.mock("@/app/agents/components/capability/SkillDetailModal", () => ({
  default: () => null,
}));
vi.mock("@/components/skill-config/SkillConfigModal", () => ({
  default: () => null,
}));
beforeEach(() => {
  state.agentId = 42;
  state.isReadOnly = false;
});

test("blocked existing skill remains visible and configurable; cancel preserves it and confirmation removes it", async () => {
  render(
    <App>
      <SelectedSkillManagement currentAgentId={42} highFidelity />
    </App>
  );
  expect(screen.getByText("existing-skill")).toBeVisible();
  expect(screen.getByText("resourceDenylist.existingBinding")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "skillPool.configure existing-skill" })
  ).toBeEnabled();
  const remove = screen.getByRole("button", {
    name: "skillPool.remove existing-skill",
  });
  fireEvent.click(remove);
  await waitFor(() =>
    expect(screen.getByText("resourceDenylist.removeWarning")).toBeVisible()
  );
  expect(state.updateSkills).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
  await waitFor(() =>
    expect(
      screen.queryByText("resourceDenylist.removeWarning")
    ).not.toBeInTheDocument()
  );
  fireEvent.click(remove);
  fireEvent.click(
    await screen.findByRole("button", { name: "common.confirm" })
  );
  await waitFor(() =>
    expect(state.updateSkills).toHaveBeenCalledExactlyOnceWith([])
  );
});
