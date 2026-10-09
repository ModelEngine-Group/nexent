"use client";

import { useState } from "react";
import {
  BotIcon,
  ChevronRightIcon,
  CirclePlusIcon,
  MoreVerticalIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

// Demo-only agent group panel (pure UI per the history-page design). Real
// agent/sub-conversation data will be wired up once the backend exposes it.
interface DemoSubConversation {
  id: string;
  description: string;
  relativeTime: string;
}

interface DemoAgentGroup {
  id: string;
  name: string;
  subConversations: DemoSubConversation[];
}

const DEMO_AGENT_GROUPS: DemoAgentGroup[] = [
  {
    id: "agent-health-report",
    name: "体检报告解读师",
    subConversations: [
      {
        id: "sub-pancreatitis",
        description: "胰腺炎最新指南检索与执行准备",
        relativeTime: "chat.agentGroups.minutesAgo",
      },
      {
        id: "sub-followup",
        description: "对话对话对话对话对话对话对话对话",
        relativeTime: "chat.agentGroups.minutesAgo",
      },
    ],
  },
  {
    id: "agent-cardiomyopathy",
    name: "心肌病筛查助手",
    subConversations: [
      {
        id: "sub-screening",
        description: "心肌病筛查问卷与风险评估",
        relativeTime: "chat.agentGroups.minutesAgo",
      },
    ],
  },
];

export function AgentGroupsPanel() {
  const { t } = useTranslation();
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(
    () => new Set()
  );

  const toggleGroup = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-1 px-2 pb-2">
      <div className="px-1 pt-2 pb-1 text-sm font-medium text-foreground">
        {t("chat.sidebar.agents")}
      </div>
      {DEMO_AGENT_GROUPS.map((group) => {
        const isExpanded = expandedIds.has(group.id);
        return (
          <div key={group.id} className="flex flex-col gap-1">
            <div className="group/agent flex h-10 items-center gap-2 rounded-lg px-2 py-2 hover:bg-[rgba(25,25,25,0.06)]">
              <button
                type="button"
                onClick={() => toggleGroup(group.id)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                aria-expanded={isExpanded}
              >
                <BotIcon
                  className="size-4 shrink-0 text-muted-foreground"
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate text-base leading-6 text-[#191919]">
                  {group.name}
                </span>
                <ChevronRightIcon
                  className={cn(
                    "size-4 shrink-0 text-muted-foreground transition-transform",
                    isExpanded && "rotate-90"
                  )}
                  aria-hidden
                />
              </button>
              <button
                type="button"
                aria-label={t("chat.agentGroups.newConversation")}
                className="size-7 shrink-0 rounded-md opacity-0 group-hover/agent:opacity-100"
              >
                <CirclePlusIcon className="size-4" />
              </button>
              <button
                type="button"
                aria-label={t("chat.agentGroups.more")}
                className="size-7 shrink-0 rounded-md opacity-0 group-hover/agent:opacity-100"
              >
                <MoreVerticalIcon className="size-4" />
              </button>
            </div>
            {isExpanded &&
              group.subConversations.map((sub) => (
                <div
                  key={sub.id}
                  className="flex h-10 items-center gap-2 rounded-lg bg-[rgba(25,25,25,0.03)] px-2 py-2 hover:bg-[rgba(25,25,25,0.06)]"
                >
                  <span className="min-w-0 flex-1 truncate text-sm leading-[22px] text-[rgba(25,25,25,0.7)]">
                    {sub.description}
                  </span>
                  <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground">
                    {t(sub.relativeTime)}
                  </span>
                </div>
              ))}
          </div>
        );
      })}
    </div>
  );
}
