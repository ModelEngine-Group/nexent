// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import type { User } from "@/types/auth";
import { trajectoryService } from "@/services/trajectoryService";
import { ImportedTrajectories } from "@/app/observability/components/ImportedTrajectories";
import { record } from "./trajectoryFixtures";

const { confirm } = vi.hoisted(() => ({ confirm: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (
      key: string,
      options?: { count?: number; done?: number; total?: number }
    ) =>
      key +
      (options?.count !== undefined ? `:${options.count}` : "") +
      (options?.done !== undefined ? `:${options.done}/${options.total}` : ""),
    i18n: { language: "zh" },
  }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: {
    savedImports: vi.fn(),
    savedImport: vi.fn(),
    saveImport: vi.fn(),
    deleteImport: vi.fn(),
  },
}));
vi.mock("@/app/observability/components/TrajectoryDrawer", () => ({
  TrajectoryDrawer: () => <div role="dialog">saved content</div>,
}));
const api = vi.mocked(trajectoryService);
const item = {
  import_id: "one",
  filename: "saved.zip",
  imported_at: "2026-11-18T00:00:00Z",
  size_bytes: 1024,
  row: record,
};
const trajectory = { row: record, pages: [], coverage: { complete: true } };
const user = { id: "admin", tenantId: "tenant", role: "OPS" } as User;
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<ImportedTrajectories user={user} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}
beforeEach(() => {
  vi.clearAllMocks();
  for (const method of [
    api.savedImports,
    api.savedImport,
    api.saveImport,
    api.deleteImport,
  ])
    method.mockReset();
  api.savedImports.mockResolvedValue({
    items: [item],
    total: 1,
    page: 1,
    page_size: 20,
  });
  api.savedImport.mockResolvedValue({ item, trajectory });
  api.saveImport.mockResolvedValue({ item, trajectory });
  api.deleteImport.mockResolvedValue({ deleted: true });
});
it("loads saved summaries and reopens without another upload", async () => {
  mount();
  expect(await screen.findByText("saved.zip")).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "trajectory.viewImport" })
  );
  expect(await screen.findByRole("dialog")).toHaveTextContent("saved content");
  expect(api.savedImport).toHaveBeenCalledWith("one", expect.any(AbortSignal));
  expect(api.saveImport).not.toHaveBeenCalled();
});
it("deletes only after confirmation and refreshes the server list", async () => {
  mount();
  await screen.findByText("saved.zip");
  fireEvent.click(
    screen.getByRole("button", { name: "trajectory.deleteImport" })
  );
  expect(api.deleteImport).not.toHaveBeenCalled();
  api.savedImports.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 20,
  });
  await act(async () => confirm.mock.calls[0][0].onOk());
  await waitFor(() =>
    expect(api.deleteImport).toHaveBeenCalledWith(
      "one",
      expect.any(AbortSignal)
    )
  );
  expect(await screen.findByText("trajectory.noImports")).toBeVisible();
});
it("shows a failed list request and retries", async () => {
  api.savedImports.mockRejectedValueOnce({ code: "import_store_busy" });
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "trajectory.retry" })
  );
  expect(await screen.findByText("saved.zip")).toBeVisible();
});
it("saves selected files and refreshes the list", async () => {
  mount();
  await screen.findByText("saved.zip");
  const input = screen.getByLabelText("trajectory.import");
  const file = new File(["zip"], "same.zip");
  fireEvent.change(input, { target: { files: [file] } });
  expect(await screen.findByRole("dialog")).toBeVisible();
  expect(api.saveImport).toHaveBeenCalledWith(file, expect.any(AbortSignal));
  await waitFor(() =>
    expect(api.savedImports.mock.calls.length).toBeGreaterThan(1)
  );
});

it("retries opening a saved record without asking for another ZIP", async () => {
  api.savedImport.mockRejectedValueOnce({ code: "import_store_busy" });
  mount();
  await screen.findByText("saved.zip");
  fireEvent.click(
    screen.getByRole("button", { name: "trajectory.viewImport" })
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "trajectory.retry" })
  );
  expect(await screen.findByRole("dialog")).toBeVisible();
  expect(api.savedImport).toHaveBeenCalledTimes(2);
  expect(api.saveImport).not.toHaveBeenCalled();
});

it("requests full-list sorting and resets the page when the sort changes", async () => {
  api.savedImports.mockImplementation(async (page) => ({
    items: [item],
    total: 21,
    page,
    page_size: 20,
  }));
  mount();
  await screen.findByText("saved.zip");
  expect(api.savedImports).toHaveBeenLastCalledWith(
    1,
    20,
    expect.any(AbortSignal),
    {
      sort_by: "imported_at",
      sort_order: "desc",
    }
  );
  fireEvent.click(within(screen.getByTitle("2")).getByRole("button"));
  await waitFor(() => expect(api.savedImports.mock.calls.at(-1)?.[0]).toBe(2));
  fireEvent.click(
    screen.getByRole("columnheader", { name: /trajectory.importFilename/ })
  );
  await waitFor(() =>
    expect(api.savedImports).toHaveBeenLastCalledWith(
      1,
      20,
      expect.any(AbortSignal),
      {
        sort_by: "filename",
        sort_order: "asc",
      }
    )
  );
  fireEvent.click(
    screen.getByRole("columnheader", { name: /trajectory.importFilename/ })
  );
  await waitFor(() =>
    expect(api.savedImports).toHaveBeenLastCalledWith(
      1,
      20,
      expect.any(AbortSignal),
      {
        sort_by: "filename",
        sort_order: "desc",
      }
    )
  );
  fireEvent.click(
    screen.getByRole("columnheader", { name: /trajectory.importedAt/ })
  );
  await waitFor(() =>
    expect(api.savedImports).toHaveBeenLastCalledWith(
      1,
      20,
      expect.any(AbortSignal),
      {
        sort_by: "imported_at",
        sort_order: "asc",
      }
    )
  );
});

