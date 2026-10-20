// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreationExamples } from "@/features/workbench/components/CreationExamples";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
import { CREATION_PROMPTS } from "@/features/workbench/state";
const state = vi.hoisted(() => ({
  text: "",
  messages: [] as unknown[],
  setText: vi.fn(),
  send: vi.fn(),
  locale: "zh",
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    composer: () => ({ setText: state.setText, send: state.send }),
  }),
  useAuiState: (selector: (value: unknown) => unknown) =>
    selector({
      composer: { text: state.text },
      thread: { messages: state.messages },
    }),
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

beforeEach(() => {
  state.text = "";
  state.messages = [];
  state.locale = "zh";
  state.setText.mockReset();
  state.send.mockReset();
});

it.each(["skill_create"] as const)(
  "UT-FE-WB-010 %s examples use localized full text and fill without sending",
  async (mode) => {
    state.text = "";
    state.locale = "zh";
    state.setText.mockReset();
    const select = vi.fn(),
      modeChange = vi.fn();
    const { rerender } = render(<CreationExamples mode={mode} />);
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
        : "workbench.creationExamples.agent.documentOrganizer";
    expect(state.setText).toHaveBeenCalledExactlyOnceWith(zh[key]);
    expect(select).not.toHaveBeenCalled();
    expect(modeChange).not.toHaveBeenCalled();
    state.text = "editable draft";
    rerender(<CreationExamples mode={mode} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    state.text = "";
    state.locale = "en";
    rerender(<CreationExamples mode={mode} />);
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

const agentKeys = ["documentOrganizer", "medicalBriefing", "eventPromotion"];

it.each(["zh", "en"])(
  "%s agent cards show short localized copy and fill each complete prompt without sending",
  async (locale) => {
    state.locale = locale;
    const copy = (locale === "zh" ? zh : en) as unknown as Record<
      string,
      string
    >;
    render(
      <>
        <textarea data-workbench-composer />
        <CreationExamples mode="agent_create" />
      </>
    );
    expect(screen.getAllByRole("button")).toHaveLength(3);
    for (const [index, key] of agentKeys.entries()) {
      const prefix = `workbench.creationExamples.agent.${key}`;
      const title = copy[`${prefix}.title`];
      const description = copy[`${prefix}.description`];
      expect(title).toBeTruthy();
      expect(description).toBeTruthy();
      expect(description.length).toBeLessThan(100);
      const button = screen.getByRole("button", {
        name: `${title} ${description}`,
      });
      expect(screen.queryByText(copy[prefix])).not.toBeInTheDocument();
      expect(copy[prefix].length).toBeGreaterThan(250);
      await userEvent.click(button);
      expect(state.setText).toHaveBeenNthCalledWith(index + 1, copy[prefix]);
      if (locale === "zh") {
        expect(CREATION_PROMPTS.agent_create[index]).toBe(copy[prefix]);
      }
      await vi.waitFor(() => expect(screen.getByRole("textbox")).toHaveFocus());
    }
    expect(state.setText).toHaveBeenCalledTimes(3);
    expect(state.send).not.toHaveBeenCalled();
  }
);

it.each(["skill_create", "agent_create"] as const)(
  "%s recommendations stay hidden for drafts or existing messages",
  (mode) => {
    const { rerender } = render(<CreationExamples mode={mode} />);
    expect(screen.getAllByRole("button")).toHaveLength(3);
    state.text = "editable draft";
    rerender(<CreationExamples mode={mode} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    state.text = "";
    state.messages = [{ role: "user", content: [] }];
    rerender(<CreationExamples mode={mode} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(state.setText).not.toHaveBeenCalled();
    expect(state.send).not.toHaveBeenCalled();
  }
);
