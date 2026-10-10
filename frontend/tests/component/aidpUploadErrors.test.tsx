import { afterEach, describe, expect, it, vi } from "vitest";
import { createInstance } from "i18next";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";

import { ApiError } from "@/services/api";
import { ErrorCode } from "@/const/errorCode";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import {
  getAidpUploadErrorMessage,
  parseAidpUploadError,
} from "@/ext_components/aidp/services/aidpUploadUtils";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
import AidpImportDrawer from "@/ext_components/aidp/components/AidpImportDrawer";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";

vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({}),
  fetchWithAuth: vi.fn(),
}));
vi.mock("@/lib/session", () => ({ handleSessionExpired: vi.fn() }));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      zh[key as keyof typeof zh] || options?.defaultValue || key,
    i18n: { language: "zh" },
  }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AIDP upload failure information", () => {
  it.each([
    { code: "000403", message: "File size exceeds limit" },
    { detail: { code: "000403", message: "File size exceeds limit" } },
    { message: { code: "000403", message: "File size exceeds limit" } },
  ])("preserves the business code in supported error envelopes: %j", (body) => {
    const error = parseAidpUploadError(
      413,
      "Payload Too Large",
      JSON.stringify(body)
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("000403");
    expect(error.message).toBe("File size exceeds limit");
  });

  it.each([
    [{ message: "解析服务不可用" }, "解析服务不可用"],
    [{ detail: "知识库不存在" }, "知识库不存在"],
    [{ details: { upstream_reason: "unsupported file" } }, "unsupported file"],
  ])(
    "retains interface text when no business code is returned: %j",
    (body, message) => {
      const error = parseAidpUploadError(
        502,
        "Bad Gateway",
        JSON.stringify(body)
      );
      expect(error.code).toBe(502);
      expect(error.message).toBe(message);
      const translate = vi.fn((_key, options) => options.defaultValue);
      expect(getAidpUploadErrorMessage(error, translate, "Upload failed")).toBe(
        message
      );
    }
  );

  it("keeps plain response text and structured upstream details", () => {
    expect(
      parseAidpUploadError(502, "Bad Gateway", "服务正在维护").message
    ).toBe("服务正在维护");
    const error = parseAidpUploadError(
      502,
      "Bad Gateway",
      JSON.stringify({
        code: ErrorCode.AIDP_SERVICE_ERROR,
        message: "Service error",
        details: { upstream_reason: "模型不可用", upstream_status_code: 400 },
      })
    );
    expect(error.code).toBe(ErrorCode.AIDP_SERVICE_ERROR);
    expect(error.details?.upstream_status_code).toBe(400);
    expect(error.message).toBe("模型不可用");
  });

  it.each(["zh", "en"])(
    "displays code translations in %s instead of raw response messages",
    async (language) => {
      const i18n = createInstance();
      await i18n.init({
        lng: language,
        keySeparator: false,
        resources: { zh: { translation: zh }, en: { translation: en } },
      });
      const translate = (key: string, options: { defaultValue: string }) =>
        i18n.t(key, options);
      for (const code of [
        ErrorCode.AIDP_SERVICE_ERROR,
        ErrorCode.AIDP_CONFIG_INVALID,
        ErrorCode.AIDP_CONNECTION_ERROR,
        ErrorCode.AIDP_AUTH_ERROR,
        ErrorCode.AIDP_RATE_LIMIT,
        ErrorCode.AIDP_RESPONSE_ERROR,
        ErrorCode.FILE_TOO_LARGE,
      ]) {
        const key = `errorCode.${code}`;
        expect(i18n.exists(key)).toBe(true);
        expect(
          getAidpUploadErrorMessage(
            new ApiError(code, "Raw server text"),
            translate,
            "Upload failed"
          )
        ).toBe(i18n.t(key));
      }
      expect(
        getAidpUploadErrorMessage(
          new Error("Connection reset"),
          translate,
          "Upload failed"
        )
      ).toBe("Connection reset");
    }
  );

  it("preserves the code through the multipart fetch upload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: ErrorCode.AIDP_AUTH_ERROR,
            message: "Upstream denied access",
          }),
          { status: 502 }
        )
      )
    );
    await expect(
      aidpKnowledgeService.uploadDocs("1", [new File(["test"], "test.txt")])
    ).rejects.toMatchObject({
      name: "ApiError",
      code: ErrorCode.AIDP_AUTH_ERROR,
      message: "Upstream denied access",
    });
  });

  it("preserves the code through the XHR upload used by the drawer", async () => {
    class UploadXhrMock {
      status = 413;
      statusText = "Payload Too Large";
      responseText = JSON.stringify({
        detail: { code: "000403", message: "File too large" },
      });
      upload = {};
      onload: (() => void) | null = null;
      open = vi.fn();
      setRequestHeader = vi.fn();
      abort = vi.fn();
      send = vi.fn(() => this.onload?.());
    }
    vi.stubGlobal("XMLHttpRequest", UploadXhrMock);
    await expect(
      aidpKnowledgeService.uploadDocsWithProgress(
        "1",
        [new File(["test"], "test.txt")],
        vi.fn(),
        new AbortController().signal
      )
    ).rejects.toMatchObject({
      name: "ApiError",
      code: "000403",
      message: "File too large",
    });
  });
});

describe("upload failures remain inside file rows", () => {
  const knowledgeBase = {
    kds_id: "1",
    kds_name: "测试知识库",
  } as AidpKnowledgeBaseItem;

  const selectFile = async () => {
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
      window.setTimeout(() => callback(0), 0)
    );
    render(
      <App>
        <AidpImportDrawer
          open
          title="导入文件"
          knowledgeBase={knowledgeBase}
          onClose={vi.fn()}
          onDocsUploaded={vi.fn()}
          onRefresh={vi.fn()}
        />
      </App>
    );
    const input = document.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, {
      target: {
        files: [new File(["test"], "测试.txt", { type: "text/plain" })],
      },
    });
    await waitFor(() =>
      expect(screen.getByText("测试.txt")).toBeInTheDocument()
    );
  };

  it.each([
    [new ApiError("000403", "Raw size error"), "文件大小超出限制"],
    [new Error("接口返回的具体失败原因"), "接口返回的具体失败原因"],
  ])(
    "renders a request failure on the file without an error toast: %s",
    async (error, expected) => {
      vi.spyOn(
        aidpKnowledgeService,
        "uploadDocsWithProgress"
      ).mockRejectedValue(error);
      await selectFile();
      await waitFor(() =>
        expect(screen.getByText(expected)).toBeInTheDocument()
      );
      expect(document.querySelector(".ant-message-error")).toBeNull();
      expect(
        screen.getByRole("button", { name: "删除 测试.txt" })
      ).toBeInTheDocument();
    }
  );

  it("uses a per-file business code returned in a successful batch response", async () => {
    vi.spyOn(aidpKnowledgeService, "uploadDocsWithProgress").mockResolvedValue({
      summary: { total: 1, success: 0, failed: 1 },
      success_list: [],
      failed_list: [
        {
          file_name: "测试.txt",
          code: "000403",
          reason_zh: "原始原因",
          reason_en: "Raw reason",
        },
      ],
    });
    await selectFile();
    await waitFor(() =>
      expect(screen.getByText("文件大小超出限制")).toBeInTheDocument()
    );
    expect(screen.queryByText("原始原因")).not.toBeInTheDocument();
    expect(document.querySelector(".ant-message-error")).toBeNull();
  });
});
