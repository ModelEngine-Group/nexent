// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect } from "react";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ConversationLoadingBoundary } from "@/app/newchat/components/ConversationLoadingBoundary";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: () => "Loading conversation" }),
}));

it("keeps the composer mounted and inert until history loading finishes", () => {
  const mounted = vi.fn();
  const unmounted = vi.fn();
  function Composer() {
    useEffect(() => {
      mounted();
      return unmounted;
    }, []);
    return <textarea aria-label="draft" defaultValue="unsent draft" />;
  }
  const view = render(
    <ConversationLoadingBoundary loading={false}>
      <Composer />
    </ConversationLoadingBoundary>
  );
  const input = screen.getByRole("textbox");
  view.rerender(
    <ConversationLoadingBoundary loading>
      <Composer />
    </ConversationLoadingBoundary>
  );
  expect(input).toBeInTheDocument();
  expect(input.parentElement).toHaveAttribute("inert");
  expect(input.closest('[aria-busy="true"]')).not.toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("Loading conversation");
  view.rerender(
    <ConversationLoadingBoundary loading={false}>
      <Composer />
    </ConversationLoadingBoundary>
  );
  expect(screen.getByRole("textbox")).toBe(input);
  expect(input).toHaveValue("unsent draft");
  expect(input.parentElement).not.toHaveAttribute("inert");
  expect(screen.queryByRole("status")).toBeNull();
  expect(mounted).toHaveBeenCalledTimes(1);
  expect(unmounted).not.toHaveBeenCalled();
});
