// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { ReadableStream } from "node:stream/web";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";

import ResourceTagChips from "@/components/tag/ResourceTagChips";
import { tagManagementApi } from "@/services/tagManagementService";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import {
  clearAssignmentCache,
  clearCachedAssignmentsByResource,
} from "@/services/tagAssignmentCache";
import type { TagAssignment } from "@/types/tagManagement";

const doubles = vi.hoisted(() => ({ request: vi.fn(), runAgent: vi.fn() }));
vi.mock("@/services/api", async (original) => ({
  ...(await original<typeof import("@/services/api")>()),
  fetchWithErrorHandling: doubles.request,
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: { runAgent: doubles.runAgent },
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
vi.mock("react-i18next", async (original) => ({
  ...(await original<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));

function assignment(id: string, label: string | null): TagAssignment {
  return {
    resource_type: "agent",
    resource_id: id,
    assignment_count: label ? 1 : 0,
    assignment_capacity: 100,
    assignments: label
      ? [
          {
            definition_id: 1,
            definition_key: "department",
            definition_name: "Department",
            selection_mode: "multi_select",
            value_id: 7,
            display_value: label,
            value_status: "active",
          },
        ]
      : [],
  };
}

function response(value: TagAssignment) {
  return { json: async () => value };
}

async function saveEvents(events: unknown[]) {
  doubles.runAgent.mockResolvedValueOnce(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const content of events)
          controller.enqueue(
            new TextEncoder().encode(
              `data: ${JSON.stringify({ type: "nl2a_state", content: JSON.stringify(content) })}\n\n`
            )
          );
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"done","content":""}\n\n')
        );
        controller.close();
      },
    }).getReader()
  );
  const result = remoteChatModelAdapter.run({
    messages: [
      {
        id: "request",
        role: "user",
        content: [{ type: "text", text: "Update tags" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: {
      custom: {
        runtimeMode: "nl2agent",
        agentId: 42,
        modelId: "11",
        persistCreationHistory: true,
      },
    },
    unstable_threadId: "tag-refresh",
  } as unknown as ChatModelRunOptions);
  if (Symbol.asyncIterator in result) {
    for await (const frame of result) {
      void frame;
    }
  } else await result;
}

const saved = (agentId = 42, fields: string[] = ["tags"]) => ({
  event: "agent_draft_fields_saved",
  agent_id: agentId,
  updated_fields: fields,
});

beforeEach(() => {
  clearAssignmentCache();
  doubles.request.mockReset();
  doubles.runAgent.mockReset();
});

it("updates mounted chips on repeated live tag saves and deduplicates reads without refreshing the page", async () => {
  let label: string | null = "Old";
  doubles.request.mockImplementation(async (url: string) => {
    const id = url.split("/").at(-1)!;
    return response(assignment(id, id === "42" ? label : "Other"));
  });
  render(
    <>
      <ResourceTagChips
        resourceType="agent"
        resourceId="42"
        emptyText={<span>Empty</span>}
      />
      <ResourceTagChips
        resourceType="agent"
        resourceId="42"
        emptyText={<span>Empty</span>}
      />
      <ResourceTagChips resourceType="agent" resourceId="43" />
    </>
  );
  await waitFor(() => expect(screen.getAllByText("Old")).toHaveLength(2));
  expect(doubles.request).toHaveBeenCalledTimes(2);
  label = "New";
  await act(async () => saveEvents([saved()]));
  await waitFor(() => expect(screen.getAllByText("New")).toHaveLength(2));
  expect(screen.queryByText("Old")).toBeNull();
  expect(screen.getByText("Other")).toBeInTheDocument();
  expect(doubles.request).toHaveBeenCalledTimes(3);
  label = null;
  await act(async () => saveEvents([saved()]));
  await waitFor(() => expect(screen.getAllByText("Empty")).toHaveLength(2));
  expect(screen.queryByText("New")).toBeNull();
  expect(doubles.request).toHaveBeenCalledTimes(4);
});

it("ignores other-agent, malformed, unrelated-field and failed saves", async () => {
  doubles.request.mockResolvedValue(response(assignment("42", "Original")));
  render(<ResourceTagChips resourceType="agent" resourceId="42" />);
  await screen.findByText("Original");
  await act(async () =>
    saveEvents([
      saved(99),
      saved(42, ["tags", "invalid-field"]),
      saved(42, ["name"]),
      {
        event: "configuration_save_failed",
        agent_id: 42,
        updated_fields: ["tags"],
      },
    ])
  );
  expect(screen.getByText("Original")).toBeInTheDocument();
  expect(doubles.request).toHaveBeenCalledOnce();
});

it.each(["resolve", "reject"])(
  "keeps fresh tags when an older in-flight request later %s",
  async (settlement) => {
    let resolve!: (value: ReturnType<typeof response>) => void;
    let reject!: (error: Error) => void;
    doubles.request.mockReturnValueOnce(
      new Promise((done, fail) => {
        resolve = done;
        reject = fail;
      })
    );
    doubles.request.mockResolvedValue(response(assignment("42", "Fresh")));
    render(<ResourceTagChips resourceType="agent" resourceId="42" />);
    await waitFor(() => expect(doubles.request).toHaveBeenCalledOnce());
    await act(async () => saveEvents([saved()]));
    await screen.findByText("Fresh");
    await act(async () => {
      if (settlement === "resolve")
        resolve(response(assignment("42", "Stale")));
      else reject(new Error("Old request failed"));
    });
    expect(screen.queryByText("Stale")).toBeNull();
    expect(screen.getByText("Fresh")).toBeInTheDocument();
    render(<ResourceTagChips resourceType="agent" resourceId="42" />);
    await waitFor(() => expect(screen.getAllByText("Fresh")).toHaveLength(2));
    expect(doubles.request).toHaveBeenCalledTimes(2);
  }
);

it("unsubscribes unmounted resources and does not refetch them on a later save", async () => {
  doubles.request.mockResolvedValue(response(assignment("42", "Original")));
  const page = render(
    <ResourceTagChips resourceType="agent" resourceId="42" />
  );
  await screen.findByText("Original");
  page.unmount();
  await act(async () => clearCachedAssignmentsByResource("agent", "42"));
  expect(doubles.request).toHaveBeenCalledOnce();
});

it.each([true, false])(
  "refreshes mounted chips only after a successful manual tag write (%s)",
  async (succeeded) => {
    let label = "Original";
    doubles.request.mockImplementation(
      async (_url: string, options?: RequestInit) => {
        if (options?.method === "PUT") {
          if (!succeeded) throw new Error("Save rejected");
          label = "Manual";
        }
        return response(assignment("42", label));
      }
    );
    render(<ResourceTagChips resourceType="agent" resourceId="42" />);
    await screen.findByText("Original");
    await act(async () => {
      const save = tagManagementApi.replaceAssignments("agent", "42", {
        value_ids: [7],
      });
      if (succeeded) await save;
      else await expect(save).rejects.toThrow("Save rejected");
    });
    await screen.findByText(succeeded ? "Manual" : "Original");
    expect(doubles.request).toHaveBeenCalledTimes(succeeded ? 3 : 2);
  }
);
