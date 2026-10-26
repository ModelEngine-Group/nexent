// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import JSZip from "jszip";
import { afterEach, describe, expect, it, vi } from "vitest";

import { normalizeImportedAgentPrompt, parseAgentImportFile } from "@/lib/agentImportUtils";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("External Agent file prompt normalization", () => {
  it.each([
    ["constraint_prompt", "few_shots_prompt"],
    ["constraints_prompt", "few_shot_prompts"],
  ])("merges %s and %s once without changing source content", (constraint, examples) => {
    const source = { duty_prompt: "职责\n  原文", [constraint]: "Rule", [examples]: "<code>\n  run()\n</code>", tools: [] };
    const original = JSON.stringify(source);
    const normalized = normalizeImportedAgentPrompt(source);
    expect(normalized).toEqual({
      prompt: "# Responsibilities\n职责\n  原文\n\n# Constraints\nRule\n\n# Examples\n<code>\n  run()\n</code>",
      tools: [],
    });
    expect(normalizeImportedAgentPrompt(normalized)).toEqual(normalized);
    expect(JSON.stringify(source)).toBe(original);
  });

  it.each([
    [{ prompt: " exact\n  prompt " }, { prompt: " exact\n  prompt " }],
    [{ duty_prompt: null, constraint_prompt: null }, { prompt: null }],
    [{ duty_prompt: "", few_shots_prompt: "" }, { prompt: "" }],
    [{ duty_prompt: "Keep", constraint_prompt: " \t\n\r" }, { prompt: "Keep" }],
    [{ prompt: "Same", duty_prompt: "Same" }, { prompt: "Same" }],
    [{ few_shot_prompts: "Example" }, { prompt: "# Examples\nExample" }],
  ])("preserves empty/null/canonical values: %j", (source, expected) => {
    expect(normalizeImportedAgentPrompt(source)).toEqual(expected);
  });

  it.each([
    ["prompt", "duty_prompt"], ["constraint_prompt", "constraints_prompt"],
    ["few_shots_prompt", "few_shot_prompts"],
  ])("rejects conflicting aliases %s and %s", (canonical, legacy) => {
    const source = { [canonical]: "New", [legacy]: "Old" };
    expect(() => normalizeImportedAgentPrompt(source)).toThrow("must not conflict");
    expect(source).toEqual({ [canonical]: "New", [legacy]: "Old" });
  });

  it.each(["prompt", "duty_prompt", "constraint_prompt", "constraints_prompt", "few_shots_prompt", "few_shot_prompts"])(
    "rejects non-string %s values", (field) => {
      for (const value of [7, [], {}, true]) {
        expect(() => normalizeImportedAgentPrompt({ [field]: value })).toThrow("must be a string or null");
      }
    },
  );

  it.each(["json", "zip"])("normalizes parent and child before opening the wizard from %s", async (extension) => {
    const data = { agent_id: 1, agent_info: {
      "1": { duty_prompt: "Root", constraint_prompt: "<TO_CONFIG:rule>" },
      "2": { duty_prompt: "Child", few_shot_prompts: "Example" },
    }, mcp_info: [] };
    const content = JSON.stringify(data);
    const file = new File([content], `agent.${extension}`);
    Object.defineProperty(file, "text", { value: async () => content });
    if (extension === "zip") {
      const zip = new JSZip().file("agent.json", content);
      const bytes = await zip.generateAsync({ type: "uint8array" });
      const decoded = await JSZip.loadAsync(bytes);
      vi.spyOn(JSZip, "loadAsync").mockResolvedValue(decoded);
    }
    const parsed = await parseAgentImportFile(file);
    expect(parsed?.agent_info["1"]).toEqual({ prompt: "# Responsibilities\nRoot\n\n# Constraints\n<TO_CONFIG:rule>" });
    expect(parsed?.agent_info["2"]).toEqual({ prompt: "# Responsibilities\nChild\n\n# Examples\nExample" });
  });

  it("returns no import data on conflicting values", async () => {
    const content = JSON.stringify({ agent_id: 1, agent_info: { "1": { prompt: "New", duty_prompt: "Old" } } });
    const file = new File([content], "agent.json");
    Object.defineProperty(file, "text", { value: async () => content });
    const error = vi.fn();
    expect(await parseAgentImportFile(file, { onGenericError: error })).toBeNull();
    expect(error).toHaveBeenCalledOnce();
  });
});
