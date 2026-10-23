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
    expect(Boolean(screen.queryByRole("button", { name: "Agent创建" }))).toBe(
      agent
    );
    expect(Boolean(screen.queryByRole("button", { name: "Skill 创建" }))).toBe(
      skill
    );
    if (agent) {
      await userEvent.click(screen.getByRole("button", { name: "Agent创建" }));
      expect(select).toHaveBeenLastCalledWith("agent_create");
    }
    if (skill) {
      await userEvent.click(screen.getByRole("button", { name: "Skill 创建" }));
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
