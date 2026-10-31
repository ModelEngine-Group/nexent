// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  collectConversationArtifacts,
  type ArtifactMessageLike,
} from "@/app/newchat/utils/conversation-artifacts";
import {
  ConversationArtifactsButton,
  ConversationArtifactsPanel,
} from "@/app/newchat/ui/artifacts-panel";
import { skillFileUploadsRegistry } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { CompleteAttachment } from "@assistant-ui/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (params && "count" in params) return `${key}:${params.count}`;
      if (params && "time" in params) return `${key}:${params.time}`;
      return key;
    },
  }),
}));

// The aggregation util imports the artifact registry from the streaming
// adapter; mocking the module keeps the heavyweight adapter out of the test.
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  searchSourcesRegistry: new Map(),
  searchImagesRegistry: new Map(),
  conversationSourcesRegistry: new Map(),
  skillFileUploadsRegistry: new Map(),
  stepTokenCounts: [],
}));

const previewDrawerMock = vi.hoisted(() => ({
  open: vi.fn(),
}));
vi.mock("@/components/common/filePreviewDrawer", () => ({
  FilePreviewDrawer: (props: {
    open: boolean;
    fileName: string;
    objectName: string;
    onClose: () => void;
  }) => {
    previewDrawerMock.open(props);
    return props.open ? (
      <div data-testid="file-preview-drawer">{props.fileName}</div>
    ) : null;
  },
}));

const storageServiceMock = vi.hoisted(() => ({
  downloadFile: vi.fn(),
  getPreviewUrl: vi.fn(() => "blob:preview"),
}));
vi.mock("@/services/storageService", () => ({
  storageService: storageServiceMock,
  getLocalFilePreviewUrl: vi.fn(),
  extractObjectNameFromUrl: vi.fn(),
  fetchImageBlob: vi.fn(),
  isLocalStorageObjectUrl: vi.fn(() => false),
}));

vi.mock("@/lib/logger", () => ({
  default: { error: vi.fn(), warn: vi.fn(), log: vi.fn() },
}));

const makeAttachment = (
  id: string,
  name: string,
  overrides: Record<string, unknown> = {}
): CompleteAttachment =>
  ({
    id,
    status: { type: "complete" },
    type: "file",
    name,
    contentType:
      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    object_name: `runs/${id}/${name}`,
    preview_url: `blob:preview-${id}`,
    download_url: `/api/storage/download/${id}`,
    size: 2048,
    ...overrides,
  }) as unknown as CompleteAttachment;

