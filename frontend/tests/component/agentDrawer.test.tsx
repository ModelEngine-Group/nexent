// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { render, changePageSize } from "./resourceDrawerTestUtils";
import {
  AgentDrawer,
  toLocalCard,
} from "@/components/resource-picker/AgentDrawer";
import type { Agent } from "@/types/agentConfig";
import { API_ENDPOINTS } from "@/services/api";
import { tagManagementApi } from "@/services/tagManagementService";

vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn(async () => []),
    listDefinitions: vi.fn(async () => []),
    getAssignments: vi.fn(async () => ({ assignments: [] })),
    getAgentAssignmentsBatch: vi.fn(async () => []),
    filterResourceIds: vi.fn(async () => ({ matched_resource_ids: [] })),
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

const categories = [
  {
    key: "mine",
    label: "Mine",
    items: [
      {
        id: "local:1",
        name: "My agent",
        description: "Local description",
        iconBg: "blue",
      },
    ],
  },
  {
    key: "repository",
    label: "Repository",
    items: [
      {
        id: "repo:1",
        name: "Repository agent",
        description: "Repository description",
        iconBg: "blue",
      },
    ],
  },
];

describe("AgentDrawer controlled selection", () => {
  it("batches only visible canonical tag IDs across pages and skips external cards", async () => {
    const items = Array.from({ length: 21 }, (_, index) => ({
      id: `repository:${index + 100}`,
      tagResourceId: String(index + 1),
      name: `Canonical agent ${index + 1}`,
      description: "",
    }));
    render(
      <AgentDrawer
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        selected={[]}
        categories={[
          { key: "repository", label: "Repository", items },
          {
            key: "external",
            label: "External",
            supportsTagFilter: false,
            items: [{ id: "a2a:1", name: "External agent", description: "" }],
          },
        ]}
      />
    );
    await waitFor(() =>
      expect(
        tagManagementApi.getAgentAssignmentsBatch
      ).toHaveBeenCalledExactlyOnceWith(
        Array.from({ length: 10 }, (_, index) => String(index + 1))
      )
    );
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    await waitFor(() =>
      expect(
        tagManagementApi.getAgentAssignmentsBatch
      ).toHaveBeenLastCalledWith(["21"])
    );
    await changePageSize(20);
    await waitFor(() =>
      expect(
        tagManagementApi.getAgentAssignmentsBatch
      ).toHaveBeenLastCalledWith(
        Array.from({ length: 20 }, (_, index) => String(index + 1))
      )
    );
    expect(tagManagementApi.getAgentAssignmentsBatch).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByRole("button", { name: "External" }));
    expect(
      screen.getByRole("option", { name: "External agent" })
    ).toBeInTheDocument();
    expect(tagManagementApi.getAgentAssignmentsBatch).toHaveBeenCalledTimes(3);
    expect(tagManagementApi.getAssignments).not.toHaveBeenCalled();
  });
  it("uses the chosen page size for agent cards without losing selection", async () => {
    const items = Array.from({ length: 21 }, (_, index) => ({
      id: String(index + 1),
      name: `Agent ${index + 1}`,
      description: "",
    }));
    render(
      <AgentDrawer
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        selected={[]}
        categories={[{ key: "mine", label: "Mine", items }]}
      />
    );
    expect(screen.getAllByRole("option")).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    fireEvent.click(screen.getByRole("option", { name: "Agent 21" }));
    await changePageSize(20);
    expect(screen.getAllByRole("option")).toHaveLength(20);
    expect(screen.getByRole("option", { name: "Agent 1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    expect(screen.getByRole("option", { name: "Agent 21" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("selects a card by body or keyboard and toggles its checkbox only once", () => {
    render(
      <AgentDrawer
        open
        categories={categories}
        selected={[]}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />
    );
    const card = screen.getByRole("option", { name: "My agent" });
    fireEvent.click(card);
    expect(card).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("checkbox", { name: "My agent" }));
    expect(card).toHaveAttribute("aria-selected", "false");
    fireEvent.keyDown(card, { key: "Enter" });
    expect(card).toHaveAttribute("aria-selected", "true");
    expect(card).toHaveClass("cursor-pointer");
  });
  it("uses the saved icon and falls back by original agent ID if loading fails", () => {
    const item = toLocalCard({
      id: 2,
      name: "Custom agent",
      description: "Agent description",
      tags: ["Finance"],
      icon_url: "/stored-icon?v=revision-2",
      current_version_no: 12,
    } as unknown as Agent);
    render(
      <AgentDrawer
        open
        onClose={vi.fn()}
        categories={[
          { key: "mine", label: "Mine", items: [{ ...item, id: "mine:2" }] },
        ]}
        selected={[]}
        onConfirm={vi.fn()}
      />
    );
    const image = document.querySelector(".ant-avatar img")!;
    expect(image.parentElement).toHaveClass("!bg-white");
    expect(screen.getByText("agent.version: 12")).toBeInTheDocument();
    const version = screen.getByText("agent.version: 12");
    const description = screen.getByText("Agent description");
    expect(version).not.toHaveClass("ant-tag");
    expect(version.parentElement).toContainElement(
      screen.getByText("Custom agent")
    );
    expect(version.compareDocumentPosition(description)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(
      description.compareDocumentPosition(screen.getByText("Finance"))
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.queryByText("agentConfig.list.online")).toBeNull();
    expect(image).toHaveAttribute(
      "src",
      API_ENDPOINTS.agent.icon(2, "revision-2")
    );
    fireEvent.error(image);
    expect(document.querySelector(".ant-avatar")).toHaveClass(
      "!bg-primary/10",
      "!text-primary"
    );
    expect(
      document.querySelector(".ant-avatar .lucide-wand")
    ).toBeInTheDocument();
  });

  it.each([undefined, "", "   "])(
    "assigns an ID-based icon when the stored icon is %s",
    (icon_url) => {
      const item = toLocalCard({
        id: 3,
        name: "Default agent",
        icon_url,
      } as unknown as Agent);
      render(
        <AgentDrawer
          open
          onClose={vi.fn()}
          categories={[
            { key: "mine", label: "Mine", items: [{ ...item, id: "mine:3" }] },
          ]}
          selected={[]}
          onConfirm={vi.fn()}
        />
      );
      expect(document.querySelector(".ant-avatar img")).toBeNull();
      expect(document.querySelector(".ant-avatar")).toHaveClass(
        "!bg-primary/10",
        "!text-primary"
      );
      expect(
        document.querySelector(".ant-avatar .lucide-lightbulb")
      ).toBeInTheDocument();
    }
  );

  it("shows caller loading errors and permits refresh without submitting a selection", () => {
    const confirm = vi.fn();
    const refresh = vi.fn();
    render(
      <AgentDrawer
        open
        onClose={vi.fn()}
        categories={[{ ...categories[0], error: "Catalog unavailable" }]}
        selected={[]}
        onConfirm={confirm}
        onRefresh={refresh}
      />
    );
    expect(screen.getByText("Catalog unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    expect(refresh).toHaveBeenCalledOnce();
    expect(confirm).not.toHaveBeenCalled();
  });
  it("keeps a cross-category draft, submits only on confirmation and retains it after rejection", async () => {
    const confirm = vi
      .fn()
      .mockRejectedValueOnce(new Error("Try again"))
      .mockResolvedValueOnce(undefined);
    const close = vi.fn();
    render(
      <AgentDrawer
        open
        onClose={close}
        categories={categories}
        selected={[]}
        onConfirm={confirm}
      />
    );
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Repository" }));
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await screen.findByText("Try again");
    expect(close).not.toHaveBeenCalled();
    expect(confirm.mock.calls[0][0]).toEqual([
      { id: "local:1", label: "My agent" },
      { id: "repo:1", label: "Repository agent" },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(confirm.mock.calls[1][0]).toEqual(confirm.mock.calls[0][0]);
  });

  it("cancel and reopen restores caller selection instead of an abandoned draft", () => {
    const confirm = vi.fn();
    const close = vi.fn();
    const props = {
      onClose: close,
      categories,
      selected: [],
      onConfirm: confirm,
    };
    const view = render(<AgentDrawer {...props} open />);
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getAllByRole("button", { name: "关闭" })[0]);
    expect(close).toHaveBeenCalledOnce();
    expect(confirm).not.toHaveBeenCalled();
    view.rerender(<AgentDrawer {...props} open={false} />);
    view.rerender(<AgentDrawer {...props} open />);
    expect(screen.getAllByRole("checkbox")[1]).toHaveAttribute(
      "aria-checked",
      "false"
    );
  });
});
