import { useEffect, useState } from "react";
import { render, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";
import {
  AssistantRuntimeProvider,
  useAuiState,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type RemoteThreadListAdapter,
} from "@assistant-ui/react";

/**
 * Mirrors the WorkbenchSessionProvider wiring with a deterministic in-memory
 * adapter so the deep-link restore path can be asserted without a backend.
 *
 * The provider reads the conversation id from the URL synchronously in a
 * useState initializer. This matters: child effects (WorkbenchPage's URL sync)
 * run before the provider's own effects on mount and may clean the URL while
 * the restore is still starting, so a mount effect would lose the race.
 */

const observed: {
  mainThreadId: string | undefined;
  remoteId: string | null;
  status: string | null;
} = { mainThreadId: undefined, remoteId: null, status: null };

const fetchCalls: string[] = [];

const testAdapter: RemoteThreadListAdapter = {
  async list() {
    return {
      threads: [{ remoteId: "42", status: "regular", title: "111" }],
    };
  },
  async rename() {},
  async archive() {},
  async unarchive() {},
  async delete() {},
  async initialize() {
    return { remoteId: "", externalId: "" };
  },
  async generateTitle() {
    throw new Error("generateTitle is not exercised in this test");
  },
  async fetch(threadId: string) {
    fetchCalls.push(threadId);
    return { remoteId: threadId, status: "regular", title: "fetched" };
  },
};

const modelAdapter = {
  run() {
    throw new Error("model runs are not exercised in this test");
  },
};

function Probe() {
  const mainThreadId = useAuiState((s) => s.threads.mainThreadId);
  const items = useAuiState((s) => s.threads.threadItems);
  const active = items.find((item) => item.id === mainThreadId);
  useEffect(() => {
    observed.mainThreadId = mainThreadId;
    observed.remoteId = active?.remoteId ?? null;
    observed.status = active?.status ?? null;
  });
  return null;
}

/** Mirrors WorkbenchPage's URL sync: wipes the param while on a placeholder. */
function UrlWipingChild({ enabled }: { enabled: boolean }) {
  useEffect(() => {
    if (!enabled) return;
    const url = new URL(window.location.href);
    if (url.searchParams.has("conversation_id")) {
      url.searchParams.delete("conversation_id");
      window.history.replaceState({}, "", url.toString());
    }
  }, [enabled]);
  return null;
}

function Harness({
  childWipesUrl,
  lateThreadId,
}: {
  childWipesUrl?: boolean;
  lateThreadId?: string;
}) {
  // Fixed provider pattern: synchronous read on the first render.
  const [requestedThreadId] = useState<string | undefined>(() => {
    if (typeof window === "undefined") return undefined;
    const searchParams = new URLSearchParams(window.location.search);
    return (
      searchParams.get("thread_id") ??
      searchParams.get("conversation_id") ??
      undefined
    );
  });

  // Library capability: a late threadId change must still switch threads.
  const [lateRequested, setLateRequested] = useState<string | undefined>(
    undefined
  );
  useEffect(() => {
    if (lateThreadId !== undefined) {
      // Test-only simulation of a prop arriving after mount; the production
      // provider reads the URL synchronously and never does this.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLateRequested(lateThreadId);
    }
  }, [lateThreadId]);

  const runtime = useRemoteThreadListRuntime({
    runtimeHook: function useWorkbenchRuntime() {
      return useLocalRuntime(modelAdapter);
    },
    adapter: testAdapter,
    threadId: requestedThreadId ?? lateRequested,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <UrlWipingChild enabled={childWipesUrl === true} />
      <Probe />
    </AssistantRuntimeProvider>
  );
}

it("UT-FE-WB-035 restores a deep-linked conversation even when a child effect wipes the URL on mount", async () => {
  window.history.replaceState({}, "", "/zh/workbench?conversation_id=42");
  render(<Harness childWipesUrl />);
  await waitFor(
    () => {
      expect(observed.remoteId).toBe("42");
      expect(observed.status).toBe("regular");
    },
    { timeout: 5000 }
  );
});

it("UT-FE-WB-035 restores a deep-linked conversation outside the first list page via fetch", async () => {
  fetchCalls.length = 0;
  window.history.replaceState({}, "", "/zh/workbench?conversation_id=99");
  render(<Harness />);
  await waitFor(
    () => {
      expect(observed.remoteId).toBe("99");
      expect(observed.status).toBe("regular");
    },
    { timeout: 5000 }
  );
  expect(fetchCalls).toContain("99");
});

it("UT-FE-WB-035 switches when the thread id arrives after mount", async () => {
  window.history.replaceState({}, "", "/zh/workbench");
  render(<Harness lateThreadId="42" />);
  await waitFor(
    () => {
      expect(observed.remoteId).toBe("42");
      expect(observed.status).toBe("regular");
    },
    { timeout: 5000 }
  );
});

it("UT-FE-WB-035 stays on a new thread when the URL carries no conversation id", async () => {
  fetchCalls.length = 0;
  window.history.replaceState({}, "", "/zh/workbench");
  render(<Harness />);
  await waitFor(() => {
    expect(observed.mainThreadId).toBeDefined();
  });
  expect(observed.remoteId).toBeNull();
  expect(fetchCalls).toEqual([]);
});