beforeEach(() => {
  skillFileUploadsRegistry.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("collectConversationArtifacts reads streamed part payloads", () => {
  const messages: ArtifactMessageLike[] = [
    {
      id: "m1",
      role: "user",
      content: [{ type: "text" }],
    },
    {
      id: "m2",
      role: "assistant",
      createdAt: new Date("2026-10-31T08:10:00Z"),
      content: [
        { type: "text" },
        {
          type: "text",
          skillFileAttachments: [
            makeAttachment("a1", "report.pptx"),
            makeAttachment("a2", "data.csv"),
          ],
        },
      ],
    },
  ];

  const artifacts = collectConversationArtifacts(messages);

  expect(artifacts).toHaveLength(2);
  expect(artifacts[0]?.attachment.name).toBe("report.pptx");
  expect(artifacts[1]?.attachment.name).toBe("data.csv");
  expect(artifacts[0]?.messageId).toBe("m2");
  expect(artifacts[0]?.key).toBe("m2:a1:0");
  expect(artifacts[0]?.createdAt).toEqual(new Date("2026-10-31T08:10:00Z"));
});

test("collectConversationArtifacts falls back to the history registry", () => {
  skillFileUploadsRegistry.set("m-restored", [
    makeAttachment("r1", "restored.md"),
  ]);
  const messages: ArtifactMessageLike[] = [
    {
      id: "m-restored",
      role: "assistant",
      content: [{ type: "text", isSkillFiles: true }],
    },
  ];

  const artifacts = collectConversationArtifacts(messages);

  expect(artifacts).toHaveLength(1);
  expect(artifacts[0]?.attachment.name).toBe("restored.md");
});

test("collectConversationArtifacts prefers the latest cumulative part", () => {
  const messages: ArtifactMessageLike[] = [
    {
      id: "m3",
      role: "assistant",
      content: [
        {
          type: "text",
          skillFileAttachments: [makeAttachment("old", "old.txt")],
        },
        {
          type: "text",
          skillFileAttachments: [
            makeAttachment("old", "old.txt"),
            makeAttachment("new", "new.txt"),
          ],
        },
      ],
    },
  ];

  const artifacts = collectConversationArtifacts(messages);

  expect(artifacts).toHaveLength(2);
  expect(artifacts.map((a) => a.attachment.name)).toEqual([
    "old.txt",
    "new.txt",
  ]);
});

test("collectConversationArtifacts ignores invalid createdAt values", () => {
  const messages: ArtifactMessageLike[] = [
    {
      id: "m4",
      role: "assistant",
      createdAt: new Date("not-a-date"),
      content: [
        {
          type: "text",
          skillFileAttachments: [makeAttachment("a", "a.txt")],
        },
      ],
    },
  ];

  const artifacts = collectConversationArtifacts(messages);

  expect(artifacts).toHaveLength(1);
  expect(artifacts[0]?.createdAt).toBeUndefined();
});

test("collectConversationArtifacts keeps keys unique across chunks", () => {
  // Two streaming chunks restart the attachment id counter, so both files
  // share the id "m9-skill-file-0" inside the cumulative part payload.
  const messages: ArtifactMessageLike[] = [
    {
      id: "m9",
      role: "assistant",
      content: [
        {
          type: "text",
          skillFileAttachments: [
            { ...makeAttachment("m9-skill-file-0", "first.txt") },
            { ...makeAttachment("m9-skill-file-0", "second.txt") },
          ],
        },
      ],
    },
  ];

  const artifacts = collectConversationArtifacts(messages);
  const keys = artifacts.map((artifact) => artifact.key);

  expect(artifacts).toHaveLength(2);
  expect(new Set(keys).size).toBe(2);
});

test("collectConversationArtifacts returns empty for empty input", () => {
  expect(collectConversationArtifacts([])).toEqual([]);
});

test("ConversationArtifactsPanel renders artifacts with actions", () => {
  const artifacts = collectConversationArtifacts([
    {
      id: "m5",
      role: "assistant",
      createdAt: new Date("2026-10-31T08:10:00Z"),
      content: [
        {
          type: "text",
          skillFileAttachments: [makeAttachment("a1", "summary.pptx")],
        },
      ],
    },
  ]);

  render(
    <TooltipProvider>
      <ConversationArtifactsPanel
        open
        artifacts={artifacts}
        onClose={() => {}}
      />
    </TooltipProvider>
  );

  expect(screen.getByText("summary.pptx")).toBeTruthy();
  expect(screen.getByText("chat.artifacts.total:1")).toBeTruthy();
  // Size (2.0 KB) and generated-at metadata render alongside the name.
  expect(screen.getByText(/2\.0 KB/)).toBeTruthy();
});

test("ConversationArtifactsPanel preview opens the shared drawer", () => {
  const artifacts = collectConversationArtifacts([
    {
      id: "m6",
      role: "assistant",
      content: [
        {
          type: "text",
          skillFileAttachments: [makeAttachment("a1", "summary.pptx")],
        },
      ],
    },
  ]);

  render(
    <TooltipProvider>
      <ConversationArtifactsPanel
        open
        artifacts={artifacts}
        onClose={() => {}}
      />
    </TooltipProvider>
  );

  fireEvent.click(
    screen.getByRole("button", { name: "chat.artifacts.preview" })
  );

  expect(previewDrawerMock.open).toHaveBeenCalledWith(
    expect.objectContaining({
      open: true,
      fileName: "summary.pptx",
      objectName: "runs/a1/summary.pptx",
      downloadUrl: "/api/storage/download/a1",
    })
  );
  expect(screen.getByTestId("file-preview-drawer")).toBeTruthy();
});

test("ConversationArtifactsPanel download uses the download url", () => {
  const artifacts = collectConversationArtifacts([
    {
      id: "m7",
      role: "assistant",
      content: [
        {
          type: "text",
          skillFileAttachments: [makeAttachment("a1", "summary.pptx")],
        },
      ],
    },
  ]);

  render(
    <TooltipProvider>
      <ConversationArtifactsPanel
        open
        artifacts={artifacts}
        onClose={() => {}}
      />
    </TooltipProvider>
  );

  fireEvent.click(
    screen.getByRole("button", { name: "chat.artifacts.download" })
  );

  // The anchor-based download path does not call the storage service.
  expect(storageServiceMock.downloadFile).not.toHaveBeenCalled();
});

test("ConversationArtifactsPanel download falls back to object storage", () => {
  const artifacts = collectConversationArtifacts([
    {
      id: "m8",
      role: "assistant",
      content: [
        {
          type: "text",
          skillFileAttachments: [
            makeAttachment("a1", "summary.pptx", { download_url: undefined }),
          ],
        },
      ],
    },
  ]);

  render(
    <TooltipProvider>
      <ConversationArtifactsPanel
        open
        artifacts={artifacts}
        onClose={() => {}}
      />
    </TooltipProvider>
  );

  fireEvent.click(
    screen.getByRole("button", { name: "chat.artifacts.download" })
  );

  expect(storageServiceMock.downloadFile).toHaveBeenCalledWith(
    "runs/a1/summary.pptx",
    "summary.pptx"
  );
});

test("ConversationArtifactsPanel hides when closed", () => {
  const { container } = render(
    <ConversationArtifactsPanel
      open={false}
      artifacts={[]}
      onClose={() => {}}
    />
  );

  expect(container.firstChild).toBeNull();
});

test("ConversationArtifactsPanel shows the empty state", () => {
  render(
    <TooltipProvider>
      <ConversationArtifactsPanel open artifacts={[]} onClose={() => {}} />
    </TooltipProvider>
  );

  expect(screen.getByText("chat.artifacts.empty")).toBeTruthy();
});

test("ConversationArtifactsButton hides without artifacts", () => {
  const { container } = render(
    <ConversationArtifactsButton count={0} onClick={() => {}} />
  );

  expect(container.firstChild).toBeNull();
});

test("ConversationArtifactsButton opens the panel on click", () => {
  const onClick = vi.fn();
  render(<ConversationArtifactsButton count={3} onClick={onClick} />);

  const button = screen.getByRole("button", {
    name: "chat.artifacts.viewAll:3",
  });
  fireEvent.click(button);

  expect(onClick).toHaveBeenCalledTimes(1);
});
