"use client";

import type { FC } from "react";
import { useState, useEffect, useMemo, useCallback } from "react";
import { ConfigProvider, Dropdown, Tabs } from "antd";
import type { MenuProps } from "antd";
import antdZhCn from "antd/locale/zh_CN";
import antdEnUs from "antd/locale/en_US";
import {
  SparklesIcon,
  SearchIcon,
  MoreHorizontal,
  Star,
  MessageSquarePlus,
} from "lucide-react";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useConversationAgentHistory } from "@/hooks/chat/useConversationAgentHistory";
import { useRouter } from "next/navigation";
import type { PublishedAgent, Agent } from "@/types/agentConfig";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import { useTranslation } from "react-i18next";
import { StandardInput } from "@/components/common/StandardInput";
import { StandardPaginator } from "@/components/common/StandardPaginator";

const LAST_USED_AGENT_KEY = "nexent_last_used_agent_id";
const RECENT_AGENT_IDS_KEY = "nexent_recent_agent_ids";
const FAVORITE_AGENT_IDS_KEY = "nexent_favorite_agent_ids";

type LandingTab = "all" | "recent" | "favorites";

function getLastUsedAgentId(): number | null {
  if (typeof window === "undefined") return null;
  return parseInt(sessionStorage.getItem(LAST_USED_AGENT_KEY) || "0");
}

function setLastUsedAgentId(agentId: number): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(LAST_USED_AGENT_KEY, agentId.toString());
}

function readIdList(storage: Storage | null, key: string): number[] {
  if (!storage) return [];
  try {
    const parsed = JSON.parse(storage.getItem(key) || "[]");
    return Array.isArray(parsed)
      ? parsed.filter((value): value is number => typeof value === "number")
      : [];
  } catch {
    return [];
  }
}

export interface AgentLandingPageProps {
  onSelectAgent: (agent: PublishedAgent) => void;
}

