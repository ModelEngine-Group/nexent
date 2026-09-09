import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SelectedResourceChips } from "@/features/workbench/components/SelectedResourceChips";

it("UT-FE-WB-028 each remove operation changes only its own resource", async () => {
  const removeAgent = vi.fn(),
    removeSkill = vi.fn(),
    changeKnowledge = vi.fn();
  render(
    <SelectedResourceChips
      resources={{
        agentName: "A",
        skills: [{ id: 1, name: "S" }],
        onSelectAgent: vi.fn(),
        onRemoveAgent: removeAgent,
      }}
      scope={{
        schema_version: 1,
        local: { mode: "override", knowledge_ids: ["10", "11"] },
        aidp: { mode: "disabled", kds_ids: [] },
      }}
      onRemoveSkill={removeSkill}
      onEditKnowledge={vi.fn()}
      onKnowledgeChange={changeKnowledge}
    />
  );
  await userEvent.click(screen.getByRole("button", { name: "移除 Skill · S" }));
  expect(removeSkill).toHaveBeenCalledExactlyOnceWith(1);
  expect(removeAgent).not.toHaveBeenCalled();
  expect(changeKnowledge).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "移除 知识库 · #10" })
  );
  expect(changeKnowledge).toHaveBeenCalledExactlyOnceWith({
    schema_version: 1,
    local: { mode: "override", knowledge_ids: ["11"] },
    aidp: { mode: "disabled", kds_ids: [] },
  });
  await userEvent.click(screen.getByRole("button", { name: "移除 Agent · A" }));
  expect(removeAgent).toHaveBeenCalledOnce();
});
it("UT-FE-WB-029 clicking a Skill label opens configuration instead of removing it", async () => {
  const edit = vi.fn(),
    remove = vi.fn();
  render(
    <SelectedResourceChips
      resources={{
        skills: [{ id: 2, name: "Invoice" }],
        onSelectAgent: vi.fn(),
        onRemoveAgent: vi.fn(),
      }}
      onEditSkill={edit}
      onRemoveSkill={remove}
      onEditKnowledge={vi.fn()}
    />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Skill · Invoice" })
  );
  expect(edit).toHaveBeenCalledOnce();
  expect(remove).not.toHaveBeenCalled();
});
