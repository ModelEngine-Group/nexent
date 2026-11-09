// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  collectConversationArtifacts,
  fetchArtifactFile,
  type ArtifactMessageLike,
} from "@/app/newchat/utils/conversation-artifacts";
import {
  ConversationArtifactsButton,
  ConversationArtifactsToolbarEntry,
  ConversationArtifactsPanel,
} from "@/app/newchat/ui/artifacts-panel";
import { ConversationArtifactsEntryProvider } from "@/app/newchat/ui/conversation-artifacts-context";
import {
  compositeAttachmentAdapter,
  markFileWithExistingUpload,
} from "@/app/newchat/adapter/attachment-adapter";
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
  uploadFiles: vi.fn(),
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

test("ConversationArtifactsToolbarEntry renders nothing without a provider", () => {
  const { container } = render(<ConversationArtifactsToolbarEntry />);

  expect(container.firstChild).toBeNull();
});

test("ConversationArtifactsToolbarEntry hides while the conversation has no artifacts", () => {
  const { container } = render(
    <ConversationArtifactsEntryProvider count={0} open={() => {}}>
      <ConversationArtifactsToolbarEntry />
    </ConversationArtifactsEntryProvider>
  );

  expect(container.firstChild).toBeNull();
});

test("ConversationArtifactsToolbarEntry shows the conversation total and opens the panel", () => {
  const open = vi.fn();
  render(
    <ConversationArtifactsEntryProvider count={2} open={open}>
      <ConversationArtifactsToolbarEntry />
    </ConversationArtifactsEntryProvider>
  );

  const button = screen.getByRole("button", {
    name: "chat.artifacts.viewAll:2",
  });
  fireEvent.click(button);

  expect(open).toHaveBeenCalledTimes(1);
});

test("ConversationArtifactsToolbarEntry persists after generation and resets for an empty conversation", () => {
  const open = vi.fn();
  const Toolbar = ({ messages }: { messages: ArtifactMessageLike[] }) => (
    <ConversationArtifactsEntryProvider
      count={collectConversationArtifacts(messages).length}
      open={open}
    >
      <ConversationArtifactsToolbarEntry />
    </ConversationArtifactsEntryProvider>
  );
  const generated: ArtifactMessageLike = {
    id: "generated-1",
    role: "assistant",
    content: [
      {
        type: "text",
        skillFileAttachments: [makeAttachment("file-1", "report.docx")],
      },
    ],
  };
  const laterTurns: ArtifactMessageLike[] = [
    generated,
    { id: "follow-up", role: "user", content: [{ type: "text" }] },
    { id: "text-answer", role: "assistant", content: [{ type: "text" }] },
  ];
  const { container, rerender } = render(<Toolbar messages={[]} />);
  expect(
    container.querySelector('[data-slot="conversation-artifacts-toolbar"]')
  ).toBeNull();
  rerender(<Toolbar messages={[generated]} />);
  expect(
    screen.getAllByRole("button", { name: "chat.artifacts.viewAll:1" })
  ).toHaveLength(1);
  expect(
    container.querySelector('[data-slot="conversation-artifacts-toolbar"]')
      ?.className
  ).toContain("justify-end");
  rerender(<Toolbar messages={laterTurns} />);
  fireEvent.click(
    screen.getByRole("button", { name: "chat.artifacts.viewAll:1" })
  );
  expect(open).toHaveBeenCalledTimes(1);
  rerender(
    <Toolbar
      messages={[
        ...laterTurns,
        {
          id: "generated-2",
          role: "assistant",
          content: [
            {
              type: "text",
              skillFileAttachments: [makeAttachment("file-2", "more.csv")],
            },
          ],
        },
      ]}
    />
  );
  expect(
    screen.getAllByRole("button", { name: "chat.artifacts.viewAll:2" })
  ).toHaveLength(1);
  rerender(<Toolbar messages={[]} />);
  expect(container.firstChild).toBeNull();
});

const renderArtifactsPanel = (
  panelProps: Partial<Parameters<typeof ConversationArtifactsPanel>[0]> = {}
) => {
  const artifacts = collectConversationArtifacts([
    {
      id: "m-add",
      role: "assistant",
      content: [
        {
          type: "text",
          skillFileAttachments: [makeAttachment("a1", "summary.pptx")],
        },
      ],
    },
  ]);
  return render(
    <TooltipProvider>
      <ConversationArtifactsPanel
        open
        artifacts={artifacts}
        onClose={() => {}}
        {...panelProps}
      />
    </TooltipProvider>
  );
};

test("ConversationArtifactsPanel offers add-to-chat when a handler is provided", async () => {
  const onAddToComposer = vi.fn();
  renderArtifactsPanel({ onAddToComposer });

  const addButton = screen.getByRole("button", {
    name: "chat.artifacts.addToChat",
  });
  fireEvent.click(addButton);

  expect(onAddToComposer).toHaveBeenCalledTimes(1);
  expect(onAddToComposer).toHaveBeenCalledWith(
    expect.objectContaining({ name: "summary.pptx" })
  );
  // The in-flight guard releases once the handler settles.
  await waitFor(() => expect(addButton).not.toBeDisabled());
});

test("ConversationArtifactsPanel hides add-to-chat without a handler", () => {
  renderArtifactsPanel();

  expect(
    screen.queryByRole("button", { name: "chat.artifacts.addToChat" })
  ).toBeNull();
});

