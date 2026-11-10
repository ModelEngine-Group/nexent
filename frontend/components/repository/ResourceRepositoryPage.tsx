// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import { ConfigProvider, Result, Segmented, Spin, Tabs } from "antd";
import antdEnUs from "antd/locale/en_US";
import antdZhCn from "antd/locale/zh_CN";
import { Bot, Puzzle, ShieldCheck, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import {
  RESOURCE_REPOSITORY_PERMISSION_ROUTE,
  RESOURCE_REPOSITORY_TABS,
} from "@/const/resourceRepository";
import {
  buildResourceRepositoryHref,
  parseResourceRepositoryTarget,
} from "@/lib/resourceRepositoryRoutes";
import type {
  ResourceRepositoryTarget,
  ResourceRepositoryView,
} from "@/types/resourceRepository";
import { AgentSpace } from "./agent/agent-space";
import { SkillSpace } from "./skill/skill-space";
import { MySkill } from "./skill/my-skill";
import { McpSpace, useMcpSpaceController } from "./mcp/agent-space";
import { MyMcp } from "./mcp/my-mcp";
import ResourceReviewCenter from "./ResourceReviewCenter";
import "./resource-space.css";

function McpContent({
  view,
  sortByPublished,
}: {
  view: ResourceRepositoryView;
  sortByPublished: boolean;
}) {
  const controller = useMcpSpaceController(sortByPublished);
  return (
    <>
      {view === "mine" ? (
        <MyMcp {...controller.mineProps} />
      ) : (
        <McpSpace {...controller.repositoryProps} />
      )}
      {controller.dialogs}
    </>
  );
}

export default function ResourceRepositoryPage() {
  const { t, i18n } = useTranslation("common");
  const { locale } = useParams<{ locale: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const pendingChanges = useRef<Record<string, string | null> | null>(null);
  const updateQuery = useCallback(
    (changes: Record<string, string | null>, replace = false) => {
      const scheduled = pendingChanges.current !== null;
      pendingChanges.current = { ...pendingChanges.current, ...changes };
      if (scheduled) return;
      queueMicrotask(() => {
        const current = new URL(window.location.href);
        const next = current.searchParams;
        const previous = next.toString();
        Object.entries(pendingChanges.current || {}).forEach(([key, value]) =>
          value === null ? next.delete(key) : next.set(key, value)
        );
        pendingChanges.current = null;
        const query = next.toString();
        if (query === previous) return;
        window.history[replace ? "replaceState" : "pushState"](
          null,
          "",
          `${pathname}${query ? `?${query}` : ""}${current.hash}`
        );
      });
    },
    [pathname]
  );
  const presentation = useMemo(
    () => ({
      layout:
        params.get("layout") === "list"
          ? ("list" as const)
          : ("cards" as const),
      resourceType: params.get("tab") || "agent",
      query: params,
      updateQuery,
    }),
    [params, updateQuery]
  );

  const { user, isAuthzReady, canAccessRoute } = useAuthorizationContext();
  const queryClient = useQueryClient();
  const identity = `${user?.id}:${user?.tenantId}:${user?.role}`;
  const [preparedIdentity, setPreparedIdentity] = useState<string | null>(null);
  useEffect(() => {
    queryClient.removeQueries({
      predicate: ({ queryKey }) =>
        /repository|myEditable|mcp|skills|resourceReview/i.test(
          String(queryKey[0])
        ),
    });
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Mount children only after identity caches have been cleared.
    setPreparedIdentity(identity);
  }, [identity, queryClient]);
  if (!isAuthzReady || preparedIdentity !== identity)
    return (
      <div className="flex h-full items-center justify-center">
        <Spin />
      </div>
    );
  if (!canAccessRoute(RESOURCE_REPOSITORY_PERMISSION_ROUTE))
    return <Result status="403" title={t("resourceCenter.accessDenied")} />;
  const parsed = parseResourceRepositoryTarget(params);
  if (!parsed.valid)
    return <Result status="404" title={t("resourceCenter.invalidTarget")} />;
  const target = parsed.target;
  const view =
    target.tab === "agent" ? "repository" : (target.view ?? "repository");
  const navigate = (next: ResourceRepositoryTarget) =>
    router.push(buildResourceRepositoryHref(locale || "en", next));
  const icons = {
    agent: <Bot size={16} />,
    mcp: <Puzzle size={16} />,
    skill: <Sparkles size={16} />,
    review: <ShieldCheck size={16} />,
  };
  return (
    <ConfigProvider
      locale={i18n.language?.startsWith("zh") ? antdZhCn : antdEnUs}
      theme={{
        token: {
          colorPrimary: "#0067d1",
          colorText: "#191919",
          borderRadius: 4,
          controlHeight: 32,
          fontSize: 14,
        },
      }}
    >
      <main
        className="resource-space flex h-full min-h-0 flex-col bg-background p-6"
        data-testid="resource-repository"
        data-resource-type={target.tab}
      >
        <h1 className="mb-4 flex items-center gap-2 text-xl font-medium leading-7 tracking-normal text-[#191919]">
          {t("resourceCenter.title")}
        </h1>
        <Tabs
          activeKey={target.tab}
          onChange={(tab) =>
            navigate({
              tab: tab as ResourceRepositoryTarget["tab"],
              view: "repository",
            })
          }
          items={RESOURCE_REPOSITORY_TABS.map((tab) => ({
            key: tab,
            label: (
              <span className="flex items-center gap-1.5">
                {icons[tab]}
                {t(`resourceCenter.tab.${tab}`)}
              </span>
            ),
          }))}
          tabBarExtraContent={
            target.tab === "mcp" || target.tab === "skill" ? (
              <Segmented
                value={view}
                onChange={(value) =>
                  navigate({
                    tab: target.tab,
                    view: value as ResourceRepositoryView,
                  })
                }
                options={[
                  { value: "repository", label: t("resourceCenter.all") },
                  { value: "mine", label: t("resourceCenter.mine") },
                ]}
              />
            ) : undefined
          }
        />
        <RepositoryPresentationContext.Provider value={presentation}>
          <div
            className="resource-repository-content min-h-0 flex-1 overflow-auto"
            key={`${identity}:${target.tab}:${view}`}
          >
            {target.tab === "agent" && (
              <AgentSpace
                active
                enhanced
                sortByPublished={params.get("sort") === "latest"}
              />
            )}
            {target.tab === "skill" &&
              (view === "mine" ? (
                <MySkill active />
              ) : (
                <SkillSpace
                  active
                  enhanced
                  sortByPublished={params.get("sort") === "latest"}
                />
              ))}
            {target.tab === "mcp" && (
              <McpContent
                view={view}
                sortByPublished={params.get("sort") === "latest"}
              />
            )}
            {target.tab === "review" && (
              <ResourceReviewCenter target={target} />
            )}
          </div>
        </RepositoryPresentationContext.Provider>
        {target.tab !== "review" && target.repositoryId && (
          <ResourceReviewCenter
            detailOnly
            target={{ ...target, resourceType: target.tab }}
          />
        )}
      </main>
    </ConfigProvider>
  );
}
