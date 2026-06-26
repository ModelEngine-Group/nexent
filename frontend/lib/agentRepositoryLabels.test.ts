import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { TFunction } from "i18next";
import {
  getAgentRepositoryCategoryLabel,
  getAgentRepositoryTagLabel,
  getAgentRepositoryTagSearchText,
} from "./agentRepositoryLabels";

const t = ((key: string) => {
  const translations: Record<string, string> = {
    "agentRepository.category.writingAssistant": "Writing Assistant",
    "agentRepository.category.other": "Other",
    "agentRepository.tag.marketing": "Marketing",
    "agentRepository.tag.codeReview": "Code Review",
    "agentRepository.review.unknownCategory": "Uncategorized",
  };
  return translations[key] ?? key;
}) as TFunction;

describe("agentRepositoryLabels", () => {
  it("localizes category by stable key", () => {
    const label = getAgentRepositoryCategoryLabel(
      { id: 1, key: "writing_assistant", name: "写作助手" },
      t
    );
    assert.equal(label, "Writing Assistant");
  });

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
});