export const AgentLandingPage: FC<AgentLandingPageProps> = ({
  onSelectAgent,
}) => {
  const { t, i18n } = useTranslation();
  const antdLocale = i18n.language?.startsWith("zh") ? antdZhCn : antdEnUs;
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [activeTab, setActiveTab] = useState<LandingTab>("all");
  const [favoriteIds, setFavoriteIds] = useState<number[]>([]);
  const [recentIds, setRecentIds] = useState<number[]>([]);

  const { filteredAgents, isLoading, search, updateSearch } =
    usePublishedAgentList();
  const { data: conversations } = useConversationAgentHistory();

  useEffect(() => {
    setFavoriteIds(readIdList(window.localStorage, FAVORITE_AGENT_IDS_KEY));
    setRecentIds(readIdList(window.sessionStorage, RECENT_AGENT_IDS_KEY));
  }, []);

  const favoriteIdSet = useMemo(() => new Set(favoriteIds), [favoriteIds]);

  const publishedAgents = useMemo(
    () => filteredAgents as unknown as PublishedAgent[],
    [filteredAgents]
  );

  // Agents that have had conversations, ordered most recent first.
  const historyAgentIds = useMemo(() => {
    const seen = new Set<number>();
    const ordered: number[] = [];
    for (const conversation of conversations ?? []) {
      const id = conversation.agent_id;
      if (typeof id === "number" && !seen.has(id)) {
        seen.add(id);
        ordered.push(id);
      }
    }
    return ordered;
  }, [conversations]);

  const usedAgentIds = useMemo(() => {
    // Session-started conversations may not be in the fetched history yet.
    const merged: number[] = [];
    const seen = new Set<number>();
    for (const id of [...recentIds, ...historyAgentIds]) {
      if (!seen.has(id)) {
        seen.add(id);
        merged.push(id);
      }
    }
    return merged;
  }, [recentIds, historyAgentIds]);

  const tabFilteredAgents = useMemo(() => {
    if (activeTab === "favorites") {
      return publishedAgents.filter((agent) =>
        favoriteIdSet.has(agent.agent_id)
      );
    }
    if (activeTab === "recent") {
      // Agents with conversation history, most recent first.
      return usedAgentIds
        .map(
          (id) => publishedAgents.find((agent) => agent.agent_id === id) ?? null
        )
        .filter((agent): agent is PublishedAgent => agent !== null);
    }
    return publishedAgents;
  }, [activeTab, publishedAgents, favoriteIdSet, usedAgentIds]);

  const totalCount = tabFilteredAgents.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  const pageAgents = useMemo(
    () => tabFilteredAgents.slice((page - 1) * pageSize, page * pageSize),
    [tabFilteredAgents, page, pageSize]
  );

  useEffect(() => {
    setPage(1);
  }, [activeTab, search, pageSize]);

  const toggleFavorite = useCallback((agentId: number) => {
    setFavoriteIds((prev) => {
      const next = prev.includes(agentId)
        ? prev.filter((id) => id !== agentId)
        : [agentId, ...prev];
      try {
        window.localStorage.setItem(
          FAVORITE_AGENT_IDS_KEY,
          JSON.stringify(next)
        );
      } catch {
        // storage unavailable (private mode): keep in-memory only
      }
      return next;
    });
  }, []);

  const handleSelectAgent = (agent: PublishedAgent) => {
    const agentKey = agent.agent_id;
    setLastUsedAgentId(agentKey);
    setRecentIds((prev) => {
      const next = [agentKey, ...prev.filter((id) => id !== agentKey)].slice(
        0,
        50
      );
      try {
        window.sessionStorage.setItem(
          RECENT_AGENT_IDS_KEY,
          JSON.stringify(next)
        );
      } catch {
        // storage unavailable: keep in-memory only
      }
      return next;
    });
    onSelectAgent(agent);
  };

  const handleSearchChange = (value: string) => {
    updateSearch(value);
  };

  const handleTabChange = (key: string) => {
    setActiveTab(key as LandingTab);
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">
            {t("chat.chat.loadingAgents")}
          </p>
        </div>
      </div>
    );
  }

  const tabItems = [
    { key: "all", label: t("chat.agentLanding.tabAll") },
    { key: "recent", label: t("chat.agentLanding.tabRecent") },
    { key: "favorites", label: t("chat.agentLanding.tabFavorites") },
  ];

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-6">
      <h1 className="text-[20px] leading-[28px] text-[#191919]">
        {t("chat.agentLanding.discoverTitle")}
      </h1>

      <ConfigProvider theme={{ token: { colorPrimary: "#2673e5" } }}>
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          items={tabItems}
          className="[&_.ant-tabs-nav]:!mb-0 [&_.ant-tabs-tab]:!px-0 [&_.ant-tabs-tab+.ant-tabs-tab]:!ml-6"
        />
      </ConfigProvider>

      <div className="w-[360px] max-w-full">
        <StandardInput
          value={search}
          onChange={(event) => handleSearchChange(event.target.value)}
          placeholder={t("chat.agentLanding.searchPlaceholderName")}
          prefix={
            <SearchIcon className="size-3.5 text-[#808080]" aria-hidden />
          }
        />
      </div>

      {pageAgents.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {pageAgents.map((agent) => (
            <AgentCard
              key={agent.agent_id}
              agent={agent}
              isFavorite={favoriteIdSet.has(agent.agent_id)}
              onSelect={handleSelectAgent}
              onToggleFavorite={toggleFavorite}
            />
          ))}
        </div>
      ) : (
        <EmptyState activeTab={activeTab} />
      )}

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-6 text-[14px] text-[#191919]">
          <span>
            {t("chat.agentLanding.totalCount", { count: totalCount })}
          </span>
          <span>{t("chat.agentLanding.selectedCount", { count: 0 })}</span>
        </div>
        <ConfigProvider locale={antdLocale}>
          <StandardPaginator
            current={page}
            pageSize={pageSize}
            total={totalCount}
            showSizeChanger
            showQuickJumper
            pageSizeOptions={[10, 20, 50]}
            className="[&_.ant-pagination-options]:!contents [&_.ant-pagination-options>.ant-select]:!order-first [&_.ant-pagination-options>.ant-select]:!mx-2 [&_.ant-pagination-options-quick-jumper]:!order-last [&_.ant-pagination-options-quick-jumper]:!ml-2"
            onChange={(nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            }}
          />
        </ConfigProvider>
      </div>
    </div>
  );
};

interface AgentCardProps {
  agent: PublishedAgent;
  isFavorite: boolean;
  onSelect: (agent: PublishedAgent) => void;
  onToggleFavorite: (agentId: number) => void;
}

