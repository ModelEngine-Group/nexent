// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { ResourceDenylistPanel } from "@/components/resource-picker/ResourceDenylistPanel";

const api = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn() }));
vi.mock("@/services/resourceDenylistService", () => ({
  loadResourceDenylist: api.load,
  saveResourceDenylist: api.save,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const snapshot = {
  items: [
    {
      key: "mcp:12",
      name: "Enterprise",
      resource_type: "mcp",
      description: "Enterprise search service",
    },
    {
      key: "tool:98",
      name: "search",
      resource_type: "tool",
      source: "mcp",
      service: "Enterprise",
      parent_key: "mcp:12",
    },
    {
      key: "tool:99",
      name: "local_lookup",
      resource_type: "tool",
      source: "local",
      service: "System",
    },
    {
      key: "tool:100",
      name: "orphan_mcp_tool",
      resource_type: "tool",
      source: "mcp",
    },
    {
      key: "skill:34",
      name: "research",
      resource_type: "skill",
      description: "Analyze publications",
    },
    {
      key: "mcp:15",
      name: "Platform service",
      resource_type: "mcp",
      global_blocked: true,
    },
  ],
  selected: [],
  revision: "tenant-revision",
};
beforeEach(() => {
  api.load.mockResolvedValue(snapshot);
  api.save.mockResolvedValue({ ...snapshot, selected: ["mcp:12", "skill:34"] });
});
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ResourceDenylistPanel scope="tenant" tenantId="tenant-a" />
    </QueryClientProvider>
  );
}
async function open(category = "mcp") {
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "resourceDenylist.details" })
    ).toBeEnabled()
  );
  fireEvent.click(
    screen.getByRole("button", { name: "resourceDenylist.details" })
  );
  if (category === "mcp")
    fireEvent.click(screen.getByRole("tab", { name: "MCP" }));
}

test("local and MCP tabs separate tool sources and preserve selections between tabs", async () => {
  mount();
  await open("local");
  expect(
    screen.getByRole("tab", { name: "toolPool.group.local" })
  ).toHaveAttribute("aria-selected", "true");
  expect(
    screen.queryByRole("checkbox", { name: "Enterprise" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("checkbox", { name: "orphan_mcp_tool" })
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "System / local_lookup" })
  );
  fireEvent.click(screen.getByRole("tab", { name: "MCP" }));
  expect(
    screen.queryByRole("checkbox", { name: "System / local_lookup" })
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "orphan_mcp_tool" }));
  fireEvent.click(screen.getByRole("tab", { name: "toolPool.group.local" }));
  expect(
    screen.getByRole("checkbox", { name: "System / local_lookup" })
  ).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(api.save).toHaveBeenCalledWith("tenant", "tenant-revision", [
      "tool:99",
      "tool:100",
    ])
  );
});

test("configuration table opens a shared drawer and saves MCP services and skills", async () => {
  mount();
  expect(
    screen.getByText("resourceDenylist.blockedResources")
  ).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "resourceDenylist.add" })
  ).not.toBeInTheDocument();
  await open();
  expect(
    screen.getByRole("dialog", { name: "resourceDenylist.drawerTitle" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: "resourceDenylist.all" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: /智能体|Agent/ })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("checkbox", { name: "Platform service" })
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "Platform service" })
  ).toBeDisabled();
  fireEvent.click(screen.getByText("Enterprise", { exact: true }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Enterprise" }));
  expect(
    screen.getByRole("checkbox", { name: "Enterprise / search" })
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "Enterprise / search" })
  ).toBeDisabled();
  fireEvent.click(
    screen.getByRole("tab", { name: "resourceDenylist.kind.skill" })
  );
  fireEvent.click(screen.getByRole("checkbox", { name: "research" }));
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(api.save).toHaveBeenCalledWith("tenant", "tenant-revision", [
      "mcp:12",
      "skill:34",
    ])
  );
});

