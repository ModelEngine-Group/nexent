// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "../../components/ui/dialog";
import { ModelCheckSummary } from "../../components/model/ModelCheckSummary";

const locale = vi.hoisted(() => ({ language: "en" }));
beforeEach(() => {
  locale.language = "en";
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: locale,
    t: (key: string, values?: { count?: number }) =>
      values?.count === undefined ? key : `${key}:${values.count}`,
  }),
}));

it("AC-FIX-10 portals shared diagnostics outside the clipping dialog and keeps it open after dismissal", async () => {
  const retry = vi.fn();
  const issue = {
    category: "MODEL_NOT_FOUND",
    scope: "connection" as const,
    http_status: 404,
  };
  render(
    <Dialog open>
      <DialogContent className="overflow-hidden">
        <DialogTitle>Onboarding</DialogTitle>
        <ModelCheckSummary
          issues={{ one: issue, two: issue }}
          onRetryShared={retry}
        />
      </DialogContent>
    </Dialog>
  );
  await userEvent.click(
    screen.getByRole("button", { name: "modelProfile.checkIssues:1" })
  );
  const region = await screen.findByRole("region", {
    name: "modelProfile.checkIssueDetails",
  });
  expect(region.closest('[data-slot="dialog-content"]')).toBeNull();
  expect(within(region).getAllByText(/HTTP 404/)).toHaveLength(1);
  await userEvent.click(
    within(region).getByRole("button", { name: "modelProfile.retryCheck" })
  );
  expect(retry).toHaveBeenCalledOnce();
  fireEvent.keyDown(region, { key: "Escape" });
  expect(screen.getByRole("dialog", { name: "Onboarding" })).toBeVisible();
});

it("AC-FIX-10 retains model ownership and routes configure and retry actions", async () => {
  const configure = vi.fn();
  const retry = vi.fn();
  const issue = {
    category: "MODEL_REQUEST_INVALID",
    scope: "model" as const,
    http_status: 422,
    parameter: "temperature",
  };
  render(
    <ModelCheckSummary
      issues={{ one: issue, two: issue }}
      modelNames={{ one: "Model One", two: "Model Two" }}
      onConfigure={configure}
      onRetry={retry}
    />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "modelProfile.checkIssues:2" })
  );
  const region = await screen.findByRole("region", {
    name: "modelProfile.checkIssueDetails",
  });
  expect(within(region).getByText("Model One")).toBeVisible();
  expect(within(region).getByText("Model Two")).toBeVisible();
  expect(within(region).getAllByText(/HTTP 422/)).toHaveLength(2);
  await userEvent.click(
    within(region).getAllByRole("button", {
      name: "modelProfile.configureModel",
    })[1]
  );
  await userEvent.click(
    within(region).getAllByRole("button", {
      name: "modelProfile.retryCheck",
    })[0]
  );
  expect(configure).toHaveBeenCalledWith("two");
  expect(retry).toHaveBeenCalledWith("one");
});

it("shows the HTTP layer detail as text instead of discarding it", async () => {
  render(
    <ModelCheckSummary
      issues={{
        kimi: {
          category: "MODEL_REQUEST_INVALID",
          scope: "model",
          http_status: 400,
          message_source: "provider",
          message:
            "(400) invalid top_p: only 0.95 is allowed <script>text</script>",
        },
      }}
    />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "modelProfile.checkIssues:1" })
  );
  const region = await screen.findByRole("region", {
    name: "modelProfile.checkIssueDetails",
  });
  expect(region).toHaveTextContent(
    "(400) invalid top_p: only 0.95 is allowed <script>text</script>"
  );
  expect(region.querySelector("script")).toBeNull();
});

it("VT-03 selects the shared Chinese diagnostic instead of the English message", async () => {
  locale.language = "zh-CN";
  render(
    <ModelCheckSummary
      issues={{
        glm: {
          category: "MODEL_PROTOCOL_ERROR",
          diagnostic_code: "MODEL_STREAM_AFTER_FINISH",
          message_source: "system",
          message: "English internal fallback",
          messages: {
            en: "Received additional content after completion.",
            zh: "收到生成结束标记后，又收到新增内容。",
          },
        },
      }}
    />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "modelProfile.checkIssues:1" })
  );
  const region = await screen.findByRole("region", {
    name: "modelProfile.checkIssueDetails",
  });
  expect(region).toHaveTextContent("收到生成结束标记后，又收到新增内容。");
  expect(region).not.toHaveTextContent("English internal fallback");
});

it("VT-03 selects English and labels unknown upstream messages", async () => {
  render(
    <ModelCheckSummary
      issues={{
        known: {
          category: "MODEL_PROTOCOL_ERROR",
          message: "unused",
          messages: {
            en: "Conflicting completion reasons.",
            zh: "结束原因冲突。",
          },
        },
        vendor: {
          category: "MODEL_HTTP_ERROR",
          message_source: "provider",
          message: "(500) custom upstream failure",
        },
      }}
    />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "modelProfile.checkIssues:2" })
  );
  const region = await screen.findByRole("region", {
    name: "modelProfile.checkIssueDetails",
  });
  expect(region).toHaveTextContent("Conflicting completion reasons.");
  expect(region).toHaveTextContent(
    "modelProfile.originalServiceError (500) custom upstream failure"
  );
});

it("VT-03 old known responses use translations instead of raw English", async () => {
  render(
    <ModelCheckSummary
      issues={{
        old: { category: "MODEL_TIMEOUT", message: "Internal English timeout" },
      }}
    />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "modelProfile.checkIssues:1" })
  );
  const region = await screen.findByRole("region", {
    name: "modelProfile.checkIssueDetails",
  });
  expect(region).toHaveTextContent("modelProfile.checkErrors.MODEL_TIMEOUT");
  expect(region).not.toHaveTextContent("Internal English timeout");
});
