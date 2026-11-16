// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {useState, type ReactNode} from "react";
import {App} from "antd";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {patchModelDraft, readModelDraft} from "@/lib/conversationModelDrafts";
import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import type { ModelOption } from "@/app/newchat/ui/model-selector";
import {
  ConversationModelControlsProvider,
  useBindConversationModelThread,
  useConversationModelThreadKey,
} from "@/features/model-controls/ConversationModelControlsProvider";
import { useConversationModelControls } from "@/features/model-controls/useConversationModelControls";
import { rejectModelSelection } from "@/features/model-controls/rejectedSelection";

const models: ModelOption[] = [
  { id: "1", name: "Default" },
  {
    id: "2",
    name: "Selected",
    defaultDeepThinking: true,
    defaultEffort: "high",
    efforts: [{ id: "high", name: "High" }],
  },
];
function BaseWrapper({children}: {children: ReactNode}) {
  const [client] = useState(() => new QueryClient({defaultOptions:{queries:{retry:false}}}));
  return <App><QueryClientProvider client={client}>{children}</QueryClientProvider></App>;
}
const wrapper = ({children}: {children: ReactNode}) => <BaseWrapper><ConversationModelControlsProvider>{children}</ConversationModelControlsProvider></BaseWrapper>;

function useControls(
  local: string,
  remote?: string,
  options = models,
  agent = "7"
) {
  const key = useConversationModelThreadKey(local, remote);
  const bind = useBindConversationModelThread();
  const controls = useConversationModelControls(
    options,
    `tenant:user:${agent}:${key}`,
    "1"
  );
  return { key, bind, controls };
}

it("retains edits made after the first server response when reopening a new conversation", () => {
  const { result, rerender } = renderHook(
    ({ local, remote }) => useControls(local, remote),
    {
      wrapper,
      initialProps: {
        local: "draft-a",
        remote: undefined as string | undefined,
      },
    }
  );
  const defaultSnapshot = result.current.controls.snapshot;
  act(() => result.current.bind!("draft-a", "990"));
  expect(result.current.controls.snapshot).toBe(defaultSnapshot);
  act(() => result.current.controls.onModelChange("2"));
  act(() => patchModelDraft(`tenant:user:7:${result.current.key}`, 2, {reasoning_effort:"low"}, []));
  act(() =>
    patchModelDraft(`tenant:user:7:${result.current.key}`, 2, {temperature:0,top_p:0.37}, [])
  );
  const firstSelected = result.current.controls.snapshot;
  expect(firstSelected).toEqual({model_id:2});
  expect(readModelDraft(`tenant:user:7:${result.current.key}`, 2)).toMatchObject({temperature:0,top_p:0.37,reasoning_effort:"low"});
  rerender({ local: "historical-runtime-slot", remote: "990" });
  expect(result.current.controls.selectedModelId).toBe("2");
  expect(result.current.key).toBe("draft-a");
  expect(result.current.controls.snapshot).toBe(firstSelected);
  act(() => patchModelDraft(`tenant:user:7:${result.current.key}`, 2, {enable_thinking:false}, []));
  rerender({ local: "draft-a", remote: "" });
  expect(result.current.controls.selectedModelId).toBe("2");
  expect(readModelDraft(`tenant:user:7:${result.current.key}`, 2)).toMatchObject({temperature:0,top_p:0.37,enable_thinking:false,reasoning_effort:"low"});
  expect(result.current.controls.snapshot).toEqual({model_id:2});
});

it("isolates drafts and Agent scopes through background and duplicate identity binding", () => {
  const { result, rerender } = renderHook(
    ({ local, remote, options, agent }) =>
      useControls(local, remote, options, agent),
    {
      wrapper,
      initialProps: {
        local: "draft-a",
        remote: undefined as string | undefined,
        options: models,
        agent: "7",
      },
    }
  );
  act(() => result.current.controls.onModelChange("2"));
  rerender({ local: "draft-b", remote: "", options: models, agent: "7" });
  act(() => result.current.bind!("draft-a", "990"));
  act(() => result.current.bind!("draft-b", "991"));
  expect(result.current.controls.selectedModelId).toBe("1");
  rerender({ local: "remote-a", remote: "990", options: models, agent: "7" });
  expect(result.current.controls.selectedModelId).toBe("2");
  act(() => result.current.bind!("new-runtime-slot", "990"));
  act(() => result.current.bind!("other", "invalid"));
  expect(result.current.key).toBe("draft-a");
  act(() => rejectModelSelection(2));
  rerender({
    local: "another-runtime-slot",
    remote: "990",
    options: models,
    agent: "7",
  });
  expect(result.current.controls.canSend).toBe(false);
  act(() => result.current.controls.onModelChange("2"));
  rerender({
    local: "another-runtime-slot",
    remote: "990",
    options: [models[0]],
    agent: "7",
  });
  expect(result.current.controls.selectedModelId).toBe("2");
  expect(result.current.controls.canSend).toBe(false);
  rerender({ local: "remote-b", remote: "991", options: models, agent: "7" });
  expect(result.current.controls.selectedModelId).toBe("1");
  rerender({ local: "remote-a", remote: "990", options: models, agent: "8" });
  expect(result.current.controls.selectedModelId).toBe("1");
});

it("keeps unbound histories stable and preserves local keys without the ordinary page provider", () => {
  const history = renderHook(() => useControls("runtime-a", "990"), {
    wrapper,
  });
  expect(history.result.current.key).toBe("990");
  const local = renderHook(({ remote }) => useControls("local", remote), {
    initialProps: { remote: "990" },
    wrapper: BaseWrapper,
  });
  expect(local.result.current.bind).toBeUndefined();
  act(() => local.result.current.controls.onModelChange("2"));
  local.rerender({ remote: "991" });
  expect(local.result.current.key).toBe("local");
  expect(local.result.current.controls.selectedModelId).toBe("2");
});
