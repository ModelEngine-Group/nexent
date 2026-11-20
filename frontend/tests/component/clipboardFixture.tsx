// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React, { useState } from "react";
import {
  ActionBarPrimitive,
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useLocalRuntime,
} from "@assistant-ui/react";
import {
  useClipboardCopy,
  useMessageClipboardCopy,
} from "@/hooks/useClipboardCopy";

export const sampleAnswer =
  "政策分析 SYNTHETIC_TEST\n\n第一项：可追溯\n\n\n```python\n    value = 1\n\n\n    print(value)\n```\n";
export const sampleCode = "\n    value = 1\n\n\n    print(value)\n";

function AssistantMessage({ unpatched = false }: { unpatched?: boolean }) {
  const [error, setError] = useState("");
  const { onCopy, isCopying } = useMessageClipboardCopy(() =>
    setError("Copy failed")
  );
  const copied = useAuiState((s) => s.message.isCopied);
  const visibleText = useAuiState((s) =>
    s.message.content
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("")
  );
  return (
    <MessagePrimitive.Root>
      <pre>{visibleText}</pre>
      <ActionBarPrimitive.Root>
        <ActionBarPrimitive.Copy
          asChild
          onClick={unpatched ? undefined : onCopy}
          disabled={isCopying}
        >
          <button data-testid="answer-copy">Copy answer</button>
        </ActionBarPrimitive.Copy>
      </ActionBarPrimitive.Root>
      <output data-testid="answer-status">
        {copied ? "Copied" : error || "Ready"}
      </output>
    </MessagePrimitive.Root>
  );
}

function UnpatchedMessage() {
  return <AssistantMessage unpatched />;
}

export function ClipboardFixture({
  empty = false,
  unpatched = false,
  text = sampleAnswer,
}: {
  empty?: boolean;
  unpatched?: boolean;
  text?: string;
}) {
  const runtime = useLocalRuntime(
    { run: async () => ({ content: [] }) },
    {
      initialMessages: [
        {
          id: "synthetic-answer",
          role: "assistant",
          content: empty
            ? []
            : [
                { type: "reasoning", text: "PRIVATE_REASONING_MUST_NOT_COPY" },
                { type: "text", text },
              ],
        },
      ],
    }
  );
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root>
        <ThreadPrimitive.Messages
          components={{
            AssistantMessage: unpatched ? UnpatchedMessage : AssistantMessage,
            UserMessage: () => null,
          }}
        />
      </ThreadPrimitive.Root>
      <CodeFixture />
      <textarea aria-label="Paste target" data-testid="paste-target" />
    </AssistantRuntimeProvider>
  );
}

function CodeFixture() {
  const [error, setError] = useState("");
  const { copy, isCopied, isCopying } = useClipboardCopy({
    scopeKey: sampleCode,
    onError: () => setError("Copy failed"),
  });
  return (
    <section>
      <button
        data-testid="code-copy"
        disabled={isCopying}
        onClick={() => {
          void copy(sampleCode);
        }}
      >
        Copy code
      </button>
      <output data-testid="code-status">
        {isCopied ? "Copied" : error || "Ready"}
      </output>
    </section>
  );
}
