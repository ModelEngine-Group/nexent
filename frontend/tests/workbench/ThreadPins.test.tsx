// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { conversationService } from "@/services/conversationService";
import type { WorkbenchPinItem, WorkbenchPins } from "@/types/conversation";
import {
  PinnedThreadsProvider,
  usePinnedThreads,
  getThreadPinKey,
  getWorkbenchPinStorageKey,
  parsePinnedThreadIds,
  hoistPinnedThreads,
  type ThreadPinIdentity,
} from "@/app/newchat/assistant-ui/thread-pins";

const scope = getWorkbenchPinStorageKey("user-a", "tenant-a");
const saved = { id: "local-a", remoteId: "42" };

function Probe({ thread = saved }: { thread?: ThreadPinIdentity }) {
  const pins = usePinnedThreads()!;
  return (
    <>
      <output data-testid="pinned">{String(pins.isPinned(thread))}</output>
      <button
        disabled={!pins.canPin(thread)}
        onClick={() => pins.togglePin(thread)}
      >
        Toggle
      </button>
      <button
        onClick={() => {
          pins.togglePin(thread);
          pins.togglePin(thread);
        }}
      >
        Toggle twice
      </button>
    </>
  );
}

let client: QueryClient;
let activeScope: string | null;
let serverPins: Map<string, WorkbenchPinItem[]>;

const pin = (
  id: number,
  conversationType: "workbench" | "agent_chat" = "workbench"
): WorkbenchPinItem => ({
  conversation_id: id,
  conversation_title: `History ${id}`,
  conversation_type: conversationType,
  create_time: 1,
  update_time: 1,
  pinned_at: "2026-11-05T00:00:00Z",
});

function view(
  children: ComponentProps<typeof PinnedThreadsProvider>["children"],
  props: Omit<ComponentProps<typeof PinnedThreadsProvider>, "children"> = {}
) {
  // Authentication scopes the API; storageKey independently scopes its cache.
  activeScope = props.storageKey === undefined ? scope : props.storageKey;
  return (
    <QueryClientProvider client={client}>
      <PinnedThreadsProvider storageKey={scope} {...props}>
        {children}
      </PinnedThreadsProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  activeScope = scope;
  serverPins = new Map();
  vi.spyOn(conversationService, "getWorkbenchPins").mockImplementation(
    async () => ({
      items: [...(serverPins.get(activeScope!) ?? [])],
    })
  );
  vi.spyOn(conversationService, "setWorkbenchPin").mockImplementation(
    async (id, pinned) => {
      const items = (serverPins.get(activeScope!) ?? []).filter(
        (item) => item.conversation_id !== id
      );
      if (pinned) items.unshift(pin(id));
      serverPins.set(activeScope!, items);
      return { items: [...items] };
    }
  );
});

afterEach(() => {
  cleanup();
  client.clear();
});

function OrderedPins() {
  const pins = usePinnedThreads()!;
  const threads = [saved, { id: "local-b", remoteId: "43" }];
  const groups = hoistPinnedThreads(
    [{ label: "recent", entries: threads }],
    pins.isPinned,
    pins.getPinOrder
  );
  const order =
    groups
      .find((group) => group.label === "chat.threadList.pinned")
      ?.entries.map((thread) => thread.remoteId)
      .join(",") ?? "";
  return (
    <>
      <output data-testid="pin-order">{order}</output>
      {threads.map((thread) => (
        <button
          key={thread.id}
          disabled={!pins.canPin(thread)}
          onClick={() => pins.togglePin(thread)}
        >
          {thread.remoteId}
        </button>
      ))}
    </>
  );
}

it("latest server pin and repin appear first and retain their order after a fresh-cache reload", async () => {
  localStorage.setItem(scope, '["999"]');
  const toggle = async (id: string, order: string) => {
    await waitFor(() =>
      expect(screen.getByRole("button", { name: id })).toBeEnabled()
    );
    fireEvent.click(screen.getByRole("button", { name: id }));
    await waitFor(() =>
      expect(screen.getByTestId("pin-order").textContent).toBe(order)
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: id })).toBeEnabled()
    );
  };
  const first = render(view(<OrderedPins />));
  await toggle("42", "42");
  await toggle("43", "43,42");
  first.unmount();
  client.clear();
  const second = render(view(<OrderedPins />));
  await waitFor(() =>
    expect(screen.getByTestId("pin-order")).toHaveTextContent("43,42")
  );
  await toggle("42", "43");
  await toggle("42", "42,43");
  expect(localStorage.getItem(scope)).toBe('["999"]');
  second.unmount();
  client.clear();
  render(view(<OrderedPins />));
  await waitFor(() =>
    expect(screen.getByTestId("pin-order")).toHaveTextContent("42,43")
  );
  expect(conversationService.getWorkbenchPins).toHaveBeenCalledTimes(3);
  expect(vi.mocked(conversationService.setWorkbenchPin).mock.calls).toEqual([
    [42, true],
    [43, true],
    [42, false],
    [42, true],
  ]);
});

