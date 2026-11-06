// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, Form } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import AgentInfo from "../../app/[locale]/agents/[agentId]/components/agent-info";

const mocks = vi.hoisted(() => ({
  agent: { description: "", name: "assistant", display_name: "Assistant" },
  updateDraft: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      agentId: 42,
      editedAgent: mocks.agent,
      updateDraft: mocks.updateDraft,
    }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => false,
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({ data: [] }),
  useTagDefinitions: () => ({ data: [], refresh: vi.fn() }),
}));
vi.mock("@/components/tag/ResourceTagAssignmentModal", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/TagDefinitionManagementModal", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/ResourceTagChips", () => ({ default: () => null }));

beforeEach(() => {
  mocks.updateDraft.mockReset();
});

test.each(["", " \n\t "])(
  "shows required description error until filled: %j",
  async (description) => {
    mocks.agent.description = description;
    const client = new QueryClient();
    function Editor() {
      return (
        <QueryClientProvider client={client}>
          <App>
            <Form initialValues={mocks.agent}>
              <AgentInfo highFidelity />
            </Form>
          </App>
        </QueryClientProvider>
      );
    }
    const view = render(<Editor />);
    const input = screen.getByRole("textbox", { name: "agent.description" });
    expect(input).toHaveAttribute("aria-required", "true");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const wrapper = input.closest(".ant-input-textarea-affix-wrapper");
    expect(wrapper).toHaveClass("ant-input-status-error");
    expect(wrapper).not.toHaveClass("!border-[#c9c9c9]");
    expect(
      input.closest(".ant-form-item")?.querySelector(".ant-form-item-required")
    ).toBeTruthy();
    const hint = screen.getByText("agent.validation.descriptionRequired");
    expect(hint).toHaveClass("text-xs");
    expect(hint.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(input).toHaveAccessibleDescription(
      "agent.validation.descriptionRequired"
    );
    fireEvent.change(input, { target: { value: "Helps with research" } });
    expect(mocks.updateDraft).toHaveBeenCalledWith({
      description: "Helps with research",
    });
    mocks.agent.description = "Helps with research";
    view.rerender(<Editor />);
    await waitFor(() =>
      expect(
        screen.queryByText("agent.validation.descriptionRequired")
      ).not.toBeInTheDocument()
    );
    expect(input).toHaveAttribute("aria-invalid", "false");
  }
);
