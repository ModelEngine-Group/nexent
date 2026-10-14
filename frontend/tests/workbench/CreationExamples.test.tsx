import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreationExamples } from "@/features/workbench/components/CreationExamples";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
const state = vi.hoisted(() => ({ text: "", setText: vi.fn(), locale: "zh" }));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ composer: () => ({ setText: state.setText }) }),
  useAuiState: (selector: (value: unknown) => unknown) =>
    selector({ composer: { text: state.text }, thread: { messages: [] } }),
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string, fallback: string) =>
      ((state.locale === "zh" ? zh : en) as unknown as Record<string, string>)[
        key
      ] ?? fallback,
  }),
}));

it.each(["skill_create", "agent_create"] as const)(
  "UT-FE-WB-010 %s examples use localized full text and fill without sending",
  async (mode) => {
    state.text = "";
    state.locale = "zh";
    state.setText.mockReset();
    const select = vi.fn(),
      modeChange = vi.fn();
    const { rerender } = render(
      <CreationExamples mode={mode} onBack={modeChange} />
    );
    expect(
      screen
        .getAllByRole("button")
        .filter(
          (button) => button.getAttribute("aria-label") !== "返回普通对话"
        )
    ).toHaveLength(3);
    await userEvent.click(
      screen
        .getAllByRole("button")
        .filter(
          (button) => button.getAttribute("aria-label") !== "返回普通对话"
        )[0]
    );
    const key =
      mode === "skill_create"
        ? "workbench.creationExamples.skill.invoiceExtraction"
        : "workbench.creationExamples.agent.knowledgeAssistant";
    expect(state.setText).toHaveBeenCalledExactlyOnceWith(zh[key]);
    expect(select).not.toHaveBeenCalled();
    expect(modeChange).not.toHaveBeenCalled();
    state.text = "editable draft";
    rerender(<CreationExamples mode={mode} onBack={modeChange} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    state.text = "";
    state.locale = "en";
    rerender(<CreationExamples mode={mode} onBack={modeChange} />);
    expect(screen.getByText(en[key])).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("button")
        .filter(
          (button) => button.getAttribute("aria-label") !== "返回普通对话"
        )
    ).toHaveLength(3);
  }
);
