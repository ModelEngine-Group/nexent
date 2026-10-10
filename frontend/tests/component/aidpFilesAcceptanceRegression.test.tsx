import { App, Modal } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import AidpKnowledgeFilesPage from "@/ext_components/aidp/components/AidpKnowledgeFilesPage";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import { ApiError } from "@/services/api";

const mocks = vi.hoisted(() => ({
  t: (key: string, options?: { defaultValue: string }) =>
    key === "errorCode.130504" ? "认证失败" : options?.defaultValue || key,
  groups: [],
  getKb: vi.fn(),
  listIngestedFiles: vi.fn(),
  removeDoc: vi.fn(),
  message: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mocks.t, i18n: { language: "zh" } }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { id: "admin", tenantId: "tenant" },
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ enableAidpKnowledge: true, isDeploymentReady: true }),
}));
vi.mock("@/ext_components/aidp/services/aidpKnowledgeService", () => ({
  default: mocks,
}));
vi.mock("@/ext_components/aidp/hooks/useAidpGroupOptions", () => ({
  useAidpGroupOptions: () => ({ groupOptions: mocks.groups }),
}));
vi.mock("@/ext_components/aidp/components/AidpUpdateKbModal", () => ({
  default: () => null,
}));
vi.mock("@/ext_components/aidp/components/AidpImportDrawer", () => ({
  default: ({
    open,
    onClose,
    onRefresh,
    onDocsUploaded,
  }: {
    open: boolean;
    onClose: () => void;
    onRefresh: () => void;
    onDocsUploaded: (ids: string[]) => void;
  }) =>
    open ? (
      <>
        <button
          onClick={() => {
            onRefresh();
            onDocsUploaded(["1"]);
          }}
        >
          finish upload
        </button>
        <button onClick={onClose}>close import</button>
      </>
    ) : null,
}));
const kb = {
  kds_id: "kb-1",
  kds_name: "测试知识库",
  permission: "EDIT",
} as AidpKnowledgeBaseItem;
const list = (name = "文件.pdf", total = 1) => ({
  value: [
    { file_uuid: "1", file_ino_no: "1", file_name: name, file_type: "pdf" },
  ],
  total_count: total,
});
const clients: QueryClient[] = [];
function page() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AidpKnowledgeFilesPage
        knowledgeBase={kb}
        onBack={vi.fn()}
        onDelete={vi.fn()}
        onUpdated={vi.fn()}
      />
    </QueryClientProvider>
  );
}
beforeEach(() => {
  mocks.getKb.mockResolvedValue(kb);
  mocks.listIngestedFiles.mockReset().mockResolvedValue(list());
  vi.spyOn(App, "useApp").mockReturnValue({
    message: mocks.message,
  } as unknown as ReturnType<typeof App.useApp>);
});
afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
  vi.restoreAllMocks();
});
function captureConfirm() {
  let options: Parameters<typeof Modal.confirm>[0];
  vi.spyOn(Modal, "confirm").mockImplementation((value) => {
    options = value;
    return { destroy: vi.fn(), update: vi.fn() };
  });
  return () => options;
}