it("preserves selected IDs across pages and only deletes after confirmation", async () => {
  api.savedImports.mockImplementation(async (page) => ({
    items:
      page === 1
        ? [item]
        : [{ ...item, import_id: "two", filename: "second.zip" }],
    total: 21,
    page,
    page_size: 20,
  }));
  mount();
  await screen.findByText("saved.zip");
  expect(
    screen.getByRole("button", { name: "trajectory.deleteSelected" })
  ).toBeDisabled();
  fireEvent.click(screen.getAllByRole("checkbox")[1]);
  fireEvent.click(within(screen.getByTitle("2")).getByRole("button"));
  await waitFor(() => expect(api.savedImports.mock.calls.at(-1)?.[0]).toBe(2));
  await screen.findByText("second.zip");
  fireEvent.click(screen.getAllByRole("checkbox")[1]);
  fireEvent.click(
    screen.getByRole("button", { name: "trajectory.deleteSelected" })
  );
  expect(api.deleteImport).not.toHaveBeenCalled();
  expect(confirm.mock.calls[0][0].content).toBe(
    "trajectory.deleteSelectedConfirm:2"
  );
  await act(async () => confirm.mock.calls[0][0].onOk());
  expect(api.deleteImport.mock.calls.map(([id]) => id)).toEqual(["one", "two"]);
});

it("retains failed selections and retries only the failed IDs after confirmation", async () => {
  let rows = [item, { ...item, import_id: "two", filename: "second.zip" }];
  api.savedImports.mockImplementation(async () => ({
    items: rows,
    total: rows.length,
    page: 1,
    page_size: 20,
  }));
  let fail = true;
  api.deleteImport.mockImplementation(async (id) => {
    if (id === "one" && fail) throw { code: "import_store_busy" };
    rows = rows.filter((row) => row.import_id !== id);
    return { deleted: true };
  });
  mount();
  await screen.findByText("saved.zip");
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  fireEvent.click(
    screen.getByRole("button", { name: "trajectory.deleteSelected" })
  );
  await act(async () => confirm.mock.calls[0][0].onOk());
  expect(
    await screen.findByText("trajectory.deleteImportsPartial")
  ).toBeVisible();
  await waitFor(() => expect(screen.queryByText("second.zip")).toBeNull());
  expect(screen.getAllByRole("checkbox")[1]).toBeChecked();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "trajectory.retry" }));
  expect(api.deleteImport).toHaveBeenCalledTimes(2);
  await act(async () => confirm.mock.calls[1][0].onOk());
  await screen.findByText("trajectory.noImports");
  expect(api.deleteImport.mock.calls.map(([id]) => id)).toEqual([
    "one",
    "two",
    "one",
  ]);
});

it("stops subsequent deletions when leaving during a batch", async () => {
  api.savedImports.mockResolvedValue({
    items: [item, { ...item, import_id: "two", filename: "second.zip" }],
    total: 2,
    page: 1,
    page_size: 20,
  });
  let finish!: (value: { deleted: boolean }) => void;
  api.deleteImport.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const view = mount();
  await screen.findByText("saved.zip");
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  fireEvent.click(
    screen.getByRole("button", { name: "trajectory.deleteSelected" })
  );
  let batch!: Promise<void>;
  act(() => {
    batch = confirm.mock.calls[0][0].onOk();
  });
  await waitFor(() => expect(api.deleteImport).toHaveBeenCalledTimes(1));
  const signal = api.deleteImport.mock.calls[0][1];
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => {
    finish({ deleted: true });
    await batch;
  });
  expect(api.deleteImport).toHaveBeenCalledTimes(1);
});

it("shows batch progress and blocks repeated confirmation while deleting", async () => {
  api.savedImports.mockResolvedValue({
    items: [item, { ...item, import_id: "two", filename: "second.zip" }],
    total: 2,
    page: 1,
    page_size: 20,
  });
  const pending: ((value: { deleted: boolean }) => void)[] = [];
  api.deleteImport.mockImplementation(
    () => new Promise((resolve) => pending.push(resolve))
  );
  mount();
  await screen.findByText("saved.zip");
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  fireEvent.click(
    screen.getByRole("button", { name: "trajectory.deleteSelected" })
  );
  const onOk = confirm.mock.calls[0][0].onOk;
  let batch!: Promise<void>;
  act(() => {
    batch = onOk();
  });
  expect(
    await screen.findByText("trajectory.deletingImports:0/2")
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: /trajectory.deleteSelected/ })
  ).toBeDisabled();
  expect(screen.getAllByRole("checkbox")[0]).toBeDisabled();
  await act(async () => onOk());
  expect(api.deleteImport).toHaveBeenCalledTimes(1);
  await act(async () => pending[0]({ deleted: true }));
  expect(
    await screen.findByText("trajectory.deletingImports:1/2")
  ).toBeVisible();
  expect(api.deleteImport.mock.calls.map(([id]) => id)).toEqual(["one", "two"]);
  await act(async () => {
    pending[1]({ deleted: true });
    await batch;
  });
  expect(await screen.findByText("trajectory.selectedImports:0")).toBeVisible();
});
