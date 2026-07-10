"use client";

import React from "react";
import { LocalResourcesCard, LocalResourceItem } from "./LocalResourcesCard";
import { WebMcpCard, WebMcpCardItem } from "./WebMcpCard";
import { WebSkillCard, WebSkillCardItem } from "./WebSkillCard";
import { FinalizeCard } from "./FinalizeCard";

/**
 * Registry that maps fenced-code-block language tags to NL2AGENT card
 * renderers. The NL2AGENT LLM emits JSON inside these fenced blocks in its
 * final answer; markdownRenderer.tsx routes matching blocks here.
 *
 * Supported tags:
 *   ```nl2agent-local-resources  -> LocalResourcesCard
 *   ```nl2agent-web-mcp          -> WebMcpCard (single)
 *   ```nl2agent-web-mcps         -> list of WebMcpCard
 *   ```nl2agent-web-skill        -> WebSkillCard (single)
 *   ```nl2agent-web-skills       -> list of WebSkillCard
 *   ```nl2agent-finalize         -> FinalizeCard
 */

export interface Nl2AgentCardRendererProps {
  language: string;
  content: string;
  /** Optional handler to open the existing AddMcpServiceModal prefilled. */
  onInstallMcp?: (item: WebMcpCardItem) => void;
}

const parseAgentId = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
};

const renderInvalidAgentId = () => (
  <div className="my-2 p-3 border border-red-200 rounded bg-red-50 text-xs text-red-700">
    Invalid NL2AGENT card JSON: missing draft agent_id.
  </div>
);

/**
 * Try to render an NL2AGENT card from a fenced code block. Returns null if
 * the language tag is not an NL2AGENT tag (so the caller falls back to the
 * default code block renderer).
 */
export const tryRenderNl2AgentCard = (
  language: string,
  content: string,
  onInstallMcp?: (item: WebMcpCardItem) => void
): React.ReactNode | null => {
  if (!language || !language.startsWith("nl2agent-")) {
    return null;
  }

  let parsed: any;
  try {
    parsed = JSON.parse(content);
  } catch {
    return (
      <div className="my-2 p-3 border border-red-200 rounded bg-red-50 text-xs text-red-700">
        Invalid NL2AGENT card JSON: {content.slice(0, 120)}
      </div>
    );
  }

  const agentId = parseAgentId(parsed.agent_id);
  if (agentId == null) {
    return renderInvalidAgentId();
  }

  switch (language) {
    case "nl2agent-local-resources": {
      const tools: LocalResourceItem[] = (parsed.tools || []).map((x: any) => ({
        ...x,
        kind: "tool" as const,
      }));
      const skills: LocalResourceItem[] = (parsed.skills || []).map((x: any) => ({
        ...x,
        kind: "skill" as const,
      }));
      return <LocalResourcesCard agentId={agentId} tools={tools} skills={skills} />;
    }
    case "nl2agent-web-mcp": {
      const item: WebMcpCardItem = parsed;
      return <WebMcpCard agentId={agentId} item={item} onInstall={onInstallMcp} />;
    }
    case "nl2agent-web-mcps": {
      const items: WebMcpCardItem[] = parsed.items || [];
      return (
        <>
          {items.map((item, i) => (
            <WebMcpCard key={i} agentId={agentId} item={item} onInstall={onInstallMcp} />
          ))}
        </>
      );
    }
    case "nl2agent-web-skill": {
      const item: WebSkillCardItem = parsed;
      return <WebSkillCard agentId={agentId} item={item} />;
    }
    case "nl2agent-web-skills": {
      const items: WebSkillCardItem[] = parsed.items || [];
      return (
        <>
          {items.map((item, i) => (
            <WebSkillCard key={i} agentId={agentId} item={item} />
          ))}
        </>
      );
    }
    case "nl2agent-finalize": {
      // Forward the full agent spec to FinalizeCard so it can display
      // all fields and call the finalize endpoint on "Publish".
      const { agent_id, ...rest } = parsed;
      return <FinalizeCard data={{ agent_id, ...rest } as any} />;
    }
    default:
      return null;
  }
};
