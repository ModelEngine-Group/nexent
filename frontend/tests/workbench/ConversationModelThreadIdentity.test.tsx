// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
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
const wrapper = ({ children }: { children: ReactNode }) => (
  <ConversationModelControlsProvider>
    {children}
  </ConversationModelControlsProvider>
);

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
  act(() => result.current.controls.onThinkingEffortChange("auto"));
  act(() =>
    result.current.controls.modelParameterSettings.onChange({
      temperature: 0,
      top_p: 0.37,
    })
  );
  const firstSelected = result.current.controls.snapshot;
  expect(firstSelected).toEqual({
    model_id: 2,
    generation_config: {
      deep_thinking: true,
      thinking_effort: "auto",
      temperature: 0,
      top_p: 0.37,
    },
  });
  rerender({ local: "historical-runtime-slot", remote: "990" });
  expect(result.current.controls.selectedModelId).toBe("2");
  expect(result.current.key).toBe("draft-a");
  expect(result.current.controls.snapshot).toBe(firstSelected);
  act(() => result.current.controls.onDeepThinkingChange(false));
  rerender({ local: "draft-a", remote: "" });
  expect(result.current.controls.selectedModelId).toBe("2");
  expect(result.current.controls.deepThinking).toBe(false);
  expect(result.current.controls.modelParameterSettings.value).toEqual({
    temperature: 0,
    top_p: 0.37,
  });
  expect(firstSelected?.generation_config.deep_thinking).toBe(true);
  expect(defaultSnapshot?.model_id).toBe(1);
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
  });
  expect(local.result.current.bind).toBeUndefined();
  act(() => local.result.current.controls.onModelChange("2"));
  local.rerender({ remote: "991" });
  expect(local.result.current.key).toBe("local");
  expect(local.result.current.controls.selectedModelId).toBe("2");
});
