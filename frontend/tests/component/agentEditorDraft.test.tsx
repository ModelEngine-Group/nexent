// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentEditorDraft } from "@/hooks/agent/useAgentEditorDraft";
import {
  searchAgentInfo,
  updateAgentInfo,
} from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import type { Agent } from "@/types/agentConfig";


vi.mock("@/services/agentConfigService", () => ({
  searchAgentInfo: vi.fn(),
  updateAgentInfo: vi.fn(),
  updateToolConfig: vi.fn(),
  searchToolConfig: vi.fn(),
}));

const waitForIdle = useAgentStore.getState().waitForIdle;

function draft(id = 42, displayName = "Generated assistant"): Agent {
  return {
    id,
    name: "generated_assistant",
    display_name: displayName,
    description: "Generated description",
    prompt: "Generated prompt",
    greeting_message: "Generated greeting",
    example_questions: ["Generated question"],
    permission: "EDIT",
    tools: [],
    skills: [],
  } as unknown as Agent;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAgentStore.setState({ waitForIdle });
  useAgentStore.getState().reset();
  vi.mocked(searchAgentInfo).mockResolvedValue({
    success: true,
    data: draft(),
  } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
  useAgentStore.getState().reset();
});

describe("Agent editor entry draft synchronization", () => {
  it("uses database instructions instead of a retired generation cache", () => {
    const key = "nexent_agent_generation_cache_v2_42";
    localStorage.setItem(key, JSON.stringify({
      agentId: 42, prompt: "Stale generated instructions", isGenerating: false,
      timestamp: Date.now(), expiryMs: 1800000,
    }));
    try {
      useAgentConfigStore.getState().setCurrentAgent({ ...draft(), id: "42" } as unknown as Agent);
      expect(useAgentConfigStore.getState().editedAgent.prompt).toBe("Generated prompt");
    } finally {
      localStorage.removeItem(key);
    }
  });

  it("persists a complete prompt without legacy fields or unrelated edits", async () => {
    useAgentStore.getState().initialize(draft());
    vi.mocked(updateAgentInfo).mockResolvedValue({ success: true } as never);
    const initial = useAgentStore.getState().editedAgent;
    expect(initial).not.toHaveProperty("constraint_prompt");
    expect(initial).not.toHaveProperty("few_shots_prompt");

    act(() => {
      useAgentStore.getState().updateDraft({ prompt: "Complete updated prompt" });
      useAgentStore.getState().flushDraft();
    });
    await waitFor(() => expect(updateAgentInfo).toHaveBeenCalledOnce());
    expect(updateAgentInfo).toHaveBeenCalledWith({ agent_id: 42, prompt: "Complete updated prompt" });
    await waitFor(() => expect(useAgentStore.getState().savedAgent?.prompt).toBe("Complete updated prompt"));
    expect(useAgentStore.getState().editedAgent?.description).toBe(initial?.description);
  });


  it("reloads a Workbench preloaded ID and replaces all generated fields without autosave", async () => {
    useAgentStore.getState().initialize({
      ...draft(),
      display_name: "Workbench Draft",
      description: "",
      prompt: "",
      greeting_message: "",
    });
    const { result } = renderHook(() => useAgentEditorDraft(42));
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(searchAgentInfo).toHaveBeenCalledWith(42, undefined, 0);
    expect(useAgentStore.getState().editedAgent).toMatchObject({
      name: "generated_assistant",
      display_name: "Generated assistant",
      description: "Generated description",
      prompt: "Generated prompt",
      greeting_message: "Generated greeting",
      example_questions: ["Generated question"],
    });
    expect(useAgentStore.getState().savedAgent).toEqual(
      useAgentStore.getState().editedAgent
    );
    expect(updateAgentInfo).not.toHaveBeenCalled();
  });

  it("initializes fresh entry and retains server read-only permission", async () => {
    vi.mocked(searchAgentInfo).mockResolvedValue({
      success: true,
      data: { ...draft(), permission: "READ_ONLY" },
    } as never);
    const { result } = renderHook(() => useAgentEditorDraft(42));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(useAgentStore.getState().currentAgentId).toBe(42);
    expect(useAgentStore.getState().isReadOnly).toBe(true);
  });

  it("reloads on reentry with the same selected ID", async () => {
    const first = renderHook(() => useAgentEditorDraft(42));
    await waitFor(() => expect(first.result.current.isLoading).toBe(false));
    first.unmount();
    vi.mocked(searchAgentInfo).mockResolvedValue({
      success: true,
      data: draft(42, "Regenerated assistant"),
    } as never);
    const second = renderHook(() => useAgentEditorDraft(42));
    await waitFor(() => expect(second.result.current.isLoading).toBe(false));
    expect(useAgentStore.getState().editedAgent?.display_name).toBe(
      "Regenerated assistant"
    );
    expect(searchAgentInfo).toHaveBeenCalledTimes(2);
  });

  it("waits for pending saves before reading the latest draft", async () => {
    const idle = deferred<boolean>();
    vi.spyOn(useAgentStore.getState(), "waitForIdle").mockReturnValue(
      idle.promise
    );
    const { result } = renderHook(() => useAgentEditorDraft(42));
    expect(searchAgentInfo).not.toHaveBeenCalled();
    await act(async () => {
      idle.resolve(true);
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(searchAgentInfo).toHaveBeenCalledOnce();
  });

  it("preserves the draft and exposes a failed pending save", async () => {
    useAgentStore.getState().initialize(draft(42, "Unsaved draft"));
    vi.spyOn(useAgentStore.getState(), "waitForIdle").mockResolvedValue(false);
    const { result } = renderHook(() => useAgentEditorDraft(42));
    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    expect(useAgentStore.getState().editedAgent?.display_name).toBe(
      "Unsaved draft"
    );
    expect(searchAgentInfo).not.toHaveBeenCalled();
  });

  it.each(["response", "network", "wrong-id"])(
    "preserves the preloaded draft on %s failure",
    async (failure) => {
      useAgentStore.getState().initialize(draft(42, "Original draft"));
      if (failure === "network") {
        vi.mocked(searchAgentInfo).mockRejectedValue(
          new Error("Network unavailable")
        );
      } else {
        vi.mocked(searchAgentInfo).mockResolvedValue(
          (failure === "wrong-id"
            ? { success: true, data: draft(43) }
            : { success: false, message: "Not found" }) as never
        );
      }
      const { result } = renderHook(() => useAgentEditorDraft(42));
      await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
      expect(useAgentStore.getState().editedAgent?.display_name).toBe(
        "Original draft"
      );
      expect(updateAgentInfo).not.toHaveBeenCalled();
    }
  );

  it("ignores a slow response for the previous route", async () => {
    const slow = deferred<Awaited<ReturnType<typeof searchAgentInfo>>>();
    vi.mocked(searchAgentInfo)
      .mockReturnValueOnce(slow.promise)
      .mockResolvedValueOnce({
        success: true,
        data: draft(43, "Current Agent"),
      } as never);
    const { result, rerender } = renderHook(
      ({ id }) => useAgentEditorDraft(id),
      { initialProps: { id: 42 } }
    );
    await waitFor(() => expect(searchAgentInfo).toHaveBeenCalledOnce());
    rerender({ id: 43 });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      slow.resolve({ success: true, data: draft(42, "Stale Agent") } as never);
    });
    expect(useAgentStore.getState().currentAgentId).toBe(43);
    expect(useAgentStore.getState().editedAgent?.display_name).toBe(
      "Current Agent"
    );
  });

  it("does not initialize after unmount", async () => {
    const slow = deferred<Awaited<ReturnType<typeof searchAgentInfo>>>();
    vi.mocked(searchAgentInfo).mockReturnValue(slow.promise);
    const { unmount } = renderHook(() => useAgentEditorDraft(42));
    await waitFor(() => expect(searchAgentInfo).toHaveBeenCalledOnce());
    unmount();
    await act(async () => {
      slow.resolve({ success: true, data: draft() } as never);
    });
    expect(useAgentStore.getState().currentAgentId).toBeNull();
  });

  it("preserves a different Agent selected while readback is pending", async () => {
    const slow = deferred<Awaited<ReturnType<typeof searchAgentInfo>>>();
    vi.mocked(searchAgentInfo).mockReturnValue(slow.promise);
    const { result } = renderHook(() => useAgentEditorDraft(42));
    await waitFor(() => expect(searchAgentInfo).toHaveBeenCalledOnce());
    await act(async () => {
      useAgentStore.getState().initialize(draft(43, "Other Agent"));
      slow.resolve({ success: true, data: draft() } as never);
    });
    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    expect(useAgentStore.getState().currentAgentId).toBe(43);
    expect(useAgentStore.getState().editedAgent?.display_name).toBe(
      "Other Agent"
    );
  });

  it("does not overwrite an edit started during readback", async () => {
    useAgentStore.getState().initialize(draft());
    const slow = deferred<Awaited<ReturnType<typeof searchAgentInfo>>>();
    vi.mocked(searchAgentInfo).mockReturnValue(slow.promise);
    const { result } = renderHook(() => useAgentEditorDraft(42));
    await waitFor(() => expect(searchAgentInfo).toHaveBeenCalledOnce());
    await act(async () => {
      useAgentStore.getState().updateDraft({ description: "New local edit" });
      slow.resolve({ success: true, data: draft() } as never);
    });
    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    expect(useAgentStore.getState().editedAgent?.description).toBe(
      "New local edit"
    );
    expect(updateAgentInfo).not.toHaveBeenCalled();
  });

  it.each([0, -1, NaN, 1.5])("does not fetch invalid ID %s", (id) => {
    const { result } = renderHook(() => useAgentEditorDraft(id));
    expect(result.current.isLoading).toBe(false);
    expect(searchAgentInfo).not.toHaveBeenCalled();
  });
});
