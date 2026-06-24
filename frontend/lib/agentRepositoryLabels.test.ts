import { describe, expect, it, vi } from "vitest";
import {
  getAgentRepositoryCategoryLabel,
  getAgentRepositoryTagLabel,
  getAgentRepositoryTagSearchText,
} from "./agentRepositoryLabels";

const t = vi.fn((key: string) => {
  const translations: Record<string, string> = {
    "agentRepository.category.writingAssistant": "Writing Assistant",
    "agentRepository.category.other": "Other",
    "agentRepository.tag.marketing": "Marketing",
    "agentRepository.tag.codeReview": "Code Review",
    "agentRepository.review.unknownCategory": "Uncategorized",
  };
  return translations[key] ?? key;
});

describe("agentRepositoryLabels", () => {
  it("localizes category by stable key", () => {
    const label = getAgentRepositoryCategoryLabel(
      { id: 1, key: "writing_assistant", name: "写作助手" },
      t
    );
    expect(label).toBe("Writing Assistant");
  });

  it("localizes preset tag keys", () => {
    expect(getAgentRepositoryTagLabel("marketing", t)).toBe("Marketing");
  });

  it("localizes legacy Chinese tag values", () => {
    expect(getAgentRepositoryTagLabel("代码审查", t)).toBe("Code Review");
  });

  it("returns custom tags unchanged", () => {
    expect(getAgentRepositoryTagLabel("my-custom-tag", t)).toBe("my-custom-tag");
  });

  it("includes localized text in tag search text", () => {
    const searchText = getAgentRepositoryTagSearchText("marketing", t);
    expect(searchText).toContain("marketing");
    expect(searchText).toContain("Marketing");
  });
});
