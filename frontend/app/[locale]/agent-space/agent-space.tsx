"use client";

import { App, Button, Empty, Input, Modal, Spin } from "antd";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import type {
  TagDefinition,
  TagResourcePredicate,
} from "@/types/tagManagement";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";
import { AgentRepositoryCard } from "./components/AgentRepositoryCard";

interface AgentSpaceProps {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  tagDefinitions: TagDefinition[];
  tagPredicates: TagResourcePredicate[];
  onTagPredicatesChange: (value: TagResourcePredicate[]) => void;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
  listings: AgentRepositoryListingItem[];
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onCopyClick: (listing: AgentRepositoryListingItem) => void;
  onDetailClick: (listing: AgentRepositoryListingItem) => void;
  showAdminMenu: boolean;
  updatingRepositoryId: number | null;
  onTakeDown: (listing: AgentRepositoryListingItem) => Promise<unknown>;
}

export function AgentSpace({
  searchQuery,
  onSearchChange,
  tagDefinitions,
  tagPredicates,
  onTagPredicatesChange,
  isLoading,
  isError,
  isFetching,
  onRetry,
  listings,
  page,
  pageSize,
  total,
  onPageChange,
  onCopyClick,
  onDetailClick,
  showAdminMenu,
  updatingRepositoryId,
  onTakeDown,
}: AgentSpaceProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 0;
  const showPagination = !isLoading && !isError && totalPages > 1;

  const confirmTakeDown = (listing: AgentRepositoryListingItem) => {
    const title =
      listing.display_name?.trim() ||
      listing.name?.trim() ||
      t("agentRepository.card.untitled");

    Modal.confirm({
      title: t("repository.listingStatus.confirmTakeDownTitle"),
      content: t("repository.listingStatus.confirmTakeDownContent", {
        name: title,
      }),
      okText: t("repository.listingStatus.takeDown"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await onTakeDown(listing);
          message.success(t("repository.mine.takeDownSuccess"));
        } catch {
          message.error(t("repository.mine.takeDownError"));
          throw new Error("Take down failed");
        }
      },
    });
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="relative min-w-0 flex-1">
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t("agentRepository.page.searchPlaceholder")}
            prefix={<Search className="size-4 text-slate-400" aria-hidden />}
            className="h-11 rounded-xl"
            allowClear
          />
        </div>
        <TagFilterPopover
          definitions={tagDefinitions}
          value={tagPredicates}
          onChange={onTagPredicatesChange}
        />
      </div>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t("agentRepository.page.repositoryHint")}
      </p>
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("agentRepository.page.loadError")}
          </p>
          <Button type="primary" onClick={onRetry} loading={isFetching}>
            {t("repository.common.retry")}
          </Button>
        </div>
      ) : listings.length === 0 ? (
        <Empty
          className="py-16"
          description={t("agentRepository.page.empty")}
        />
      ) : (
        <>
          <ResourceCardGrid
            items={listings}
            columns={4}
            paginateItems={false}
            showToolbar={false}
            renderItem={(listing) => (
              <AgentRepositoryCard
                key={listing.agent_repository_id}
                listing={listing}
                showAdminMenu={showAdminMenu}
                isTakingDown={
                  updatingRepositoryId === listing.agent_repository_id
                }
                onCopyClick={onCopyClick}
                onDetailClick={onDetailClick}
                onTakeDown={() => confirmTakeDown(listing)}
              />
            )}
          />
          {showPagination ? (
            <PaginationControls
              page={page}
              totalPages={totalPages}
              onPageChange={onPageChange}
            />
          ) : null}
        </>
      )}
    </div>
  );
}

function PaginationControls({
  page,
  totalPages,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="flex items-center justify-center gap-1.5 pt-2">
      <Button
        type="default"
        className="flex size-9 items-center justify-center rounded-lg p-0"
        disabled={page <= 1}
        onClick={() => onPageChange(Math.max(1, page - 1))}
        aria-label={t("repository.pagination.prev")}
      >
        <ChevronLeft className="size-4" aria-hidden />
      </Button>
      {Array.from({ length: totalPages }, (_, index) => index + 1).map(
        (pageNumber) => (
          <Button
            key={pageNumber}
            type={pageNumber === page ? "primary" : "default"}
            className="flex size-9 items-center justify-center rounded-lg p-0"
            onClick={() => onPageChange(pageNumber)}
            aria-label={t("repository.pagination.page", { page: pageNumber })}
            aria-current={pageNumber === page ? "page" : undefined}
          >
            {pageNumber}
          </Button>
        )
      )}
      <Button
        type="default"
        className="flex size-9 items-center justify-center rounded-lg p-0"
        disabled={page >= totalPages}
        onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        aria-label={t("repository.pagination.next")}
      >
        <ChevronRight className="size-4" aria-hidden />
      </Button>
    </div>
  );
}
