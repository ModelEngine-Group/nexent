import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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

beforeEach(() => window.localStorage.clear());

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
        <button key={thread.id} onClick={() => pins.togglePin(thread)}>
          {thread.remoteId}
        </button>
      ))}
    </>
  );
}

it("latest pin and repin appear first and retain their order after reload", () => {
  const view = () => (
    <PinnedThreadsProvider storageKey={scope} persistedConversationIds>
      <OrderedPins />
    </PinnedThreadsProvider>
  );
  const first = render(view());
  fireEvent.click(screen.getByText("42"));
  fireEvent.click(screen.getByText("43"));
  expect(screen.getByTestId("pin-order")).toHaveTextContent("43,42");
  first.unmount();
  const second = render(view());
  expect(screen.getByTestId("pin-order")).toHaveTextContent("43,42");
  fireEvent.click(screen.getByText("42"));
  expect(screen.getByTestId("pin-order")).toHaveTextContent("43");
  fireEvent.click(screen.getByText("42"));
  expect(screen.getByTestId("pin-order")).toHaveTextContent("42,43");
  expect(localStorage.getItem(scope)).toBe('["43","42"]');
  second.unmount();
  render(view());
  expect(screen.getByTestId("pin-order")).toHaveTextContent("42,43");
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

it("persists server identity through reload and local-ID changes", () => {
  const first = render(
    <PinnedThreadsProvider storageKey={scope} persistedConversationIds>
      <Probe />
    </PinnedThreadsProvider>
  );
  fireEvent.click(screen.getByText("Toggle"));
  expect(screen.getByTestId("pinned")).toHaveTextContent("true");
  expect(JSON.parse(localStorage.getItem(scope)!)).toEqual(["42"]);
  first.unmount();
  render(
    <PinnedThreadsProvider storageKey={scope} persistedConversationIds>
      <Probe thread={{ id: "new-local-id", remoteId: "42" }} />
    </PinnedThreadsProvider>
  );
  expect(screen.getByTestId("pinned")).toHaveTextContent("true");
  fireEvent.click(screen.getByText("Toggle"));
  expect(JSON.parse(localStorage.getItem(scope)!)).toEqual([]);
});

it("resets user and tenant scopes without carrying pin state across identities", () => {
  localStorage.setItem(scope, '["42"]');
  const view = (key: string | null) => (
    <PinnedThreadsProvider storageKey={key} persistedConversationIds>
      <Probe />
    </PinnedThreadsProvider>
  );
  const { rerender } = render(view(scope));
  expect(screen.getByTestId("pinned")).toHaveTextContent("true");
  rerender(view(getWorkbenchPinStorageKey("user-b", "tenant-a")));
  expect(screen.getByTestId("pinned")).toHaveTextContent("false");
  rerender(view(getWorkbenchPinStorageKey("user-a", "tenant-b")));
  expect(screen.getByTestId("pinned")).toHaveTextContent("false");
  rerender(view(null));
  expect(screen.getByText("Toggle")).toBeDisabled();
  rerender(view(scope));
  expect(screen.getByTestId("pinned")).toHaveTextContent("true");
});

it("uses the persisted mapping for an initialized draft and blocks unsent drafts", () => {
  const draft = { id: "draft", remoteId: "workbench-draft:draft" };
  const { rerender } = render(
    <PinnedThreadsProvider storageKey={scope} persistedConversationIds>
      <Probe thread={draft} />
    </PinnedThreadsProvider>
  );
  expect(screen.getByText("Toggle")).toBeDisabled();
  rerender(
    <PinnedThreadsProvider
      storageKey={scope}
      persistedConversationIds
      serverConversationIds={new Map([["draft", "51"]])}
    >
      <Probe thread={draft} />
    </PinnedThreadsProvider>
  );
  expect(screen.getByText("Toggle")).toBeEnabled();
  fireEvent.click(screen.getByText("Toggle"));
  expect(JSON.parse(localStorage.getItem(scope)!)).toEqual(["51"]);
});

it("retains the Agent-chat storage key and local identity contract", () => {
  localStorage.setItem("chat.pinnedThreadIds", '["local-a"]');
  localStorage.setItem(scope, '["99"]');
  render(
    <PinnedThreadsProvider>
      <Probe />
    </PinnedThreadsProvider>
  );
  expect(screen.getByTestId("pinned")).toHaveTextContent("true");
  fireEvent.click(screen.getByText("Toggle"));
  expect(localStorage.getItem("chat.pinnedThreadIds")).toBe("[]");
  expect(localStorage.getItem(scope)).toBe('["99"]');
});

it("handles two toggles before rerender without losing the second update", () => {
  render(
    <PinnedThreadsProvider storageKey={scope} persistedConversationIds>
      <Probe />
    </PinnedThreadsProvider>
  );
  fireEvent.click(screen.getByText("Toggle twice"));
  expect(screen.getByTestId("pinned")).toHaveTextContent("false");
  expect(localStorage.getItem(scope)).toBe("[]");
});

it("keeps pin/unpin usable when browser storage cannot be read or written", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("Storage unavailable");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Quota exceeded");
  });
  const warning = vi.fn();
  render(
    <PinnedThreadsProvider
      storageKey={scope}
      persistedConversationIds
      onStorageError={warning}
    >
      <Probe />
    </PinnedThreadsProvider>
  );
  fireEvent.click(screen.getByText("Toggle"));
  expect(screen.getByTestId("pinned")).toHaveTextContent("true");
  fireEvent.click(screen.getByText("Toggle"));
  expect(screen.getByTestId("pinned")).toHaveTextContent("false");
  expect(warning).toHaveBeenCalledTimes(2);
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
