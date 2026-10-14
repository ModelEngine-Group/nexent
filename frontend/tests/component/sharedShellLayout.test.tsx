import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { ClientLayout } from "../../app/[locale]/layout.client";

const state = vi.hoisted(() => ({
  pathname: "/zh/models",
  authorized: true,
  speed: false,
}));
vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ isAuthorized: state.authorized }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ isSpeedMode: state.speed }),
}));
vi.mock("@/components/navigation/SideNavigation", () => ({
  SideNavigation: () => <nav>sidebar</nav>,
}));
vi.mock("@/components/auth/AuthDialogs", () => ({
  AuthDialogs: () => <div>auth dialogs</div>,
}));
vi.mock("@/components/quota/QuotaWarningMonitor", () => ({
  QuotaWarningMonitor: () => null,
}));
vi.mock("@/components/memory/MemoryEmbeddingMonitor", () => ({
  MemoryEmbeddingMonitor: () => null,
}));

beforeEach(() => {
  state.authorized = true;
  state.speed = false;
});

test.each([
  "/zh",
  "/zh/models",
  "/en/knowledges",
  "/zh/memory",
  "/zh/agent-space",
  "/zh/agents/1",
  "/zh/newchat",
])("shared shell %s reserves no global header/footer space", (path) => {
  state.pathname = path;
  const { container } = render(
    <ClientLayout>
      <main>page content</main>
    </ClientLayout>
  );
  expect(screen.getByText("page content")).toBeVisible();
  expect(screen.getByRole("navigation")).toBeVisible();
  expect(container.querySelector("header, footer")).toBeNull();
  expect(screen.getByText("auth dialogs")).toBeVisible();
});

test("unauthorized protected content stays hidden; home and OAuth completion stay public", () => {
  state.authorized = false;
  state.pathname = "/zh/models";
  const { rerender } = render(
    <ClientLayout>
      <main>page content</main>
    </ClientLayout>
  );
  expect(screen.queryByText("page content")).toBeNull();
  state.pathname = "/zh";
  rerender(
    <ClientLayout>
      <main>page content</main>
    </ClientLayout>
  );
  expect(screen.getByText("page content")).toBeVisible();
  state.pathname = "/zh/oauth/complete";
  rerender(
    <ClientLayout>
      <main>page content</main>
    </ClientLayout>
  );
  expect(screen.getByText("page content")).toBeVisible();
});

test("share stays standalone and speed mode hides auth dialogs", () => {
  state.pathname = "/zh/share/example";
  state.authorized = false;
  const { rerender } = render(
    <ClientLayout>
      <main>share content</main>
    </ClientLayout>
  );
  expect(screen.getByText("share content")).toBeVisible();
  expect(screen.queryByRole("navigation")).toBeNull();
  expect(screen.getByText("auth dialogs")).toBeVisible();
  state.speed = true;
  rerender(
    <ClientLayout>
      <main>share content</main>
    </ClientLayout>
  );
  expect(screen.queryByText("auth dialogs")).toBeNull();
});
