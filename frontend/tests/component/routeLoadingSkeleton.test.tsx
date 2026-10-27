// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Suspense, use, useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RouteLoadingSkeleton } from "@/components/common/RouteLoadingSkeleton";
import { RouteTransitionContent } from "@/components/navigation/RouteTransitionContent";
import { ClientLayout } from "@/app/layout.client";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/zh/agents",
  useRouter: () => navigation,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ isAuthorized: true }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ isSpeedMode: true }),
}));
vi.mock("@/components/auth/AuthDialogs", () => ({ AuthDialogs: () => null }));
vi.mock("@/components/quota/QuotaWarningMonitor", () => ({
  QuotaWarningMonitor: () => null,
}));
vi.mock("@/components/memory/MemoryEmbeddingMonitor", () => ({
  MemoryEmbeddingMonitor: () => null,
}));
vi.mock("@/components/navigation/SideNavigation", () => ({
  SideNavigation: ({ onNavigate }: { onNavigate: (path: string) => void }) => (
    <nav>
      <button onClick={() => onNavigate("/zh/models")}>models</button>
      <button onClick={() => onNavigate("/zh/resource-manage")}>
        resources
      </button>
      <button onClick={() => onNavigate("/zh/agents")}>current</button>
      <button onClick={() => onNavigate("/zh/error")}>error</button>
    </nav>
  ),
}));

it.each([
  ["/zh/models", "configuration", "sidebar.modelConfig"],
  ["/en/resource-manage", "table", "sidebar.resourceManage"],
  ["/zh/knowledges", "cards", "sidebar.knowledgeBaseConfig"],
  ["/zh/aidp-knowledges", "split", "sidebar.knowledgeBaseConfig"],
  ["/zh/mcp-space", "cards", "sidebar.mcpSpace"],
  ["/zh/workbench", "conversation", "sidebar.agentWorkbench"],
  ["/en/newchat", "conversation", "sidebar.startChat"],
])(
  "renders placeholders including the title for %s",
  (pathname, layout, title) => {
    render(<RouteLoadingSkeleton pathname={pathname} />);
    const status = screen.getByRole("status", { name: "common.loading" });
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveAttribute("data-layout", layout);
    expect(status.textContent).toBe(title);
    expect(screen.getByRole("heading")).toHaveTextContent(title);
    expect(
      screen.getByRole("heading").querySelector(".sr-only")
    ).toHaveTextContent(title);
    expect(
      screen.getByRole("heading").querySelector(".route-skeleton-title")
    ).toBeInTheDocument();
    expect(
      status.querySelectorAll(".route-skeleton-bone").length
    ).toBeGreaterThan(5);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  }
);

it("falls back for unknown routes and uses current path when no target is supplied", () => {
  const { rerender } = render(<RouteLoadingSkeleton pathname="/zh/unknown" />);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  expect(screen.getByRole("status").textContent).toBe("");
  expect(
    screen.getByRole("status").querySelector(".route-skeleton-title")
  ).toBeInTheDocument();
  rerender(<RouteLoadingSkeleton pathname="/zh/users" />);
  expect(screen.getByRole("status")).toHaveAttribute("data-layout", "table");
  expect(
    screen.getByRole("status").querySelector(".route-skeleton-title")
  ).toBeInTheDocument();
  rerender(<RouteLoadingSkeleton />);
  expect(screen.getByRole("heading")).toHaveTextContent("sidebar.agentConfig");
});

it("preserves mounted drafts while making source content inert, then exposes settled errors", () => {
  const content = <input aria-label="draft" defaultValue="unsaved" />;
  const { rerender } = render(
    <RouteTransitionContent pendingPath={null}>
      {content}
    </RouteTransitionContent>
  );
  const draft = screen.getByRole("textbox");
  rerender(
    <RouteTransitionContent pendingPath="/zh/models">
      {content}
    </RouteTransitionContent>
  );
  expect(draft.parentElement).toHaveAttribute("inert");
  expect(draft.parentElement).toHaveAttribute("aria-hidden", "true");
  expect(draft).not.toBeVisible();
  rerender(
    <RouteTransitionContent pendingPath={null}>
      {content}
    </RouteTransitionContent>
  );
  expect(screen.getByRole("textbox")).toBe(draft);
  expect(draft).toHaveValue("unsaved");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  rerender(
    <RouteTransitionContent pendingPath={null}>
      <p role="alert">route failed</p>
    </RouteTransitionContent>
  );
  expect(screen.getByRole("alert")).toBeVisible();
});

it("tracks actual React route transitions, latest target, same-route selection and settled failure", async () => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  function Destination({ path }: { path: string }) {
    if (path === "/zh/models" || path === "/zh/resource-manage") use(pending);
    return path === "/zh/error" ? <p role="alert">failed</p> : <p>{path}</p>;
  }
  function Harness() {
    const [path, setPath] = useState("/zh/agents");
    navigation.push.mockImplementation(setPath);
    return (
      <ClientLayout>
        <Destination path={path} />
      </ClientLayout>
    );
  }
  render(
    <Suspense fallback="initial">
      <Harness />
    </Suspense>
  );
  fireEvent.click(screen.getByText("current"));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await act(async () => {
    fireEvent.click(screen.getByText("models"));
  });
  expect(screen.getByRole("heading")).toHaveTextContent("sidebar.modelConfig");
  expect(screen.getByText("resources")).toBeEnabled();
  await act(async () => {
    fireEvent.click(screen.getByText("resources"));
  });
  expect(screen.getByRole("heading")).toHaveTextContent(
    "sidebar.resourceManage"
  );
  await act(async () => {
    release();
    await pending;
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByText("/zh/resource-manage")).toBeVisible();
  fireEvent.click(screen.getByText("error"));
  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