it("requests once on entry and refreshes only once on closing the import drawer", async () => {
  page();
  await screen.findByText("文件.pdf");
  expect(mocks.listIngestedFiles).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen.getByRole("button", { name: /aidpKnowledge.importFile/ })
  );
  mocks.listIngestedFiles.mockClear();
  fireEvent.click(screen.getByText("finish upload"));
  expect(mocks.listIngestedFiles).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("close import"));
  await waitFor(() => expect(mocks.listIngestedFiles).toHaveBeenCalledTimes(1));
});
it("does not let a late old search overwrite the new search", async () => {
  let finishOld!: (value: ReturnType<typeof list>) => void;
  mocks.listIngestedFiles.mockImplementation((_id, _page, _size, keyword) =>
    keyword === "old"
      ? new Promise((resolve) => {
          finishOld = resolve;
        })
      : Promise.resolve(list(keyword === "new" ? "new.pdf" : "文件.pdf"))
  );
  page();
  await screen.findByText("文件.pdf");
  const search = screen.getByPlaceholderText("aidpKnowledge.detailFileSearch");
  fireEvent.change(search, { target: { value: "old" } });
  await waitFor(() =>
    expect(mocks.listIngestedFiles).toHaveBeenLastCalledWith(
      "kb-1",
      1,
      10,
      "old",
      expect.any(AbortSignal)
    )
  );
  fireEvent.change(search, { target: { value: "new" } });
  await screen.findByText("new.pdf");
  await act(async () => finishOld(list("old.pdf")));
  expect(screen.queryByText("old.pdf")).toBeNull();
  expect(screen.getByText("new.pdf")).toBeVisible();
});
it("retains rows and shows the interface reason after a failed refresh, then recovers using refresh", async () => {
  page();
  await screen.findByText("文件.pdf");
  mocks.listIngestedFiles.mockRejectedValueOnce(
    new ApiError(502, "解析服务不可用")
  );
  fireEvent.click(
    screen.getByRole("button", { name: "aidpKnowledge.refresh" })
  );
  expect(await screen.findByText("解析服务不可用")).toBeVisible();
  expect(screen.getByText("文件.pdf")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "aidpKnowledge.retry" })
  ).toBeNull();
  mocks.listIngestedFiles.mockResolvedValue(list("恢复.pdf"));
  fireEvent.click(
    screen.getByRole("button", { name: "aidpKnowledge.refresh" })
  );
  await screen.findByText("恢复.pdf");
  expect(screen.queryByText("解析服务不可用")).toBeNull();
});
it("shows a translated query error rather than normal empty state", async () => {
  mocks.listIngestedFiles.mockRejectedValue(
    new ApiError("130504", "Unauthorized")
  );
  page();
  expect(await screen.findByText("认证失败")).toBeVisible();
  expect(screen.queryByText("aidpKnowledge.detailFilesEmpty")).toBeNull();
});
it("uses the same empty state with and without a search term", async () => {
  mocks.listIngestedFiles.mockResolvedValue({ value: [], total_count: 0 });
  page();
  await screen.findByText("aidpKnowledge.detailFilesEmpty");
  fireEvent.change(
    screen.getByPlaceholderText("aidpKnowledge.detailFileSearch"),
    { target: { value: "missing" } }
  );
  await waitFor(() =>
    expect(mocks.listIngestedFiles).toHaveBeenLastCalledWith(
      "kb-1",
      1,
      10,
      "missing",
      expect.any(AbortSignal)
    )
  );
  expect(screen.getByText("aidpKnowledge.detailFilesEmpty")).toBeVisible();
});
it("rejects a per-file deletion failure and preserves its translated error", async () => {
  const options = captureConfirm();
  mocks.removeDoc.mockResolvedValue({
    summary: { total: 1, success: 0, failed: 1 },
    success_list: [],
    failed_list: [{ file_uuid: "1", code: "130504", message: "Unauthorized" }],
  });
  page();
  await screen.findByText("文件.pdf");
  fireEvent.click(screen.getByRole("button", { name: "common.delete" }));
  await act(async () => {
    await expect(options().onOk?.()).rejects.toThrow("Unauthorized");
  });
  expect(mocks.message.error).toHaveBeenCalledWith("认证失败");
  expect(mocks.message.success).not.toHaveBeenCalled();
  expect(screen.getByText("文件.pdf")).toBeVisible();
});
it("returns to a valid page after removing the last file on the final page", async () => {
  const options = captureConfirm();
  let deleted = false;
  mocks.listIngestedFiles.mockImplementation((_id, page) =>
    Promise.resolve(
      page === 2
        ? deleted
          ? { value: [], total_count: 10 }
          : list("末页.pdf", 11)
        : list("第一页.pdf", deleted ? 10 : 11)
    )
  );
  mocks.removeDoc.mockImplementation(async () => {
    deleted = true;
    return {
      summary: { total: 1, success: 1, failed: 0 },
      success_list: [{ file_uuid: "1" }],
      failed_list: [],
    };
  });
  page();
  await screen.findByText("第一页.pdf");
  fireEvent.click(screen.getByRole("button", { name: "right" }));
  await screen.findByText("末页.pdf");
  fireEvent.click(screen.getByRole("button", { name: "common.delete" }));
  await act(async () => {
    await options().onOk?.();
  });
  expect(await screen.findByText("第一页.pdf")).toBeVisible();
  expect(mocks.listIngestedFiles).toHaveBeenLastCalledWith(
    "kb-1",
    1,
    10,
    "",
    expect.any(AbortSignal)
  );
});
