import { beforeEach, expect, it, vi } from "vitest";
import { resolveRestoredWorkbench } from "@/features/workbench/conversationRestore";
import { previewWorkbenchAgent } from "@/features/workbench/api";
import { fetchSkillsList, type SkillListItem } from "@/services/skillService";
import { initialWorkbenchState } from "@/features/workbench/state";
vi.mock("@/features/workbench/api", () => ({ previewWorkbenchAgent: vi.fn() }));
vi.mock("@/services/skillService", () => ({ fetchSkillsList: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(previewWorkbenchAgent).mockResolvedValue({
    agent_id: 8,
    version_no: 3,
    knowledge: {},
    default_skill_mounts: [
      { skill_id: 1, config_values: { region: "published" } },
    ],
  });
  vi.mocked(fetchSkillsList).mockResolvedValue([
    { skill_id: "1", name: "Default" },
    { skill_id: "2", name: "Selected" },
  ] as SkillListItem[]);
});
it("UT-FE-WB-032 restores canonical declarations and display names without default reintroduction", async () => {
  const config = {
    ...initialWorkbenchState.config,
    mode: "single_agent_chat" as const,
    agent_mounts: [{ agent_id: 8, version_no: 3 }],
    skill_mounts: [{ skill_id: 2, config_values: { region: "custom" } }],
  };
  const result = await resolveRestoredWorkbench({
    workbench_config: config,
    workbench_config_version: 7,
    agent_id: 99,
  });
  expect(previewWorkbenchAgent).toHaveBeenCalledExactlyOnceWith(8, 3);
  expect(result).toEqual({ config, version: 7, skillNames: { 2: "Selected" } });
  expect(result.config.skill_mounts).not.toContainEqual({
    skill_id: 1,
    config_values: { region: "published" },
  });
});
it("UT-FE-WB-033 legacy restoration uses published defaults and retains version zero", async () => {
  const result = await resolveRestoredWorkbench({ agent_id: 8 });
  expect(previewWorkbenchAgent).toHaveBeenCalledExactlyOnceWith(8);
  expect(result.version).toBe(0);
  expect(result.config.agent_mounts).toEqual([{ agent_id: 8, version_no: 3 }]);
  expect(result.config.skill_mounts).toEqual([
    { skill_id: 1, config_values: { region: "published" } },
  ]);
  const empty = await resolveRestoredWorkbench({});
  expect(empty.config.mode).toBe("generic_chat");
  expect(empty.version).toBe(0);
});
it("restoration stays pending until display resources finish loading", async () => {
  let finish!: (items: SkillListItem[]) => void;
  vi.mocked(fetchSkillsList).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const ready = vi.fn();
  const pending = resolveRestoredWorkbench({ agent_id: 8 }).then(ready);
  await vi.waitFor(() => expect(fetchSkillsList).toHaveBeenCalledOnce());
  expect(ready).not.toHaveBeenCalled();
  finish([{ skill_id: "1", name: "Default" }] as SkillListItem[]);
  await pending;
  expect(ready).toHaveBeenCalledOnce();
});
