"use client";

import { useAuiState } from "@assistant-ui/react";
import type { SyntaxHighlighterProps } from "@assistant-ui/react-markdown";

import { tryRenderNl2AgentCard } from "./index";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export const resolveNl2AgentPersistedMessageId = (
  persistedMessageId: unknown,
  runtimeMessageId: unknown
): number | undefined => {
  for (const candidate of [persistedMessageId, runtimeMessageId]) {
    if (
      typeof candidate === "boolean" ||
      (typeof candidate === "string" && candidate.trim() === "")
    ) {
      continue;
    }
    const numericId = Number(candidate);
    if (Number.isInteger(numericId) && numericId > 0) return numericId;
  }
  return undefined;
};

export const Nl2AgentFenceRenderer = ({
  language,
  code,
}: SyntaxHighlighterProps) => {
  const workflow = useNl2AgentWorkflow();
  const { agentId, editable } = workflow;
  const complete = useAuiState((s) => s.message.status?.type === "complete");
  const latest = useAuiState(
    (s) => s.thread.messages.at(-1)?.id === s.message.id
  );
  const interactive = complete && latest && editable;

  if (!complete) {
    return (
      <div className="my-2 rounded border border-dashed p-3 text-xs text-muted-foreground">
        Generating agent configuration card…
      </div>
    );
  }

  const rendered = tryRenderNl2AgentCard(language, code, agentId);
  if (!rendered) return null;
  return (
    <div
      className={interactive ? undefined : "pointer-events-none opacity-75"}
      aria-disabled={!interactive}
    >
      {rendered}
    </div>
  );
};

const languages = [
  "nl2agent-requirements-summary",
  "nl2agent-model-selection",
  "nl2agent-local-resources",
  "nl2agent-web-mcp",
  "nl2agent-web-mcps",
  "nl2agent-web-skill",
  "nl2agent-web-skills",
  "nl2agent-agent-identity",
  "nl2agent-finalize",
] as const;

type Nl2AgentFenceLanguage = (typeof languages)[number];

// @assistant-ui/react-markdown 0.14.x extracts fenced languages with `\w+`,
// which truncates every canonical `nl2agent-*` tag to `nl2agent`. Feed it a
// word-only alias and restore the canonical language before card validation.
const languageAliases = Object.fromEntries(
  languages.map((language) => [language, language.replaceAll("-", "")])
) as Record<Nl2AgentFenceLanguage, string>;

const languageByAlias = Object.fromEntries(
  Object.entries(languageAliases).map(([language, alias]) => [alias, language])
) as Record<string, Nl2AgentFenceLanguage>;

export const preprocessNl2AgentFences = (content: string): string =>
  content.replace(
    /^([ \t]*)(`{3,}|~{3,})(nl2agent-[\w-]+)([^\S\r\n]*)$/gm,
    (line, indentation, marker, language, trailing) => {
      const alias = languageAliases[language as Nl2AgentFenceLanguage];
      return alias ? `${indentation}${marker}${alias}${trailing}` : line;
    }
  );

const HiddenCodeHeader = () => null;

export const nl2AgentComponentsByLanguage = Object.fromEntries(
  Object.entries(languageByAlias).map(([alias, language]) => {
    const CanonicalNl2AgentFenceRenderer = (props: SyntaxHighlighterProps) => (
      <Nl2AgentFenceRenderer {...props} language={language} />
    );
    return [
      alias,
      {
        SyntaxHighlighter: CanonicalNl2AgentFenceRenderer,
        CodeHeader: HiddenCodeHeader,
      },
    ];
  })
);

export const Nl2AgentMessageLifecycle = () => null;