function AgentCard({
  agent,
  isFavorite,
  onSelect,
  onToggleFavorite,
}: AgentCardProps) {
  const { t } = useTranslation();
  const Icon = getAgentIcon(agent);
  const displayName = agent.display_name || agent.name;
  // TODO(mock): the published-agent API does not return tags yet; fall back to a
  // placeholder tag so cards match the design until the API ships real tags.
  const firstTag = agent.tags?.[0] ?? t("chat.agentLanding.defaultTag");

  const menuItems: MenuProps["items"] = [
    {
      key: "newSession",
      label: t("chat.agentLanding.newSession"),
    },
    {
      key: "favorite",
      label: isFavorite
        ? t("chat.agentLanding.unfavorite")
        : t("chat.agentLanding.favorite"),
    },
  ];

  const handleMenuClick: MenuProps["onClick"] = ({ key, domEvent }) => {
    domEvent.stopPropagation();
    if (key === "newSession") {
      onSelect(agent);
      return;
    }
    if (key === "favorite") {
      onToggleFavorite(agent.agent_id);
    }
  };

  const handleCardKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(agent);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(agent)}
      onKeyDown={handleCardKeyDown}
      className="flex cursor-pointer flex-col rounded-[8px] border border-solid border-[#c9c9c9] bg-[#fff] p-4 text-left transition-colors hover:border-[#2673e5]"
    >
      <div className="flex items-start gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/10">
          <Icon className="size-5 text-primary" aria-hidden />
        </div>
        <p className="min-w-0 flex-1 truncate pt-2 text-[16px] font-bold leading-[24px] text-[#1a1a1a]">
          {displayName}
        </p>
        <span className="shrink-0" onClick={(event) => event.stopPropagation()}>
          <Dropdown
            menu={{ items: menuItems, onClick: handleMenuClick }}
            trigger={["click"]}
          >
            <button
              type="button"
              aria-label={t("chat.agentLanding.cardMenu")}
              className="flex size-6 cursor-pointer items-center justify-center rounded-[4px] text-[#191919] hover:bg-[#f0f0f0]"
            >
              <MoreHorizontal className="size-4" aria-hidden />
            </button>
          </Dropdown>
        </span>
      </div>
      <p className="mt-2 line-clamp-2 text-[14px] leading-[22px] text-[#777777]">
        {agent.description}
      </p>
      {firstTag && (
        <span className="mt-3 inline-flex w-fit rounded-[4px] bg-[#f0f0f0] px-2 py-0.5 text-[12px] leading-[20px] text-[#808080]">
          {firstTag}
        </span>
      )}
    </div>
  );
}

interface EmptyStateProps {
  activeTab: LandingTab;
}

function EmptyState({ activeTab }: EmptyStateProps) {
  const { t } = useTranslation();

  if (activeTab === "favorites") {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Star className="mb-3 size-10 text-muted-foreground/50" aria-hidden />
        <p className="text-sm text-muted-foreground">
          {t("chat.agentLanding.emptyFavorites")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground/70">
          {t("chat.agentLanding.emptyFavoritesHint")}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <SearchIcon
        className="mb-3 size-10 text-muted-foreground/50"
        aria-hidden
      />
      <p className="text-sm text-muted-foreground">
        {t("chat.agentLanding.noMatchingAgents")}
      </p>
      <p className="mt-1 text-xs text-muted-foreground/70">
        {t("chat.agentLanding.tryAnotherSearch")}
      </p>
    </div>
  );
}

export function AgentLandingEmptyState() {
  const { t } = useTranslation();
  const router = useRouter();

  const handleCreateAgent = () => {
    router.push("/agents");
  };

  return (
    <div className="flex h-full items-center justify-center overflow-y-auto px-4 py-8">
      <div className="flex w-full max-w-md flex-col items-center gap-6 text-center">
        <div className="flex size-16 items-center justify-center rounded-full bg-primary/10">
          <SparklesIcon className="size-8 text-primary" aria-hidden />
        </div>
        <div className="space-y-2">
          <h1 className="text-2xl font-bold text-foreground">
            {t("chat.agentLanding.noAgents")}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t("chat.agentLanding.noAgentsDescription")}
          </p>
        </div>
        <button
          type="button"
          onClick={handleCreateAgent}
          className="h-8 w-full cursor-pointer rounded-[4px] bg-[#0067d1] text-[14px] text-white"
        >
          {t("chat.agentLanding.createAgent")}
        </button>
      </div>
    </div>
  );
}