test("ConversationArtifactsPanel serializes rapid additions across different files", async () => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const onAddToComposer = vi
    .fn()
    .mockReturnValueOnce(pending)
    .mockResolvedValue(undefined);
  const artifacts = collectConversationArtifacts([
    {
      id: "multi",
      role: "assistant",
      content: [
        {
          type: "text",
          skillFileAttachments: [
            makeAttachment("a", "one.docx"),
            makeAttachment("b", "two.docx"),
          ],
        },
      ],
    },
  ]);
  renderArtifactsPanel({ artifacts, onAddToComposer });
  const buttons = screen.getAllByRole("button", {
    name: "chat.artifacts.addToChat",
  });
  act(() => {
    fireEvent.click(buttons[0]);
    fireEvent.click(buttons[1]);
    fireEvent.click(buttons[0]);
  });
  expect(onAddToComposer).toHaveBeenCalledTimes(1);
  expect(
    buttons.every((button) => (button as HTMLButtonElement).disabled)
  ).toBe(true);
  await act(async () => {
    finish();
    await pending;
  });
  await waitFor(() =>
    expect(
      buttons.every((button) => !(button as HTMLButtonElement).disabled)
    ).toBe(true)
  );
  fireEvent.click(buttons[1]);
  await waitFor(() => expect(onAddToComposer).toHaveBeenCalledTimes(2));
  expect(onAddToComposer).toHaveBeenLastCalledWith(
    expect.objectContaining({ name: "two.docx" })
  );
});

test("ConversationArtifactsPanel ignores repeat clicks while adding", () => {
  const onAddToComposer = vi.fn(
    () => new Promise<void>(() => {}) // never settles
  );
  renderArtifactsPanel({ onAddToComposer });

  const addButton = screen.getByRole("button", {
    name: "chat.artifacts.addToChat",
  });
  fireEvent.click(addButton);
  fireEvent.click(addButton);

  expect(onAddToComposer).toHaveBeenCalledTimes(1);
});

test("fetchArtifactFile prefers the object storage stream endpoint", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    blob: async () => new Blob(["bytes"]),
  });
  vi.stubGlobal("fetch", fetchMock);

  try {
    const file = await fetchArtifactFile(makeAttachment("a1", "report.pptx"));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/file/download/runs/a1/report.pptx"
    );
    expect(file.name).toBe("report.pptx");
    expect(file.size).toBeGreaterThan(0);
  } finally {
    vi.unstubAllGlobals();
  }
});

test("fetchArtifactFile falls back to the attachment download url", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    blob: async () => new Blob(["bytes"]),
  });
  vi.stubGlobal("fetch", fetchMock);

  try {
    const attachment = makeAttachment("a2", "notes.md", {
      object_name: undefined,
      contentType: "text/markdown",
    });
    const file = await fetchArtifactFile(attachment);

    expect(fetchMock).toHaveBeenCalledWith("/api/storage/download/a2");
    expect(file.name).toBe("notes.md");
    expect(file.type).toBe("text/markdown");
  } finally {
    vi.unstubAllGlobals();
  }
});

test("fetchArtifactFile rejects when no source is available", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);

  try {
    const attachment = makeAttachment("a3", "lost.bin", {
      object_name: undefined,
      preview_url: undefined,
      download_url: undefined,
    });

    await expect(fetchArtifactFile(attachment)).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  } finally {
    vi.unstubAllGlobals();
  }
});

const makePendingAttachment = (file: File, name: string) =>
  ({
    id: `att-${name}`,
    status: { type: "running", reason: "composer-send" },
    type: "file",
    name,
    contentType: "application/vnd.api+json",
    file,
  }) as unknown as Parameters<typeof compositeAttachmentAdapter.send>[0];

test("compositeAttachmentAdapter reuses stored objects for marked files", async () => {
  const meta = {
    object_name: "runs/a1/report.pptx",
    url: "blob:preview-a1",
    type: "application/vnd.api+json",
    size: 2048,
  };
  const file = markFileWithExistingUpload(
    new File(["bytes"], "report.pptx"),
    meta
  );

  const result = await compositeAttachmentAdapter.send(
    makePendingAttachment(file, "report.pptx")
  );

  // The already-stored object must not be uploaded a second time.
  expect(storageServiceMock.uploadFiles).not.toHaveBeenCalled();
  expect(result.status.type).toBe("complete");
  expect(result.content[0]).toMatchObject({
    type: "file",
    data: "blob:preview-a1",
  });
  expect(result).toMatchObject({ object_name: meta.object_name });
});

test("compositeAttachmentAdapter still uploads unmarked files", async () => {
  storageServiceMock.uploadFiles.mockResolvedValue({
    success_count: 1,
    results: [
      {
        success: true,
        object_name: "attachments/report.pptx",
        url: "blob:url",
        presigned_url: "blob:presigned",
        file_size: 2048,
      },
    ],
  });

  const result = await compositeAttachmentAdapter.send(
    makePendingAttachment(new File(["bytes"], "report.pptx"), "report.pptx")
  );

  expect(storageServiceMock.uploadFiles).toHaveBeenCalledTimes(1);
  expect(result.status.type).toBe("complete");
  expect(result).toMatchObject({ object_name: "attachments/report.pptx" });
  expect(result.content[0]).toMatchObject({
    type: "file",
    data: "blob:presigned",
  });
});
