import React from "react";
import { App } from "antd";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AidpImportDrawer from "@/ext_components/aidp/components/AidpImportDrawer";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { validateAidpFiles } from "@/services/uploadService";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpUploadResponse } from "@/ext_components/aidp/services/aidpKnowledgeService";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string | number>) =>
      options ? `${key} ${Object.values(options).join(" ")}` : key,
    i18n: { language: "zh" },
  }),
}));
vi.mock("@/ext_components/aidp/services/aidpKnowledgeService", () => ({
  default: { uploadDocsWithProgress: vi.fn() },
}));
vi.mock("@/services/uploadService", () => ({ validateAidpFiles: vi.fn() }));
const upload = vi.mocked(aidpKnowledgeService.uploadDocsWithProgress);
const kb = { kds_id: "kb-1", kds_name: "Test KB" } as AidpKnowledgeBaseItem;
const file = (name: string, size = 4) => new File([new Uint8Array(size)], name);
const accepted = (files: File[]): AidpUploadResponse => ({
  summary: { total: files.length, success: files.length, failed: 0 },
  success_list: files.map((f) => ({
    file_uuid: `uuid-${f.name}`,
    file_ino_no: `ino-${f.name}`,
    file_name: f.name,
    file_type: "txt",
    file_size: f.size,
    first_upload_time: 1,
  })),
  failed_list: [],
});
function renderDrawer() {
  const onClose = vi.fn(),
    onDocsUploaded = vi.fn(),
    onRefresh = vi.fn();
  const view = render(
    <App>
      <AidpImportDrawer
        open
        title="导入文件"
        knowledgeBase={kb}
        onClose={onClose}
        onDocsUploaded={onDocsUploaded}
        onRefresh={onRefresh}
      />
    </App>,
  );
  return { ...view, onClose, onDocsUploaded, onRefresh };
}
const choose = (files: File[]) =>
  fireEvent.change(document.body.querySelector('input[type="file"]')!, {
    target: { files },
  });
const confirm = () => screen.getByRole("button", { name: "common.confirm" });
const rows = () => document.body.querySelectorAll('[class*="fileRow_"]');

