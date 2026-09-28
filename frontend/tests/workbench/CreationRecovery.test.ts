import { describe, expect, it } from "vitest";
import {
  isAgentCreationAwaitingDraft,
  shouldAutoCreateAgentDraft,
} from "@/features/workbench/creationRecovery";

describe("deleted Agent creation recovery", () => {
  it("creates a draft for a new or recovered creation conversation", () => {
    expect(shouldAutoCreateAgentDraft(undefined, false)).toBe(true);
    expect(shouldAutoCreateAgentDraft("42", true)).toBe(true);
    expect(shouldAutoCreateAgentDraft("42", false)).toBe(false);
  });

  it("keeps an existing conversation locked only until draft restoration completes", () => {
    expect(isAgentCreationAwaitingDraft("42", false, false)).toBe(true);
    expect(isAgentCreationAwaitingDraft("42", false, true)).toBe(false);
    expect(isAgentCreationAwaitingDraft("42", true, false)).toBe(false);
    expect(isAgentCreationAwaitingDraft(undefined, false, false)).toBe(false);
  });
});