it("pin insertion order overrides history age while ordinary recency stays intact", () => {
  const groups = [
    {
      label: "today",
      entries: [
        { id: "recent", rank: 0 },
        { id: "ordinary-a", rank: -1 },
      ],
    },
    {
      label: "older",
      entries: [
        { id: "older", rank: 1 },
        { id: "ordinary-b", rank: -1 },
      ],
    },
  ];
  const original = structuredClone(groups);
  const ordered = hoistPinnedThreads(
    groups,
    (entry) => entry.rank >= 0,
    (entry) => entry.rank
  );
  expect(ordered[0].entries.map((entry) => entry.id)).toEqual([
    "older",
    "recent",
  ]);
  expect(
    ordered
      .slice(1)
      .flatMap((group) => group.entries)
      .map((entry) => entry.id)
  ).toEqual(["ordinary-a", "ordinary-b"]);
  expect(groups).toEqual(original);
  expect(
    hoistPinnedThreads(groups, (entry) => entry.rank >= 0)[0].entries.map(
      (entry) => entry.id
    )
  ).toEqual(["recent", "older"]);
});

it("persists server identity through a fresh cache and local-ID changes", async () => {
  const first = render(view(<Probe />));
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("true")
  );
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  first.unmount();
  client.clear();
  render(view(<Probe thread={{ id: "new-local-id", remoteId: "42" }} />));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("true")
  );
  fireEvent.click(screen.getByText("Toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("false")
  );
  expect(vi.mocked(conversationService.setWorkbenchPin).mock.calls).toEqual([
    [42, true],
    [42, false],
  ]);
  expect(serverPins.get(scope)).toEqual([]);
});

it("isolates user and tenant scopes and disables pinning without an identity", async () => {
  serverPins.set(scope, [pin(42)]);
  const { rerender } = render(view(<Probe />));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("true")
  );
  for (const key of [
    getWorkbenchPinStorageKey("user-b", "tenant-a"),
    getWorkbenchPinStorageKey("user-a", "tenant-b"),
  ]) {
    rerender(view(<Probe />, { storageKey: key }));
    expect(screen.getByTestId("pinned")).toHaveTextContent("false");
    await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
    expect(screen.getByTestId("pinned")).toHaveTextContent("false");
  }
  const reads = vi.mocked(conversationService.getWorkbenchPins).mock.calls
    .length;
  rerender(view(<Probe />, { storageKey: null }));
  expect(screen.getByText("Toggle")).toBeDisabled();
  fireEvent.click(screen.getByText("Toggle"));
  expect(conversationService.getWorkbenchPins).toHaveBeenCalledTimes(reads);
  expect(conversationService.setWorkbenchPin).not.toHaveBeenCalled();
  rerender(view(<Probe />));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("true")
  );
});

it("uses the persisted mapping for an initialized draft and blocks unsent drafts", async () => {
  const draft = { id: "draft", remoteId: "workbench-draft:draft" };
  const { rerender } = render(view(<Probe thread={draft} />));
  await waitFor(() =>
    expect(conversationService.getWorkbenchPins).toHaveBeenCalledTimes(1)
  );
  expect(screen.getByText("Toggle")).toBeDisabled();
  fireEvent.click(screen.getByText("Toggle"));
  expect(conversationService.setWorkbenchPin).not.toHaveBeenCalled();
  rerender(
    view(<Probe thread={draft} />, {
      serverConversationIds: new Map([["draft", "51"]]),
    })
  );
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("true")
  );
  expect(conversationService.setWorkbenchPin).toHaveBeenCalledExactlyOnceWith(
    51,
    true
  );
});