describe("AKPR-D1-015 AIDP batch import drawer", () => {
  beforeEach(() => {
    upload.mockReset().mockImplementation(() => new Promise(() => {}));
    vi.mocked(validateAidpFiles).mockReset().mockReturnValue({
      valid: [],
      invalidType: [],
      oversized: [],
      exceededCount: [],
    });
  });
  it("uploads a selection together, shares progress and waits for acceptance before Confirm", async () => {
    let progress!: (loaded: number, total: number) => void;
    let resolve!: (result: AidpUploadResponse) => void;
    upload.mockImplementation((_id, _files, onProgress) => {
      progress = onProgress;
      return new Promise((done) => {
        resolve = done;
      });
    });
    const { onClose, onDocsUploaded, onRefresh } = renderDrawer();
    const files = [file("guide.txt", 2560), file("manual.txt", 5120)];
    choose(files);
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    expect(upload.mock.calls[0][1]).toEqual(files);
    expect(confirm()).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "common.cancel" }),
    ).toBeDisabled();
    act(() => progress(350, 1000));
    expect(
      document.body.querySelectorAll('svg[aria-label="35%"]'),
    ).toHaveLength(2);
    expect(screen.getByText("3K")).toBeTruthy();
    expect(screen.getByText("5K")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /aidpKnowledge.delete/ }),
    ).toBeNull();
    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    act(() => progress(1000, 1000));
    expect(
      document.body.querySelectorAll('[class*="waitingSpinner_"]'),
    ).toHaveLength(2);
    expect(
      document.body.querySelectorAll('[class*="dashedRow_"]'),
    ).toHaveLength(2);
    expect(confirm()).toBeDisabled();
    await act(async () => resolve(accepted([...files].reverse())));
    await waitFor(() => expect(confirm()).toBeEnabled());
    expect(
      document.body.querySelectorAll('[class*="successRow_"]'),
    ).toHaveLength(2);
    expect(onDocsUploaded).toHaveBeenCalledWith([
      "ino-guide.txt",
      "ino-manual.txt",
    ]);
    expect(onRefresh).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: /aidpKnowledge.delete/ }),
    ).toBeNull();
    await userEvent.setup().click(confirm());
    expect(onClose).toHaveBeenCalledOnce();
    expect(upload).toHaveBeenCalledOnce();
  });
  it("caps the list at 50 and sends all accepted files together", async () => {
    renderDrawer();
    choose(Array.from({ length: 51 }, (_, i) => file(`guide-${i}.txt`)));
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    expect(upload.mock.calls[0][1]).toHaveLength(50);
    expect(rows()).toHaveLength(50);
    expect(
      screen.getByText("aidpKnowledge.importFileCount 50 50"),
    ).toBeTruthy();
    expect(confirm()).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /aidpKnowledge.delete/ }),
    ).toBeNull();
  });
  it("retains mixed results, deletes failures locally and sends only the next selection", async () => {
    upload.mockImplementation(async (_id, files) => {
      const good = files.filter((f) => f.name !== "bad.txt");
      return {
        ...accepted(good),
        summary: {
          total: files.length,
          success: good.length,
          failed: files.length - good.length,
        },
        failed_list: files
          .filter((f) => f.name === "bad.txt")
          .map((f) => ({
            file_name: f.name,
            reason_zh: "AIDP 拒绝上传",
            reason_en: "Rejected",
          })),
      };
    });
    const { onClose } = renderDrawer();
    fireEvent.drop(
      document.body.querySelector('input[type="file"]')!.parentElement!,
      {
        dataTransfer: {
          files: [file("bad.txt"), file("good.txt")],
          types: ["Files"],
        },
      },
    );
    expect(await screen.findByText("AIDP 拒绝上传")).toBeTruthy();
    await waitFor(() => expect(confirm()).toBeEnabled());
    expect(rows()).toHaveLength(2);
    expect(
      document.body.querySelectorAll('[class*="successRow_"]'),
    ).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: "aidpKnowledge.delete good.txt" }),
    ).toBeNull();
    await userEvent
      .setup()
      .click(
        screen.getByRole("button", { name: "aidpKnowledge.delete bad.txt" }),
      );
    expect(rows()).toHaveLength(1);
    expect(upload).toHaveBeenCalledOnce();
    choose([file("second.txt")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(upload.mock.calls[1][1].map((f) => f.name)).toEqual(["second.txt"]);
    expect(rows()).toHaveLength(2);
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });
  it("marks a network error against every file and enables Confirm", async () => {
    upload.mockRejectedValue(new Error("Network interrupted"));
    const { onClose, onDocsUploaded } = renderDrawer();
    choose([file("one.txt"), file("two.txt")]);
    expect(await screen.findAllByText("Network interrupted")).toHaveLength(2);
    await waitFor(() => expect(confirm()).toBeEnabled());
    expect(
      screen.getAllByRole("button", { name: /aidpKnowledge.delete/ }),
    ).toHaveLength(2);
    expect(onDocsUploaded).not.toHaveBeenCalled();
    await userEvent.setup().click(confirm());
    expect(onClose).toHaveBeenCalledOnce();
    expect(upload).toHaveBeenCalledOnce();
  });
  it("fails missing response entries instead of claiming success", async () => {
    upload.mockImplementation(async (_id, files) => accepted(files.slice(1)));
    renderDrawer();
    choose([file("missing.txt"), file("accepted.txt")]);
    expect(await screen.findByText("aidpKnowledge.uploadFailed")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "aidpKnowledge.delete missing.txt" }),
    ).toBeTruthy();
    expect(
      document.body.querySelectorAll('[class*="successRow_"]'),
    ).toHaveLength(1);
  });
  it("shows local validation failures without uploading", async () => {
    vi.mocked(validateAidpFiles).mockImplementation((files) => ({
      valid: [],
      invalidType: files,
      oversized: [],
      exceededCount: [],
    }));
    renderDrawer();
    choose([file("invalid.txt")]);
    expect(
      await screen.findByText("aidpKnowledge.invalidFileType 1"),
    ).toBeTruthy();
    expect(upload).not.toHaveBeenCalled();
    expect(confirm()).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "aidpKnowledge.delete invalid.txt" }),
    ).toBeTruthy();
  });
  it("aborts the browser request on unmount", async () => {
    const { unmount } = renderDrawer();
    choose([file("guide.txt")]);
    await waitFor(() => expect(upload).toHaveBeenCalledOnce());
    const signal = upload.mock.calls[0][3];
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
