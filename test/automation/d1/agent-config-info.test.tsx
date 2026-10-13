import { App, Form } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentInfo from "../../../frontend/app/[locale]/agents/[agentId]/components/agent-info";

const mocks = vi.hoisted(() => ({
  updateDraft: vi.fn(),
  draft: {
    display_name: "Fixture Agent",
    name: "fixture_agent",
    author: "Author",
    description: "",
    icon_url: null,
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      editedAgent: mocks.draft,
      agentId: 42,
      updateDraft: mocks.updateDraft,
    }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => false,
}));
vi.mock("@/hooks/agent/useSaveGuard", () => ({
  AGENT_DESCRIPTION_MAX_LENGTH: 500,
  AGENT_NAME_MAX_LENGTH: 60,
  createAgentNameConflictValidator: () => ({
    validator: async () => undefined,
  }),
  isValidAgentName: () => true,
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({ data: [] }),
  useTagDefinitions: () => ({ data: [], refresh: vi.fn() }),
}));
vi.mock("@/components/tag/ResourceTagChips", () => ({ default: () => null }));
vi.mock("@/components/tag/ResourceTagAssignmentModal", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/TagDefinitionManagementModal", () => ({
  default: () => null,
}));

function infoTree(highFidelity = true) {
  return (
    <App>
      <Form initialValues={mocks.draft}>
        <AgentInfo highFidelity={highFidelity} />
      </Form>
    </App>
  );
}

describe("AGENT-CONFIG-D1-004 description boundaries and compatibility", () => {
  beforeEach(() => {
    mocks.draft.description = "";
    mocks.updateDraft.mockReset();
  });

  it("accepts the complete 200-character high-fidelity description", () => {
    render(infoTree());
    const description = screen.getByPlaceholderText(
      "agent.highFidelity.descriptionPlaceholder",
    );
    expect(description).toHaveAttribute("maxlength", "200");
    const boundary = "a".repeat(200);
    fireEvent.change(description, { target: { value: boundary } });
    expect(mocks.updateDraft).toHaveBeenLastCalledWith({
      description: boundary,
    });
  });

  it("renders complete legacy text, rejects growth, and permits shortening", () => {
    const legacy = "a".repeat(201);
    mocks.draft.description = legacy;
    render(infoTree());
    const description = screen.getByPlaceholderText(
      "agent.highFidelity.descriptionPlaceholder",
    );
    expect(description).toHaveValue(legacy);
    expect(mocks.updateDraft).not.toHaveBeenCalled();
    fireEvent.change(description, { target: { value: "a".repeat(202) } });
    expect(mocks.updateDraft).not.toHaveBeenCalled();
    const shortened = "a".repeat(199);
    fireEvent.change(description, { target: { value: shortened } });
    expect(mocks.updateDraft).toHaveBeenLastCalledWith({
      description: shortened,
    });
    expect(description).toHaveAttribute("maxlength", "200");
  });

  it("retains the default description maximum of 500", () => {
    render(infoTree(false));
    expect(
      screen.getByPlaceholderText("agent.descriptionPlaceholder"),
    ).toHaveAttribute("maxlength", "500");
  });

  it("shows identity fields directly in the high-fidelity basic section", () => {
    render(infoTree());

    expect(
      screen.getByPlaceholderText("agent.displayNamePlaceholder"),
    ).toBeVisible();
    expect(screen.getByPlaceholderText("agent.namePlaceholder")).toBeVisible();
    expect(
      screen.getByPlaceholderText("agent.authorPlaceholder"),
    ).toBeVisible();
    expect(
      screen.queryByText("agent.highFidelity.additionalInfo"),
    ).not.toBeInTheDocument();
  });
});
