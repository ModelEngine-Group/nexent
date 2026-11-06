// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { CSSProperties } from "react";
import { theme } from "antd";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { getEffectiveRoutePath } from "@/lib/auth";
import "./route-loading-skeleton.css";

interface RouteLoadingSkeletonProps {
  pathname?: string;
}

function Bone({ className = "" }: { className?: string }) {
  return <div className={`route-skeleton-bone ${className}`} />;
}

function Rows() {
  return (
    <div>
      {Array.from({ length: 5 }, (_, row) => (
        <div className="route-skeleton-row" key={row}>
          {Array.from({ length: 4 }, (_, column) => (
            <Bone key={column} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function RouteLoadingSkeleton({ pathname }: RouteLoadingSkeletonProps) {
  const currentPath = usePathname();
  const { t } = useTranslation("common");
  const { token } = theme.useToken();
  const path = getEffectiveRoutePath(pathname ?? currentPath).split("/")[1];
  const routes: Record<string, { title: string; layout: string }> = {
    "": { title: "sidebar.homePage", layout: "cards" },
    workbench: { title: "sidebar.agentWorkbench", layout: "conversation" },
    newchat: { title: "sidebar.startChat", layout: "conversation" },
    chat: { title: "sidebar.startChat", layout: "conversation" },
    models: { title: "sidebar.modelConfig", layout: "configuration" },
    knowledges: { title: "sidebar.knowledgeBaseConfig", layout: "cards" },
    "aidp-knowledges": {
      title: "sidebar.knowledgeBaseConfig",
      layout: "split",
    },
    agents: { title: "sidebar.agentConfig", layout: "cards" },
    memory: { title: "sidebar.memoryConfig", layout: "configuration" },
    evaluation: { title: "sidebar.agentEvaluation", layout: "table" },
    "agent-tasks": { title: "sidebar.agentTasks", layout: "table" },
    "agent-space": { title: "sidebar.agentSpace", layout: "cards" },
    "agent-repository": { title: "sidebar.agentSpace", layout: "cards" },
    "mcp-space": { title: "sidebar.mcpSpace", layout: "cards" },
    "skill-space": { title: "sidebar.skillSpace", layout: "cards" },
    "resource-manage": { title: "sidebar.resourceManage", layout: "table" },
    "owner-manage": { title: "sidebar.ownerManage", layout: "table" },
  };
  const route = routes[path];
  const layout = route?.layout ?? "table";
  const isSplit = layout === "split" || layout === "conversation";

  return (
    <section
      className="route-loading-skeleton"
      role="status"
      aria-label={t("common.loading")}
      aria-busy="true"
      data-layout={layout}
      style={
        {
          "--route-skeleton-base": token.colorFillSecondary,
          "--route-skeleton-highlight": token.colorFill,
          "--route-skeleton-border": token.colorBorderSecondary,
          background: token.colorBgContainer,
          color: token.colorText,
        } as CSSProperties
      }
    >
      {route ? (
        <h1 className="mb-6">
          <span className="sr-only">{t(route.title)}</span>
          <Bone className="route-skeleton-title" />
        </h1>
      ) : (
        <div className="mb-6">
          <Bone className="route-skeleton-title" />
        </div>
      )}
      <div aria-hidden="true" className={isSplit ? "route-skeleton-split" : ""}>
        {isSplit && (
          <div className="route-skeleton-sidebar">
            <Bone className="route-skeleton-field" />
            {Array.from({ length: 6 }, (_, index) => (
              <Bone key={index} />
            ))}
          </div>
        )}
        <div className="min-w-0">
          {layout === "conversation" ? (
            <div className="route-skeleton-conversation">
              <Bone className="route-skeleton-user-message" />
              <div className="grid gap-4">
                <Bone className="w-1/3" />
                <Bone />
                <Bone className="w-4/5" />
                <Bone className="w-3/5" />
              </div>
              <Bone className="route-skeleton-composer" />
            </div>
          ) : (
            <>
              <div className="mb-6 flex gap-5">
                <Bone className="w-20" />
                <Bone className="w-20" />
                <Bone className="w-20" />
              </div>
              {layout === "configuration" && (
                <div className="mb-8 grid grid-cols-1 gap-6 sm:grid-cols-2">
                  {Array.from({ length: 4 }, (_, index) => (
                    <div className="grid gap-3" key={index}>
                      <Bone className="w-1/3" />
                      <Bone className="route-skeleton-field" />
                    </div>
                  ))}
                </div>
              )}
              <div className="mb-6 flex gap-4">
                <Bone className="route-skeleton-field w-3/5" />
                <Bone className="route-skeleton-field w-1/5" />
              </div>
              {layout === "cards" ? (
                <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
                  {Array.from({ length: 6 }, (_, index) => (
                    <div className="route-skeleton-card" key={index}>
                      <Bone className="route-skeleton-avatar" />
                      <Bone className="w-2/3" />
                      <Bone />
                      <Bone className="w-4/5" />
                    </div>
                  ))}
                </div>
              ) : (
                <Rows />
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
