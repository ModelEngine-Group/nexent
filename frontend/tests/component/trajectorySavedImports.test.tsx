// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "zh" } }),
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
  await waitFor(() => expect(api.deleteImport).toHaveBeenCalledWith("one"));
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