test("individual MCP tool selection survives cancelling its service selection", async () => {
  mount();
  await open();
  fireEvent.click(screen.getByText("Enterprise", { exact: true }));
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Enterprise / search" })
  );
  fireEvent.click(
    screen.getByRole("switch", { name: "resourceDenylist.onlyBlocked" })
  );
  expect(
    screen.getByRole("button", { name: /^Enterprise$/ })
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("switch", { name: "resourceDenylist.onlyBlocked" })
  );
  fireEvent.click(screen.getByRole("checkbox", { name: "Enterprise" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Enterprise" }));
  expect(
    screen.getByRole("checkbox", { name: "Enterprise / search" })
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "Enterprise / search" })
  ).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(api.save).toHaveBeenCalledWith("tenant", "tenant-revision", [
      "tool:98",
    ])
  );
});

test("description search and cancel do not persist an unsaved selection", async () => {
  mount();
  await open();
  fireEvent.click(
    screen.getByRole("tab", { name: "resourceDenylist.kind.skill" })
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: "resourceDenylist.search" }),
    { target: { value: "publications" } }
  );
  expect(
    screen.getByRole("checkbox", { name: "research" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("checkbox", { name: "Enterprise" })
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "research" }));
  fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
  expect(api.save).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "resourceDenylist.details" })
  );
  fireEvent.click(
    screen.getByRole("tab", { name: "resourceDenylist.kind.skill" })
  );
  expect(
    await screen.findByRole("checkbox", { name: "research" })
  ).not.toBeChecked();
});

test("save failure retains selected resources and permits retry", async () => {
  api.save.mockRejectedValue(new Error("Conflict"));
  mount();
  await open();
  fireEvent.click(
    screen.getByRole("tab", { name: "resourceDenylist.kind.skill" })
  );
  fireEvent.click(screen.getByRole("checkbox", { name: "research" }));
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  expect(
    await screen.findByText("resourceDenylist.saveFailed")
  ).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "research" })).toBeChecked();
  expect(screen.getByRole("button", { name: "common.confirm" })).toBeEnabled();
});

test.each([
  { label: "identical cached snapshot and revision", latest: snapshot },
  {
    label: "changed catalog with unchanged revision",
    latest: {
      ...snapshot,
      items: snapshot.items.filter((item) => item.key !== "tool:99"),
    },
  },
  {
    label: "changed server selection and revision",
    latest: {
      ...snapshot,
      selected: ["skill:34"],
      revision: "latest-revision",
    },
  },
])("reload discards unsaved selections using $label", async ({ latest }) => {
  api.load.mockResolvedValueOnce(snapshot).mockResolvedValue(latest);
  api.save.mockRejectedValue(new Error("Save failed"));
  mount();
  await open("local");
  fireEvent.click(
    screen.getByRole("checkbox", { name: "System / local_lookup" })
  );
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await screen.findByText("resourceDenylist.saveFailed");
  fireEvent.click(
    screen.getByRole("button", { name: "resourceDenylist.reload" })
  );
  await waitFor(() =>
    expect(
      screen.queryByText("resourceDenylist.saveFailed")
    ).not.toBeInTheDocument()
  );
  if (latest.items.some((item) => item.key === "tool:99")) {
    expect(
      screen.getByRole("checkbox", { name: "System / local_lookup" })
    ).not.toBeChecked();
  } else {
    expect(
      screen.queryByRole("checkbox", { name: "System / local_lookup" })
    ).not.toBeInTheDocument();
  }
  expect(screen.getByRole("button", { name: "common.confirm" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("tab", { name: "resourceDenylist.kind.skill" })
  );
  expect(screen.getByRole("checkbox", { name: "research" })).toHaveProperty(
    "checked",
    latest.selected.includes("skill:34")
  );
  expect(api.save).toHaveBeenCalledTimes(1);
  expect(api.load).toHaveBeenCalledTimes(2);
});

test("failed reload retains the unsaved draft and save error", async () => {
  api.save.mockRejectedValue(new Error("Save failed"));
  mount();
  await open("local");
  fireEvent.click(
    screen.getByRole("checkbox", { name: "System / local_lookup" })
  );
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await screen.findByText("resourceDenylist.saveFailed");
  api.load.mockRejectedValue(new Error("Reload unavailable"));
  fireEvent.click(
    screen.getByRole("button", { name: "resourceDenylist.reload" })
  );
  await screen.findByText("resourceDenylist.loadFailed");
  expect(
    screen.getByRole("checkbox", { name: "System / local_lookup" })
  ).toBeChecked();
  expect(screen.getByText("resourceDenylist.saveFailed")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "common.confirm" })).toBeEnabled();
  expect(api.save).toHaveBeenCalledTimes(1);
});

