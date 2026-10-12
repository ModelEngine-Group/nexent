import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProviderTestPanel } from "@/app/[locale]/memory/ProviderTestPanel";
import {
  testIngest,
  testSearch,
  type ProviderConfig,
} from "@/services/providerService";

const en: Record<string, string> = {
  "memory.external.test.title": "Test {{name}}",
  "memory.external.test.ingestConfirmTitle": "Write test memory?",
  "memory.external.test.sequenceConfirmDescription":
    "This writes a test memory before searching.",
  "memory.external.test.writeAndSearch": "Write and search",
  "memory.external.actions.cancel": "Cancel",
  "memory.external.actions.close": "Close",
  "memory.external.test.sequenceWarning":
    "A test write is performed before the search.",
  "memory.external.test.sampleContent": "Sample content",
  "memory.external.test.sampleQuery": "Sample query",
  "memory.external.test.content": "Content",
  "memory.external.test.contentHint": "Content hint",
  "memory.external.test.contentRequired": "Content is required",
  "memory.external.test.query": "Query",
  "memory.external.test.queryHint": "Query hint",
  "memory.external.test.queryRequired": "Query is required",
  "memory.external.test.succeeded": "Test completed successfully",
  "memory.external.test.failed": "The provider request failed.",
  "memory.external.test.duration": "Duration",
  "memory.external.test.accepted": "Accepted",
  "memory.external.test.rejected": "Rejected",
  "memory.external.test.hits": "Hits",
  "memory.external.test.error": "Error",
  "memory.external.test.unknownError": "Unknown error",
};

function translate(key: string, options?: Record<string, unknown>): string {
  let value = en[key] ?? key;
  if (options) {
    for (const [name, replacement] of Object.entries(options)) {
      value = value.replaceAll(`{{${name}}}`, String(replacement));
    }
  }
  return value;
}

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate, i18n: {} }),
}));

vi.mock("antd", async (importOriginal) => {
  const actual = await importOriginal<typeof import("antd")>();
  return {
    ...actual,
    App: Object.assign(actual.App, {
      useApp: () => ({
        modal: {
          confirm: (config: { onOk?: () => void }) => {
            config.onOk?.();
          },
        },
        message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
        notification: {},
      }),
    }),
  };
});

vi.mock("@/services/providerService", () => ({
  testIngest: vi.fn(),
  testSearch: vi.fn(),
}));

const testIngestMock = vi.mocked(testIngest);
const testSearchMock = vi.mocked(testSearch);

const provider: ProviderConfig = {
  provider_config_id: 1,
  tenant_id: "tenant-a",
  provider_name: "my provider",
  connection_type: "plugin",
  enabled: true,
  timeout_seconds: 30,
  last_error_code: null,
  params: { "plugin.name": "mem0" },
  create_time: "2026-01-01T00:00:00Z",
  update_time: "2026-01-01T00:00:00Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderPanel() {
  const onClose = vi.fn();
  const onTested = vi.fn();
  render(
    <ProviderTestPanel
      open
      provider={provider}
      onClose={onClose}
      onTested={onTested}
    />
  );
  return { onClose, onTested };
}

describe("ProviderTestPanel connectivity test", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    testIngestMock.mockResolvedValue({ accepted: 1, rejected: 0 });
    testSearchMock.mockResolvedValue({ count: 2 });
  });

  it("UT-FE-AUTO-528B1E179F939E0B renders drawer title, sequence warning and prefilled fields", async () => {
    renderPanel();

    expect(screen.getByText("Test my provider")).toBeTruthy();
    expect(
      screen.getByText("A test write is performed before the search.")
    ).toBeTruthy();

    const [contentField, queryField] = screen.getAllByRole("textbox");
    expect((contentField as HTMLTextAreaElement).value).toBe("Sample content");
    expect((queryField as HTMLTextAreaElement).value).toBe("Sample query");
  });

  it("runs ingest then search and shows success results", async () => {
    const user = userEvent.setup();
    const callOrder: string[] = [];
    testIngestMock.mockImplementation(async () => {
      callOrder.push("ingest");
      return { accepted: 1, rejected: 0 };
    });
    testSearchMock.mockImplementation(async () => {
      callOrder.push("search");
      return { count: 2 };
    });

    const { onTested } = renderPanel();
    const [contentField, queryField] = screen.getAllByRole("textbox");
    await user.clear(contentField);
    await user.type(contentField, "hello memory");
    await user.clear(queryField);
    await user.type(queryField, "what did I write?");

    await user.click(screen.getByRole("button", { name: "Write and search" }));

    await waitFor(() =>
      expect(screen.getByText("Test completed successfully")).toBeTruthy()
    );
    expect(callOrder).toEqual(["ingest", "search"]);
    expect(testIngestMock).toHaveBeenCalledWith(
      1,
      expect.arrayContaining([
        expect.objectContaining({
          unit_type: "user_message",
          unit_content: "hello memory",
        }),
      ])
    );
    expect(testSearchMock).toHaveBeenCalledWith(1, "what did I write?", 3);
    expect(screen.getByText("Duration")).toBeTruthy();
    expect(screen.getByText("Accepted")).toBeTruthy();
    expect(screen.getByText("Rejected")).toBeTruthy();
    expect(screen.getByText("Hits")).toBeTruthy();
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByText("0")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    expect(onTested).toHaveBeenCalledTimes(1);
  });

  it("does not run search when ingest fails", async () => {
    const user = userEvent.setup();
    testIngestMock.mockRejectedValue(new Error("ingest failed"));

    renderPanel();
    await user.click(screen.getByRole("button", { name: "Write and search" }));

    await waitFor(() =>
      expect(screen.getByText("The provider request failed.")).toBeTruthy()
    );
    expect(testIngestMock).toHaveBeenCalledTimes(1);
    expect(testSearchMock).not.toHaveBeenCalled();
  });

  it("shows generic error and never leaks upstream body when search fails", async () => {
    const user = userEvent.setup();
    testIngestMock.mockResolvedValue({ accepted: 1, rejected: 0 });
    testSearchMock.mockRejectedValue(new Error("secret upstream body"));

    renderPanel();
    await user.click(screen.getByRole("button", { name: "Write and search" }));

    await waitFor(() =>
      expect(screen.getByText("The provider request failed.")).toBeTruthy()
    );
    expect(screen.queryByText("secret upstream body")).toBeNull();
  });

  it("toggles loading state and refreshes via onTested", async () => {
    const user = userEvent.setup();
    const ingestGate = deferred<{ accepted: number; rejected: number }>();
    testIngestMock.mockReturnValueOnce(ingestGate.promise);
    testSearchMock.mockResolvedValue({ count: 2 });

    const { onTested } = renderPanel();
    const button = screen.getByRole("button", { name: "Write and search" });
    await user.click(button);

    await waitFor(() => expect(testIngestMock).toHaveBeenCalledTimes(1));
    expect(button.className).toContain("ant-btn-loading");

    ingestGate.resolve({ accepted: 1, rejected: 0 });

    await waitFor(() =>
      expect(screen.getByText("Test completed successfully")).toBeTruthy()
    );
    expect(button.className).not.toContain("ant-btn-loading");
    expect(onTested).toHaveBeenCalledTimes(1);
  });
});
