"use client";

import type { FC } from "react";
import { useState, useEffect, useMemo } from "react";
import { SparklesIcon, CodeIcon, SearchIcon, FileTextIcon, History, ChevronLeft, ChevronRight, LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useRouter } from "next/navigation";
import type { PublishedAgent, Agent } from "@/types/agentConfig";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";

const LAST_USED_AGENT_KEY = "nexent_last_used_agent_id";

function getLastUsedAgentId(): number | null {
  if (typeof window === "undefined") return null;
  return parseInt(sessionStorage.getItem(LAST_USED_AGENT_KEY) || "0");
}

function setLastUsedAgentId(agentId: number): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(LAST_USED_AGENT_KEY, agentId.toString());
}

export interface AgentLandingPageProps {
  onSelectAgent: (agent: PublishedAgent) => void;
}

export const AgentLandingPage: FC<AgentLandingPageProps> = ({ onSelectAgent }) => {
  const PAGE_SIZE = 6;
  const [page, setPage] = useState(1);
  const [lastUsedAgentId, setLastUsedAgentIdState] = useState<number | null>(null);

  const {
    agents,
    paginatedAgents,
    filteredAgents,
    excludedAgent,
    totalPages,
    isLoading,
    search,
    updateSearch,
  } = usePublishedAgentList({
    page,
    pageSize: PAGE_SIZE,
    excludeAgentId: lastUsedAgentId,
  });

  useEffect(() => {
    setLastUsedAgentIdState(getLastUsedAgentId());
  }, []);

  const handleSelectAgent = (agent: PublishedAgent) => {
    const agentKey = agent.agent_id;
    setLastUsedAgentId(agentKey);
    setLastUsedAgentIdState(agentKey);
    onSelectAgent(agent);
  };

  const handleSearchChange = (value: string) => {
    updateSearch(value);
    setPage(1);
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading agents...</p>
        </div>
      </div>
    );
  }

  const hasAgents = filteredAgents.length > 0;

  return (
    <div className="flex h-full flex-col overflow-y-auto px-8 py-8">
      <div className="flex flex-1 items-center justify-center">

      
        <div className="flex w-full max-w-3xl flex-col items-center gap-6">
          <div className="text-center">
            <h1 className="text-balance text-2xl font-bold text-foreground md:text-3xl">
              选择一个智能体开始对话
            </h1>
            <p className="mt-2 text-pretty text-sm text-muted-foreground">
              每个智能体擅长不同的任务，选择合适的智能体可以获得更好的回答。
            </p>
          </div>

          <div className="w-full sm:max-w-md">
            <div className="relative">
              <SearchIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="搜索智能体..."
                className="pl-9"
              />
            </div>
          </div>

          {excludedAgent && (
            <LastUsedAgentCard agent={excludedAgent as unknown as PublishedAgent} onSelect={handleSelectAgent} />
          )}

          
          <div className="w-full">
            <div className="mb-2 w-full text-xs font-medium text-muted-foreground">
              全部智能体
            </div>
            {hasAgents ? (
              <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
                {paginatedAgents.map((agent: Agent) => {
                  const publishedAgent = agent as unknown as PublishedAgent;
                  return (
                    <AgentCard
                      key={getAgentKey(publishedAgent)}
                      agent={publishedAgent}
                      onSelect={handleSelectAgent}
                    />
                  );
                })}
              </div>
            ) : (
              <EmptyState />
            )}
          </div>
          

          {totalPages > 1 && (
            <Pagination
              currentPage={page}
              totalPages={totalPages}
              onPageChange={setPage}
              onPrev={() => setPage((prev) => Math.max(1, prev - 1))}
              onNext={() => setPage((prev) => prev + 1)}
            />
          )}

          <p className="text-xs text-muted-foreground">
            共 {filteredAgents.length} 个智能体
            {totalPages > 1 && `，第 ${page}/${totalPages} 页`}
          </p>
        </div>
      </div>
    </div>
  );
};

function getAgentKey(agent: PublishedAgent): number {
  return agent.agent_id;
}

interface AgentCardProps {
  agent: PublishedAgent;
  onSelect: (agent: PublishedAgent) => void;
}

