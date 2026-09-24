import { expect, it, vi } from "vitest";

const { updateAgentInfo, searchAgentInfo, initialize } = vi.hoisted(() => ({
  updateAgentInfo: vi.fn(),
  searchAgentInfo: vi.fn(),
  initialize: vi.fn(),
}));
vi.mock("@/services/agentConfigService", () => ({
  updateAgentInfo,
  searchAgentInfo,
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: { getState: () => ({ initialize }) },
}));

import {
  createWorkbenchAgentDraft,
  prepareWorkbenchAgentDraft,
} from "@/features/workbench/agentCreationDraft";

it("creates an editable draft before the first NL2Agent call", async () => {
  updateAgentInfo.mockResolvedValue({ success: true, data: { agent_id: 42 } });
  const draft = await createWorkbenchAgentDraft("creator@example.com");
  expect(draft.agentId).toBe(42);
  expect(updateAgentInfo).toHaveBeenCalledWith(
    expect.objectContaining({
      display_name: draft.displayName,
      author: "creator@example.com",
      is_main_agent: true,
    })
  );
});

it("rejects an invalid draft ID instead of calling NL2Agent without one", async () => {
  updateAgentInfo.mockResolvedValue({ success: true, data: {} });
  await expect(createWorkbenchAgentDraft("")).rejects.toThrow(
    "Failed to create an Agent draft"
  );
});

it("loads the editable draft into the store used by NL2Agent resource cards", async () => {
  searchAgentInfo.mockResolvedValue({
    success: true,
    data: { agent_id: 42, name: "Draft" },
  });
  await prepareWorkbenchAgentDraft(42);
  expect(searchAgentInfo).toHaveBeenCalledWith(42, undefined, 0);
  expect(initialize).toHaveBeenCalledWith({
    agent_id: 42,
    name: "Draft",
    permission: "EDIT",
  });
});

it("does not mount a draft that could not be loaded", async () => {
  initialize.mockClear();
  searchAgentInfo.mockResolvedValue({ success: false, message: "Not found" });
  await expect(prepareWorkbenchAgentDraft(42)).rejects.toThrow("Not found");
  expect(initialize).not.toHaveBeenCalled();
});
