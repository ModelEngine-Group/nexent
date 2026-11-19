// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { TrajectoryExportButton } from "@/app/observability/components/TrajectoryExportButton";
import { trajectoryService } from "@/services/trajectoryService";
import { record } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: { exportArchive: vi.fn() },
}));
const api = vi.mocked(trajectoryService);
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("downloads the ZIP and revokes its URL when the viewer closes", async () => {
  api.exportArchive.mockResolvedValue(new Blob(["zip"]));
  const create = vi.fn(() => "blob:archive");
  const revoke = vi.fn();
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    }
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const view = render(
    <App>
      <TrajectoryExportButton row={record} />
    </App>
  );
  await userEvent.click(
    screen.getByRole("button", { name: "trajectory.export" })
  );
  await waitFor(() => expect(click).toHaveBeenCalledOnce());
  expect(create).toHaveBeenCalledOnce();
  expect(api.exportArchive.mock.calls.at(-1)![0]).toBe(record);
  view.unmount();
  expect(revoke).toHaveBeenCalledWith("blob:archive");
});

it("cancels outstanding export when pagehide occurs and permits retry", async () => {
  let complete!: (blob: Blob) => void;
  api.exportArchive.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      })
  );
  const create = vi.fn();
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = create;
    }
  );
  const view = render(
    <App>
      <TrajectoryExportButton row={record} />
    </App>
  );
  await userEvent.click(
    screen.getByRole("button", { name: "trajectory.export" })
  );
  const signal = api.exportArchive.mock.calls.at(-1)![1]!;
  act(() => window.dispatchEvent(new Event("pagehide")));
  expect(signal.aborted).toBe(true);
  await act(async () => complete(new Blob(["late"])));
  expect(create).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "trajectory.export" })
  ).not.toHaveClass("ant-btn-loading");
  view.unmount();
});