function AgentCard({ agent, onSelect }: AgentCardProps) {
  const Icon = getAgentIcon(agent);
  const displayName = agent.display_name || agent.name;

  return (
    <button
      type="button"
      onClick={() => onSelect(agent)}
      className="flex items-start gap-3 rounded-2xl border border-border bg-card p-4 text-left transition-colors hover:border-primary/40 hover:bg-accent/50"
    >
      <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary/10">
        <Icon className="size-5 text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold text-foreground">{displayName}</p>
        <p className="text-xs text-primary line-clamp-1 text-muted-foreground">{agent.name}</p>
        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
          {agent.greeting_message || agent.description}
        </p>
      </div>
    </button>
  );
}

interface LastUsedAgentCardProps {
  agent: PublishedAgent;
  onSelect: (agent: PublishedAgent) => void;
}

function LastUsedAgentCard({ agent, onSelect }: LastUsedAgentCardProps) {
  const Icon = getAgentIcon(agent);
  const displayName = agent.display_name || agent.name;

  return (
    <div className="w-full">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <History className="size-3.5" />
        上次使用的智能体
      </div>
      <button
        type="button"
        onClick={() => onSelect(agent)}
        className="flex w-full items-start gap-3 rounded-2xl border-2 border-primary/30 bg-primary/5 p-4 text-left transition-colors hover:border-primary/50 hover:bg-primary/10"
      >
        <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary/10 ring-2 ring-primary/20">
          <Icon className="size-5 text-primary" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate font-semibold text-foreground">{displayName}</p>
            <span className="shrink-0 rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary">
              继续对话
            </span>
          </div>
          <p className="text-xs text-primary">{agent.name}</p>
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {agent.greeting_message || agent.description}
          </p>
        </div>
      </button>
    </div>
  );
}

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  onPrev: () => void;
  onNext: () => void;
}

function Pagination({ currentPage, totalPages, onPageChange, onPrev, onNext }: PaginationProps) {
  const pages = useMemo(() => {
    const items: (number | "...")[] = [];
    for (let i = 1; i <= totalPages; i++) {
      if (
        i === 1 ||
        i === totalPages ||
        (i >= currentPage - 1 && i <= currentPage + 1)
      ) {
        items.push(i);
      } else if (i === currentPage - 2 || i === currentPage + 2) {
        items.push("...");
      }
    }
    return items;
  }, [currentPage, totalPages]);

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="icon"
        className="size-8"
        onClick={onPrev}
        disabled={currentPage === 1}
      >
        <ChevronLeft className="size-4" />
      </Button>
      <div className="flex items-center gap-1">
        {pages.map((page, index) =>
          page === "..." ? (
            <span key={`ellipsis-${index}`} className="px-1 text-muted-foreground">
              ...
            </span>
          ) : (
            <Button
              key={page}
              variant={currentPage === page ? "default" : "outline"}
              size="icon"
              className="size-8 text-xs"
              onClick={() => onPageChange(page)}
            >
              {page}
            </Button>
          )
        )}
      </div>
      <Button
        variant="outline"
        size="icon"
        className="size-8"
        onClick={onNext}
        disabled={currentPage === totalPages}
      >
        <ChevronRight className="size-4" />
      </Button>
    </div>
  );
}

export function AgentLandingEmptyState() {
  const router = useRouter();

  const handleCreateAgent = () => {
    router.push("/agents");
  };

  return (
    <div className="flex h-full items-center justify-center overflow-y-auto px-4 py-8">
      <div className="flex w-full max-w-md flex-col items-center gap-6 text-center">
        <div className="flex size-16 items-center justify-center rounded-full bg-primary/10">
          <SparklesIcon className="size-8 text-primary" />
        </div>
        <div className="space-y-2">
          <h1 className="text-2xl font-bold text-foreground">
            还没有智能体
          </h1>
          <p className="text-sm text-muted-foreground">
            创建一个智能体，开始你的 AI 对话之旅。
          </p>
        </div>
        <Button onClick={handleCreateAgent} className="w-full">
          创建智能体
        </Button>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <SearchIcon className="mb-3 size-10 text-muted-foreground/50" />
      <p className="text-sm text-muted-foreground">未找到匹配的智能体</p>
      <p className="mt-1 text-xs text-muted-foreground/70">尝试使用其他关键词搜索</p>
    </div>
  );
}

