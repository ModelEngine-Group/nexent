"use client";

import { useMemo, useState } from "react";
import { Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { FILTER_ALL } from "@/const/mcpTools";
import { filterByDeploymentType, matchesNameOrTag } from "@/lib/mcpTools";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import RepositoryTagFilter from "@/components/tag/RepositoryTagFilter";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import McpToolsSearchFilterBar from "./components/McpToolsSearchFilterBar";
import McpToolsPagination from "./components/McpToolsPagination";
import RepositoryMcpCard from "./components/RepositoryMcpCard";
import { type DeploymentFilter, PlaceholderBox } from "./mcp-space-shared";

export function McpRepository({
  browser,
  localServices,
  isAdmin,
  actions,
  onSelect,
  onInstall,
  onOffline,
}: {
  browser: ReturnType<typeof useMcpCommunityBrowser>;
  localServices: McpServiceItem[];
  isAdmin: boolean;
  actions: React.ReactNode;
  onSelect: (service: CommunityMcpCard) => void;
  onInstall: (service: CommunityMcpCard) => void;
  onOffline: (service: CommunityMcpCard) => void;
}) {
  const { t } = useTranslation("common");
  const [deploymentType] = useState<DeploymentFilter>(FILTER_ALL);

  const filteredServices = useMemo(() => {
    return filterByDeploymentType(browser.services, deploymentType).filter(
      (item) => matchesNameOrTag(item, browser.filters.search)
    );
  }, [browser.services, browser.filters.search, deploymentType]);

  const isInstalled = (service: CommunityMcpCard) => {
    return localServices.some((localService) => {
      if (localService.permission !== "EDIT") return false;
      if (
        service.communityId &&
        localService.communityId === service.communityId
      )
        return true;
      return localService.name === service.name;
    });
  };

  return (
    <div className="space-y-4">
      <McpToolsSearchFilterBar
        search={browser.filters.search}
        actions={actions}
        searchActions={
          <RepositoryTagFilter
            value={
              browser.filters.tag === FILTER_ALL
                ? undefined
                : browser.filters.tag
            }
            tags={browser.tagStats}
            onChange={(value) =>
              browser.updateFilter("tag", value ?? FILTER_ALL)
            }
          />
        }
        onSearchChange={(value) => browser.updateFilter("search", value)}
      />

      <p className="text-sm text-slate-500">
        {t("mcpTools.repository.installHint")}
      </p>

      {browser.loading ? (
        <PlaceholderBox>
          <Spin />
        </PlaceholderBox>
      ) : filteredServices.length === 0 ? (
        <PlaceholderBox>
          <Empty description={t("mcpTools.repository.empty")} />
        </PlaceholderBox>
      ) : (
        <ResourceCardGrid
          items={filteredServices}
          columns={3}
          paginateItems={false}
          showToolbar={false}
          renderItem={(service, index) => (
            <RepositoryMcpCard
              key={`${service.communityId || service.name}-${index}`}
              service={service}
              isAdmin={isAdmin}
              installed={isInstalled(service)}
              onInstall={onInstall}
              onSelect={onSelect}
              onOffline={onOffline}
            />
          )}
        />
      )}

      {filteredServices.length > 0 ? (
        <McpToolsPagination
          mode="offset"
          current={browser.page}
          pageSize={browser.pageSize}
          total={browser.total}
          onChange={browser.setPage}
        />
      ) : null}
    </div>
  );
}
