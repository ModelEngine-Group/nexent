import type { PropsWithChildren } from "react";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AidpKnowledgeConfiguration from "@/ext_components/aidp/components/AidpKnowledgeConfiguration";

const service = vi.hoisted(() => ({
  listKbs: vi.fn(),
  deleteKb: vi.fn(),
}));
vi.mock("@/ext_components/aidp/services/aidpKnowledgeService", () => ({
  default: service,
}));
vi.mock("@/ext_components/aidp/components/AidpImportDrawer", () => ({
  default: ({
    onClose,
    onDocsUploaded,
    onRefresh,
  }: {
    onClose: () => void;
    onDocsUploaded: (ids: string[]) => void;
    onRefresh: () => void;
  }) => (
    <>
      <button
        onClick={() => {
          onRefresh();
          onDocsUploaded(["uploaded-file"]);
        }}
      >
        finish test upload
      </button>
      <button onClick={onClose}>close drawer with confirm</button>
      <button onClick={onClose}>close drawer with X</button>
    </>
  ),
}));

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "zh" } }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ locale: "zh" }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { id: "admin", tenantId: "tenant", role: "admin" },
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ enableAidpKnowledge: true, isDeploymentReady: true }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
}));
vi.mock("@/components/permission/Can", () => ({
  Can: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/hooks/useErrorHandler", () => ({
  useErrorHandler: () => ({
    getI18nErrorMessage: vi.fn(),
    handleError: (error: Error) => ({ message: error.message }),
  }),
}));

const makeTree = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: PropsWithChildren) => (
    <App>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </App>
  );
  return render(<AidpKnowledgeConfiguration />, { wrapper: Wrapper });
};

beforeEach(() => {
  window.sessionStorage.clear();
  service.listKbs.mockResolvedValue({
    value: [{ kds_id: "kb-1", kds_name: "测试知识库", permission: "EDIT" }],
    total_count: 1,
  });
});
afterEach(() => window.sessionStorage.clear());

describe("knowledge list view preference", () => {
  it("restores the table view when the knowledge page mounts again", async () => {
    const first = makeTree();
    await screen.findByText("测试知识库");
    fireEvent.click(screen.getByTitle("aidpKnowledge.viewTable"));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "aidpKnowledge.columnSettings" })
      ).toBeVisible()
    );
    first.unmount();

    makeTree();
    await screen.findByText("测试知识库");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "aidpKnowledge.columnSettings" })
      ).toBeVisible()
    );
  });

  it("refreshes only when the import drawer closes after upload completion", async () => {
    makeTree();
    await screen.findByText("测试知识库");
    service.listKbs.mockClear();

    fireEvent.click(
      screen.getByRole("button", { name: "aidpKnowledge.moreOperations" })
    );
    fireEvent.click(await screen.findByText("aidpKnowledge.importFile"));
    fireEvent.click(
      await screen.findByRole("button", { name: "finish test upload" })
    );
    expect(service.listKbs).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "close drawer with confirm" })
    );

    await waitFor(() => expect(service.listKbs).toHaveBeenCalledTimes(1));
  });

  it("refreshes the list when the import drawer closes with X", async () => {
    makeTree();
    await screen.findByText("测试知识库");
    service.listKbs.mockClear();

    fireEvent.click(
      screen.getByRole("button", { name: "aidpKnowledge.moreOperations" })
    );
    fireEvent.click(await screen.findByText("aidpKnowledge.importFile"));
    fireEvent.click(
      await screen.findByRole("button", { name: "close drawer with X" })
    );

    await waitFor(() => expect(service.listKbs).toHaveBeenCalledTimes(1));
  });
});
