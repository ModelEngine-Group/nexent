import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AidpKnowledgeGuide from "@/ext_components/aidp/components/AidpKnowledgeGuide";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "zh" } }),
}));

afterEach(() => window.sessionStorage.clear());

describe("knowledge guide preference", () => {
  it("starts expanded, remembers collapse across route unmount, and reopens from usage guide", async () => {
    const first = render(<AidpKnowledgeGuide />);
    expect(screen.getByText("aidpKnowledge.guideIntro")).toBeVisible();
    expect(screen.getByText("aidpKnowledge.guideBenefitOne")).toBeVisible();
    expect(screen.getByText("aidpKnowledge.guideBenefitTwo")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /guideCollapse/ }));
    expect(screen.queryByText("aidpKnowledge.guideIntro")).toBeNull();
    first.unmount();

    render(<AidpKnowledgeGuide />);
    await screen.findByRole("button", { name: /guideExpand/ });
    expect(screen.queryByText("aidpKnowledge.guideIntro")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /guideExpand/ }));
    expect(screen.getByText("aidpKnowledge.guideIntro")).toBeVisible();
  });
});
