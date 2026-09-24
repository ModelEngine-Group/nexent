import { describe, expect, it } from "vitest";
import {
  applySkillCreationEvent,
  buildSkillSavePayload,
  initialSkillCreationDraft,
} from "@/features/workbench/creationRuntime";

describe("workbench creation runtime", () => {
  it("collects NL2Skill files and prepares a saveable Skill", () => {
    let draft = initialSkillCreationDraft;
    draft = applySkillCreationEvent(draft, { type: "agent_new_run" });
    draft = applySkillCreationEvent(draft, {
      type: "skill_body",
      content:
        "---\nname: invoice-helper\ndescription: Extract invoices\ntags: [invoice]\n---\n# Instructions",
    });
    draft = applySkillCreationEvent(draft, {
      type: "file_content",
      path: "scripts/extract.py",
      content: "print('ok')",
    });
    draft = applySkillCreationEvent(draft, { type: "done" });
    draft = applySkillCreationEvent(draft, { type: "stream_closed" });

    expect(draft.complete).toBe(true);
    expect(buildSkillSavePayload(draft)).toEqual({
      name: "invoice-helper",
      description: "Extract invoices",
      tags: ["invoice"],
      source: "custom",
      content: "# Instructions",
      files: [{ path: "scripts/extract.py", content: "print('ok')" }],
    });
  });

  it("rolls back failed model attempts without losing previous files", () => {
    let draft = applySkillCreationEvent(initialSkillCreationDraft, {
      type: "skill_body",
      content: "stable",
    });
    draft = applySkillCreationEvent(draft, {
      type: "model_attempt_control",
      phase: "begin",
      attempt_id: "a1",
    });
    draft = applySkillCreationEvent(draft, {
      type: "skill_body",
      content: " failed",
    });
    draft = applySkillCreationEvent(draft, {
      type: "model_attempt_control",
      phase: "rollback",
      attempt_id: "a1",
    });
    expect(draft.files["SKILL.md"]).toBe("stable");
  });

  it("does not mark an empty or failed stream saveable", () => {
    const done = applySkillCreationEvent(initialSkillCreationDraft, {
      type: "done",
    });
    expect(done.complete).toBe(false);
    expect(buildSkillSavePayload(done)).toBeNull();
  });

  it("restarts the target file after a failed first attempt", () => {
    let draft = applySkillCreationEvent(initialSkillCreationDraft, {
      type: "skill_body",
      content: "old",
    });
    draft = applySkillCreationEvent(draft, { type: "agent_new_run" });
    draft = applySkillCreationEvent(draft, {
      type: "model_attempt_control",
      phase: "begin",
      attempt_id: "a1",
    });
    draft = applySkillCreationEvent(draft, {
      type: "skill_body",
      content: "bad",
    });
    draft = applySkillCreationEvent(draft, {
      type: "model_attempt_control",
      phase: "rollback",
      attempt_id: "a1",
    });
    draft = applySkillCreationEvent(draft, {
      type: "skill_body",
      content: "new",
    });
    expect(draft.files["SKILL.md"]).toBe("new");
  });
});
