// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { queryClient } from "@/lib/queryClient";
import { useAgentStore } from "@/stores/agentStore";
import { updateAgentInfo } from "@/services/agentConfigService";
import type { Agent } from "@/types/agentConfig";

vi.mock("@/lib/utils", () => ({ safeStringify: JSON.stringify }));
vi.mock("@/services/agentConfigService", () => ({
  updateAgentInfo: vi.fn(),
  searchToolConfig: vi.fn(),
  updateToolConfig: vi.fn(),
}));

const pagedKey = ["agents", { tenantId: "tenant-a", page: 1, pageSize: 20 }];
const legacyKey = ["agents", "legacy", "tenant-a"];
beforeEach(() => {
  queryClient.clear();
  useAgentStore.getState().reset();
  useAgentStore.getState().initialize({
    id: "42",
    name: "agent_a",
    display_name: "Agent A",
    permission: "EDIT",
    tools: [],
  } as unknown as Agent);
  for (const queryKey of [pagedKey, legacyKey]) {
    queryClient.setQueryData(queryKey, {
      agents: [{ id: "42", display_name: "Agent A" }],
    });
  }
  queryClient.setQueryData(["models"], ["model-a"]);
});
afterEach(async () => {
  await useAgentStore.getState().waitForIdle();
  useAgentStore.getState().reset();
  queryClient.clear();
});

it("invalidates fresh paged and legacy Agent lists after a confirmed save and refetches the renamed Agent", async () => {
  let finish!: (value: Awaited<ReturnType<typeof updateAgentInfo>>) => void;
  vi.mocked(updateAgentInfo).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  useAgentStore.getState().updateAgentConfig({ display_name: "Renamed Agent" });
  expect(queryClient.getQueryState(pagedKey)?.isInvalidated).toBe(false);
  finish({ success: true, data: null, message: "", error: undefined });
  await useAgentStore.getState().waitForIdle();
  expect(queryClient.getQueryState(pagedKey)?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(legacyKey)?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(["models"])?.isInvalidated).toBe(false);
  const fetchList = vi.fn().mockResolvedValue({
    agents: [{ id: "42", display_name: "Renamed Agent" }],
  });
  const result = await queryClient.fetchQuery({
    queryKey: pagedKey,
    queryFn: fetchList,
    staleTime: 60_000,
  });
  expect(fetchList).toHaveBeenCalledOnce();
  expect(result.agents[0].display_name).toBe("Renamed Agent");
});

it.each(["rejected", "unsuccessful"])(
  "does not invalidate or replace lists for a %s save",
  async (failure) => {
    if (failure === "rejected")
      vi.mocked(updateAgentInfo).mockRejectedValueOnce(
        new Error("Save failed")
      );
    else
      vi.mocked(updateAgentInfo).mockResolvedValueOnce({
        success: false,
        data: null,
        error: undefined,
        message: "Save failed",
      });
    useAgentStore.getState().updateAgentConfig({ display_name: "Not saved" });
    await useAgentStore.getState().waitForIdle();
    expect(queryClient.getQueryState(pagedKey)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryData(pagedKey)).toEqual({
      agents: [{ id: "42", display_name: "Agent A" }],
    });
  }
);
