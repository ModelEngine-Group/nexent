// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreationActions } from "@/features/workbench/components/CreationActions";

it.each([
  [false, false],
  [false, true],
  [true, false],
  [true, true],
])(
  "UT-FE-WB-012 creation permissions: agent=%s skill=%s",
  async (agent, skill) => {
    const select = vi.fn();
    render(
      <CreationActions
        canCreateAgent={agent}
        canCreateSkill={skill}
        disabled={false}
        onSelect={select}
      />
    );
    expect(Boolean(screen.queryByRole("button", { name: "智能体创建" }))).toBe(
      agent
    );
    expect(Boolean(screen.queryByRole("button", { name: "技能创建" }))).toBe(
      skill
    );
    if (agent) {
      await userEvent.click(screen.getByRole("button", { name: "智能体创建" }));
      expect(select).toHaveBeenLastCalledWith("agent_create");
    }
    if (skill) {
      await userEvent.click(screen.getByRole("button", { name: "技能创建" }));
      expect(select).toHaveBeenLastCalledWith("skill_create");
    }
  }
);

it("running creation actions cannot switch threads", async () => {
  const select = vi.fn();
  render(
    <CreationActions canCreateAgent canCreateSkill disabled onSelect={select} />
  );
  for (const button of screen.getAllByRole("button")) {
    expect(button).toBeDisabled();
    await userEvent.click(button);
  }
  expect(select).not.toHaveBeenCalled();
});

it("offers draft editing separately and removes the link while running", () => {
  const props = {
    canCreateAgent: true,
    canCreateSkill: true,
    onSelect: vi.fn(),
    mode: "agent_create" as const,
    draftAgentId: 42,
  };
  const view = render(<CreationActions {...props} disabled={false} />);
  expect(screen.getByRole("link", { name: "编辑当前草稿" })).toHaveAttribute(
    "href",
    "/zh/agents/42"
  );
  expect(screen.queryByText("草稿已生成")).not.toBeInTheDocument();
  view.rerender(<CreationActions {...props} disabled />);
  expect(
    screen.queryByRole("link", { name: "编辑当前草稿" })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "编辑当前草稿" })).toBeDisabled();
  view.rerender(
    <CreationActions {...props} disabled={false} mode="skill_create" />
  );
  expect(screen.queryByText("编辑当前草稿")).not.toBeInTheDocument();
});

it.each([undefined, 0, -1])(
  "hides a missing or invalid draft %s",
  (draftAgentId) => {
    render(
      <CreationActions
        canCreateAgent
        canCreateSkill
        disabled={false}
        onSelect={vi.fn()}
        mode="agent_create"
        draftAgentId={draftAgentId}
      />
    );
    expect(screen.queryByText("编辑当前草稿")).not.toBeInTheDocument();
  }
);

it.each(["agent_create", "skill_create"] as const)(
  "clicking active %s exits but another mode switches",
  async (mode) => {
    const select = vi.fn();
    const exit = vi.fn();
    const { rerender } = render(
      <CreationActions
        canCreateAgent
        canCreateSkill
        disabled={false}
        mode={mode}
        onSelect={select}
        onExit={exit}
      />
    );
    expect(
      screen.queryByRole("button", { name: "返回普通对话" })
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(2);
    const active = mode === "agent_create" ? "智能体创建" : "技能创建";
    const other = mode === "agent_create" ? "技能创建" : "智能体创建";
    await userEvent.click(screen.getByRole("button", { name: active }));
    expect(exit).toHaveBeenCalledTimes(1);
    expect(select).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: other }));
    expect(select).toHaveBeenCalledWith(
      mode === "agent_create" ? "skill_create" : "agent_create"
    );
    rerender(
      <CreationActions
        canCreateAgent
        canCreateSkill
        disabled
        mode={mode}
        onSelect={select}
        onExit={exit}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: active }));
    expect(exit).toHaveBeenCalledTimes(1);
  }
);
