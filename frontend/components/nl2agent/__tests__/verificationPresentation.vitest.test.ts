import { describe, expect, it } from "vitest";

import {
  buildVerificationPart,
  parseVerificationPresentation,
} from "../../../app/[locale]/newchat/adapter/remote-chat-model-adapter";

describe("newchat verification presentation", () => {
  it("extracts the user-facing message instead of exposing transport JSON", () => {
    const raw = JSON.stringify({
      phase: "final_pass",
      event: "final_answer",
      severity: "info",
      score: 1,
      message: "最终自检通过：答案完整且格式正常",
      passed: true,
    });

    const part = buildVerificationPart(raw);

    expect(part.text).toBe("最终自检通过：答案完整且格式正常");
    expect(part.text).not.toContain('"phase"');
    expect(part.isVerification).toBe(true);
    expect(part.verification).toEqual(
      expect.objectContaining({ phase: "final_pass", score: 1, passed: true })
    );
  });

  it("keeps legacy plain-text verification events readable", () => {
    expect(parseVerificationPresentation("Self-check passed").message).toBe(
      "Self-check passed"
    );
  });
});
