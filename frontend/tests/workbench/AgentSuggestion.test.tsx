// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { BookOpen } from "lucide-react";
import {
  CardSuggestion,
  TextSuggestion,
} from "@/components/agent/agent-suggestion";
import type { AgentSuggestionItem } from "@/types/agentSuggestion";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));

const suggestions: AgentSuggestionItem[] = [
  {
    id: "docs",
    title: "Documents",
    description: "Organize uploaded documents",
    prompt: "Create a document organizer",
    icon: BookOpen,
  },
  {
    id: "briefing",
    title: "Briefing",
    prompt: "Create a briefing assistant",
    disabled: true,
  },
];

it("supports keyboard selection and blocks disabled items without owning submission", async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  const view = render(
    <CardSuggestion suggestions={suggestions} onSelect={onSelect} />
  );
  expect(
    screen.getByRole("heading", { name: "agentSuggestion.heading" })
  ).toBeInTheDocument();
  await user.tab();
  expect(
    screen.getByRole("button", {
      name: "Documents Organize uploaded documents",
    })
  ).toHaveFocus();
  await user.keyboard("{Enter}");
  await user.keyboard(" ");
  expect(onSelect).toHaveBeenCalledTimes(2);
  expect(onSelect).toHaveBeenLastCalledWith(
    suggestions[0].prompt,
    suggestions[0]
  );
  expect(screen.queryByText(suggestions[0].prompt)).not.toBeInTheDocument();
  const disabled = screen.getByRole("button", { name: "Briefing" });
  expect(disabled).toBeDisabled();
  await user.click(disabled);
  expect(onSelect).toHaveBeenCalledTimes(2);
  view.rerender(
    <CardSuggestion suggestions={suggestions} onSelect={onSelect} disabled />
  );
  for (const button of screen.getAllByRole("button")) {
    expect(button).toBeDisabled();
    await user.click(button);
  }
  expect(onSelect).toHaveBeenCalledTimes(2);
});

it("keeps explicit and fallback icons stable across content changes and reordering", () => {
  const items = [
    suggestions[0],
    { id: "fallback", title: "Fallback", prompt: "full prompt" },
  ];
  const view = render(
    <CardSuggestion suggestions={items} onSelect={vi.fn()} />
  );
  expect(
    screen.getByRole("button", { name: /Documents/ }).querySelector("svg")
  ).toHaveClass("lucide-book-open");
  const originalIcon = screen
    .getByRole("button", { name: "Fallback" })
    .querySelector("svg")?.outerHTML;
  view.rerender(
    <CardSuggestion
      suggestions={[{ ...items[1], title: "Updated fallback" }, items[0]]}
      onSelect={vi.fn()}
    />
  );
  expect(
    screen
      .getByRole("button", { name: "Updated fallback" })
      .querySelector("svg")?.outerHTML
  ).toBe(originalIcon);
});

it("renders nothing for empty cards and retains the text suggestion heading", () => {
  const view = render(<CardSuggestion suggestions={[]} onSelect={vi.fn()} />);
  expect(view.container).toBeEmptyDOMElement();
  view.rerender(
    <TextSuggestion suggestions={suggestions} onSelect={vi.fn()} />
  );
  expect(
    screen.getByRole("heading", { name: "agentSuggestion.heading" })
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Organize uploaded documents")
  ).not.toBeInTheDocument();
});
