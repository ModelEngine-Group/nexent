import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { handleSessionExpired } from "@/lib/session";

vi.mock("@/services/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/api")>()),
  API_ENDPOINTS: {
    aidpMgmt: {
      kbDocuments: (id: string) =>
        `/api/aidp-mgmt/knowledge-bases/${id}/documents`,
    },
  },
  fetchWithErrorHandling: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ getAuthHeaders: vi.fn() }));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("@/lib/session", () => ({ handleSessionExpired: vi.fn() }));

class XhrMock {
  static last: XhrMock;
  constructor() {
    XhrMock.last = this;
  }
  upload = {
    onprogress: null as
      | ((event: {
          lengthComputable: boolean;
          loaded: number;
          total: number;
        }) => void)
      | null,
    onload: null as (() => void) | null,
  };
  open = vi.fn();
  send = vi.fn();
  setRequestHeader = vi.fn();
  abort = vi.fn(() => this.onabort?.());
  withCredentials = false;
  status = 200;
  statusText = "";
  responseText = "";
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
}

describe("AKPR-D1-015 AIDP multipart progress transport", () => {
  beforeEach(() => {
    vi.stubGlobal("XMLHttpRequest", XhrMock);
    vi.mocked(handleSessionExpired).mockClear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });
  it("sends repeated files in one authenticated multipart request and waits for the response", async () => {
    const files = [new File(["one"], "one.txt"), new File(["two"], "two.txt")];
    const progress = vi.fn();
    const controller = new AbortController();
    const abortListener = vi.spyOn(controller.signal, "removeEventListener");
    const promise = aidpKnowledgeService.uploadDocsWithProgress(
      "kb-1",
      files,
      progress,
      controller.signal,
    );
    const xhr = XhrMock.last;
    expect(xhr.open).toHaveBeenCalledWith(
      "POST",
      expect.stringContaining("/knowledge-bases/kb-1/documents"),
    );
    expect(xhr.send).toHaveBeenCalledOnce();
    expect((xhr.send.mock.calls[0][0] as FormData).getAll("files")).toEqual(
      files,
    );
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.setRequestHeader).not.toHaveBeenCalledWith(
      "Content-Type",
      expect.anything(),
    );
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
    expect(progress).toHaveBeenLastCalledWith(50, 100);
    xhr.upload.onload?.();
    expect(progress).toHaveBeenLastCalledWith(1, 1);
    let resolved = false;
    void promise.then(() => {
      resolved = true;
    });
    await Promise.resolve();
    expect(resolved).toBe(false);
    xhr.responseText = JSON.stringify({
      summary: { total: 2, success: 0, failed: 2 },
      success_list: [],
      failed_list: [
        { file_name: "one.txt", reason_zh: "Rejected" },
        { file_name: "two.txt", reason_zh: "Rejected" },
      ],
    });
    xhr.onload?.();
    expect((await promise).failed_list).toHaveLength(2);
    expect(abortListener).toHaveBeenCalledWith("abort", expect.any(Function));
  });
  it("preserves upstream rejection reasons", async () => {
    const promise = aidpKnowledgeService.uploadDocsWithProgress(
      "kb",
      [new File(["x"], "x.txt")],
      vi.fn(),
      new AbortController().signal,
    );
    const rejected = expect(promise).rejects.toThrow("AIDP rejected request");
    XhrMock.last.status = 502;
    XhrMock.last.responseText = JSON.stringify({
      details: { upstream_reason: "AIDP rejected request" },
    });
    XhrMock.last.onload?.();
    await rejected;
  });
  it("triggers existing session handling on an unauthorized response", async () => {
    const promise = aidpKnowledgeService.uploadDocsWithProgress(
      "kb",
      [],
      vi.fn(),
      new AbortController().signal,
    );
    const rejected = expect(promise).rejects.toThrow("HTTP 401");
    XhrMock.last.status = 401;
    XhrMock.last.onload?.();
    await rejected;
    expect(handleSessionExpired).toHaveBeenCalledOnce();
  });
  it("aborts on cancellation without pretending the request succeeded", async () => {
    const controller = new AbortController();
    const promise = aidpKnowledgeService.uploadDocsWithProgress(
      "kb",
      [],
      vi.fn(),
      controller.signal,
    );
    const rejected = expect(promise).rejects.toMatchObject({
      name: "AbortError",
    });
    controller.abort();
    await rejected;
    expect(XhrMock.last.abort).toHaveBeenCalledOnce();
  });
});