test("global and tenant selections share type groups with locked platform chips", async () => {
  api.load.mockResolvedValue({
    ...snapshot,
    items: [
      ...snapshot.items,
      {
        key: "tool:201",
        name: "global_local",
        resource_type: "tool",
        source: "local",
        global_blocked: true,
      },
      {
        key: "tool:202",
        name: "global_remote",
        resource_type: "tool",
        source: "mcp",
        service: "Global service",
        global_blocked: true,
      },
      {
        key: "skill:203",
        name: "global_skill",
        resource_type: "skill",
        global_blocked: true,
      },
      {
        key: "tool:204",
        name: "inherited_child",
        resource_type: "tool",
        source: "mcp",
        parent_key: "mcp:15",
        global_blocked: true,
      },
    ],
    selected: ["tool:99", "tool:98", "mcp:12", "skill:34", "tool:201"],
  });
  mount();
  await open();
  const summary = screen.getByTestId("resource-denylist-summary");
  expect(
    within(screen.getByRole("table")).getByText(
      "resourceDenylist.summary.mcpTool 2"
    )
  ).toBeInTheDocument();
  expect(within(summary).queryByRole("region")).not.toBeInTheDocument();
  expect(
    within(summary).queryByText("resourceDenylist.summary.global")
  ).not.toBeInTheDocument();
  expect(
    within(summary).queryByText("resourceDenylist.summary.tenant")
  ).not.toBeInTheDocument();
  const local = within(summary).getByRole("group", {
    name: "resourceDenylist.summary.local",
  });
  expect(local).toHaveTextContent("global_local");
  expect(local).toHaveTextContent("local_lookup");
  const services = within(summary).getByRole("group", {
    name: "resourceDenylist.summary.mcpService",
  });
  expect(services).toHaveTextContent("Platform service");
  expect(services).toHaveTextContent("Enterprise");
  const tools = within(summary).getByRole("group", {
    name: "resourceDenylist.summary.mcpTool",
  });
  expect(tools).toHaveTextContent("Global service / global_remote");
  expect(tools).toHaveTextContent("Enterprise / search");
  const skills = within(summary).getByRole("group", {
    name: "resourceDenylist.summary.skill",
  });
  expect(skills).toHaveTextContent("global_skill");
  expect(skills).toHaveTextContent("research");
  expect(
    within(summary).queryByText("inherited_child")
  ).not.toBeInTheDocument();
  expect(
    within(summary).getAllByRole("img", {
      name: "resourceDenylist.globalBlocked",
    })
  ).toHaveLength(4);
  const lockedTag = within(summary)
    .getByText("global_local")
    .closest(".ant-tag") as HTMLElement;
  expect(within(lockedTag).queryByRole("button")).not.toBeInTheDocument();
  expect(
    within(lockedTag).getByRole("img", {
      name: "resourceDenylist.globalBlocked",
    })
  ).toBeInTheDocument();
  fireEvent.click(
    within(summary).getByRole("button", { name: "resourceDenylist.clear" })
  );
  expect(within(summary).getByText("global_local")).toBeInTheDocument();
  expect(within(summary).queryByText("local_lookup")).not.toBeInTheDocument();
  expect(
    within(summary).queryByText("Enterprise / search")
  ).not.toBeInTheDocument();
  expect(
    within(summary).getByRole("button", { name: "resourceDenylist.clear" })
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(api.save).toHaveBeenCalledWith("tenant", "tenant-revision", [
      "tool:201",
    ])
  );
});

test("MCP disclosure uses an independent expand button and leaves selections unchanged", async () => {
  mount();
  await open();
  const expand = screen.getByRole("button", {
    name: /^Enterprise$/,
  });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(expand);
  expect(expand).toHaveAttribute("aria-expanded", "true");
  expect(
    screen.getByRole("checkbox", { name: "Enterprise" })
  ).not.toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "Enterprise / search" })
  ).not.toBeChecked();
  fireEvent.click(expand);
  expect(expand).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.queryByRole("checkbox", { name: "Enterprise / search" })
  ).not.toBeInTheDocument();
  expect(api.save).not.toHaveBeenCalled();
});
