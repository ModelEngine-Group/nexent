// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider, Drawer, Modal } from "antd";
import { useState } from "react";
import { expect, test, vi } from "vitest";
import ResourceRepositoryPage from "@/app/resource-space/page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ locale: "en" }),
  usePathname: () => "/en/resource-space",
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams("tab=agent"),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@tanstack/react-query", () => {
  const client = { removeQueries: vi.fn() };
  return { useQueryClient: () => client };
});
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    isAuthzReady: true,
    canAccessRoute: () => true,
  }),
}));
vi.mock("@/app/resource-space/skill/skill-space", () => ({
  SkillSpace: () => null,
}));
vi.mock("@/app/resource-space/skill/my-skill", () => ({ MySkill: () => null }));
vi.mock("@/app/resource-space/mcp/mcp-space", () => ({ McpSpace: () => null }));
vi.mock("@/app/resource-space/mcp/my-mcp", () => ({ MyMcp: () => null }));
vi.mock("@/app/resource-space/components/ResourceReviewCenter", () => ({
  default: () => null,
}));
vi.mock("@/app/resource-space/agent/agent-space", () => ({
  AgentSpace: function OverlayFixture() {
    const [drawerOpen, setDrawerOpen] = useState(true);
    const [modalOpen, setModalOpen] = useState(false);
    return (
      <>
        <button onClick={() => setModalOpen(true)}>Open dialog</button>
        <Drawer
          title="Repository drawer"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
        >
          <button>Inside drawer</button>
        </Drawer>
        <Modal
          title="Repository dialog"
          open={modalOpen}
          onCancel={() => setModalOpen(false)}
        >
          <button>Inside dialog</button>
        </Modal>
      </>
    );
  },
}));

test("repository overlays close from the backdrop under the app defaults", async () => {
  render(
    <ConfigProvider
      drawer={{ mask: { closable: false } }}
      modal={{ mask: { closable: false } }}
    >
      <ResourceRepositoryPage />
    </ConfigProvider>
  );
  const insideDrawer = await screen.findByRole("button", {
    name: "Inside drawer",
  });
  fireEvent.click(insideDrawer);
  expect(insideDrawer).toBeVisible();
  fireEvent.click(document.querySelector(".ant-drawer-mask")!);
  expect(
    screen.queryByRole("dialog", { name: "Repository drawer" })
  ).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
  const insideDialog = await screen.findByRole("button", {
    name: "Inside dialog",
  });
  await waitFor(() => expect(insideDialog).toBeVisible());
  fireEvent.click(insideDialog);
  expect(insideDialog).toBeVisible();
  const backdrop = document.querySelector(".ant-modal-wrap")!;
  fireEvent.mouseDown(backdrop);
  fireEvent.click(backdrop);
  expect(
    screen.queryByRole("dialog", { name: "Repository dialog" })
  ).toBeNull();
});
