import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { TFunction } from "i18next";
import {
  getAgentRepositoryTagLabel,
  getAgentRepositoryTagSearchText,
  resolveAgentRepositoryTagForSubmit,
} from "./agentRepositoryLabels";

const t = ((key: string) => {
  const translations: Record<string, string> = {
    "agentRepository.tag.marketing": "Marketing",
    "agentRepository.tag.codeReview": "Code Review",
  };
  return translations[key] ?? key;
}) as TFunction;

describe("agentRepositoryLabels", () => {
  it("localizes preset tag keys", () => {
    assert.equal(getAgentRepositoryTagLabel("marketing", t), "Marketing");
  });

  it("localizes legacy Chinese tag values", () => {
    assert.equal(getAgentRepositoryTagLabel("代码审查", t), "Code Review");
  });

  it("returns custom tags unchanged", () => {
    assert.equal(getAgentRepositoryTagLabel("my-custom-tag", t), "my-custom-tag");
  });

  it("includes localized text in tag search text", () => {
    const searchText = getAgentRepositoryTagSearchText("marketing", t);
    assert.match(searchText, /marketing/);
    assert.match(searchText, /Marketing/);
  });

  it("resolves preset tag keys to localized submit values", () => {
    assert.equal(resolveAgentRepositoryTagForSubmit("marketing", t), "Marketing");
  });

  it("resolves legacy Chinese preset values to localized submit values", () => {
    assert.equal(
      resolveAgentRepositoryTagForSubmit("代码审查", t),
      "Code Review"
    );
  });

  it("returns custom tags unchanged for submit", () => {
    assert.equal(
      resolveAgentRepositoryTagForSubmit("my-custom-tag", t),
      "my-custom-tag"
    );
  });
});