it("filters server pins by conversation type and ignores legacy local identities", async () => {
  localStorage.setItem("chat.pinnedThreadIds", '["local-a"]');
  serverPins.set(scope, [pin(42), pin(43, "agent_chat")]);
  const thread = { id: "local-a", remoteId: "43" };
  const { rerender } = render(
    view(<Probe thread={thread} />, { conversationType: "agent_chat" })
  );
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("true")
  );
  rerender(view(<Probe thread={saved} />, { conversationType: "agent_chat" }));
  expect(screen.getByTestId("pinned")).toHaveTextContent("false");
  rerender(view(<Probe thread={thread} />, { conversationType: "workbench" }));
  expect(screen.getByTestId("pinned")).toHaveTextContent("false");
  rerender(view(<Probe thread={saved} />));
  expect(screen.getByTestId("pinned")).toHaveTextContent("true");
  expect(localStorage.getItem("chat.pinnedThreadIds")).toBe('["local-a"]');
  expect(conversationService.setWorkbenchPin).not.toHaveBeenCalled();
});

it("ignores a duplicate toggle while a save is pending and permits unpin after acknowledgment", async () => {
  let finish!: (value: WorkbenchPins) => void;
  const save = vi
    .mocked(conversationService.setWorkbenchPin)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
  render(view(<Probe />));
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle twice"));
  await waitFor(() => expect(save).toHaveBeenCalledExactlyOnceWith(42, true));
  expect(screen.getByTestId("pinned")).toHaveTextContent("false");
  expect(screen.getByText("Toggle")).toBeDisabled();
  serverPins.set(scope, [pin(42)]);
  await act(async () => finish({ items: [pin(42)] }));
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  expect(screen.getByTestId("pinned")).toHaveTextContent("true");
  fireEvent.click(screen.getByText("Toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("false")
  );
  expect(save).toHaveBeenNthCalledWith(2, 42, false);
  expect(save).toHaveBeenCalledTimes(2);
});

it("keeps server pin/unpin usable without reading or writing browser storage", async () => {
  const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("Storage unavailable");
  });
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Quota exceeded");
  });
  const warning = vi.fn();
  render(view(<Probe />, { onStorageError: warning }));
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("true")
  );
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("pinned")).toHaveTextContent("false")
  );
  expect(vi.mocked(conversationService.setWorkbenchPin).mock.calls).toEqual([
    [42, true],
    [42, false],
  ]);
  expect(get).not.toHaveBeenCalled();
  expect(set).not.toHaveBeenCalled();
  expect(warning).not.toHaveBeenCalled();
});

it.each([
  undefined,
  "0",
  "-1",
  "1.5",
  "NaN",
  "workbench-draft:a",
  "9007199254740992",
])("rejects invalid persisted conversation identity %s", (remoteId) => {
  expect(getThreadPinKey({ id: "local", remoteId }, true)).toBeUndefined();
});

it("prioritizes valid server mappings and falls back to valid remote identity", () => {
  expect(getThreadPinKey(saved, true, new Map([["local-a", "43"]]))).toBe("43");
  expect(getThreadPinKey(saved, true, new Map([["local-a", "invalid"]]))).toBe(
    "42"
  );
  expect(getThreadPinKey(saved)).toBe("local-a");
});

it.each([null, "invalid JSON", "{}", "null", "42"])(
  "tolerates invalid stored pins %s",
  (raw) => {
    expect([...parsePinnedThreadIds(raw)]).toEqual([]);
  }
);

it("ignores invalid stored entries and deduplicates IDs", () => {
  expect([...parsePinnedThreadIds('["42",42,null,"","42"]')]).toEqual(["42"]);
});

it("hoists only supplied visible histories and preserves recency within both groups", () => {
  const groups = [
    { label: "today", entries: [{ id: "a" }, { id: "b" }] },
    { label: "older", entries: [{ id: "c" }, { id: "d" }] },
  ];
  const before = structuredClone(groups);
  expect(
    hoistPinnedThreads(groups, ({ id }) =>
      ["b", "c", "filtered-out"].includes(id)
    )
  ).toEqual([
    { label: "chat.threadList.pinned", entries: [{ id: "b" }, { id: "c" }] },
    { label: "today", entries: [{ id: "a" }] },
    { label: "older", entries: [{ id: "d" }] },
  ]);
  expect(groups).toEqual(before);
  expect(hoistPinnedThreads([], () => true)).toEqual([]);
});

it("hoists undated histories and omits an empty pinned group", () => {
  const recent = [{ label: "recent", entries: [{ id: "a" }, { id: "b" }] }];
  expect(hoistPinnedThreads(recent, ({ id }) => id === "b")[0]).toEqual({
    label: "chat.threadList.pinned",
    entries: [{ id: "b" }],
  });
  expect(hoistPinnedThreads(recent, () => false)).toEqual(recent);
});
