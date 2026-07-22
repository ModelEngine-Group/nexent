"use client";

import { Button } from "antd";
import { Bot, Check, Eye, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";

const GRID_COLS =
  "grid-cols-[minmax(0,2fr)_120px_160px_minmax(0,1.5fr)_280px]";

interface ReviewAgentListProps {
  listings: AgentRepositoryListingItem[];
  currentUserEmail?: string | null;
  updatingRepositoryId: number | null;
  onDetailClick: (listing: AgentRepositoryListingItem) => void;
  onApprove: (listing: AgentRepositoryListingItem) => void;
  onReject: (listing: AgentRepositoryListingItem) => void;
}

function getListingTitle(
  listing: AgentRepositoryListingItem,
  t: TFunction
) {
  return (
    listing.display_name?.trim() ||
    listing.name?.trim() ||
    t("agentRepository.card.untitled")
  );
}

function getSubmitterDisplay(
  submittedBy: string | null | undefined,
  currentUserEmail: string | null | undefined,
  t: TFunction
) {
  const trimmed = submittedBy?.trim();
  if (!trimmed) {
    return t("agentRepository.review.unknownSubmitter");
  }
  if (
    currentUserEmail &&
    trimmed.toLowerCase() === currentUserEmail.toLowerCase()
  ) {
    return t("agentRepository.review.me");
  }
  return trimmed;
}

export function ReviewAgentList({
  listings,
  currentUserEmail,
  updatingRepositoryId,
  onDetailClick,
  onApprove,
  onReject,
}: ReviewAgentListProps) {
  const { t } = useTranslation("common");

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="inline-block min-w-full">
        <div
          className={`hidden min-w-[860px] ${GRID_COLS} gap-4 border-b border-slate-200 bg-slate-50 px-5 py-4 text-xs font-medium text-slate-500 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-400 lg:grid lg:items-center`}
        >
          <span>{t("agentRepository.review.column.agent")}</span>
          <span>{t("agentRepository.review.column.version")}</span>
          <span>{t("agentRepository.review.column.submitter")}</span>
          <span>{t("agentRepository.review.column.listingNote")}</span>
          <span>{t("agentRepository.review.column.actions")}</span>
        </div>

        <ul className="divide-y divide-slate-200 dark:divide-slate-700">
          {listings.map((listing) => {
            const title = getListingTitle(listing, t);
            const isUpdating =
              updatingRepositoryId === listing.agent_repository_id;
            const versionLabel =
              listing.version_label?.trim() ||
              t("agentRepository.review.noVersion");
            const submitter = getSubmitterDisplay(
              listing.submitted_by,
              currentUserEmail,
              t
            );
            const listingNote = listing.content?.trim() || "—";

            return (
              <li
                key={listing.agent_repository_id}
                className={`min-w-[860px] ${GRID_COLS} gap-4 px-5 py-4 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40 lg:grid lg:items-center`}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-lg text-primary">
                    {listing.icon?.trim() ? (
                      <span aria-hidden>{listing.icon.trim()}</span>
                    ) : (
                      <Bot className="size-5" aria-hidden />
                    )}
                  </div>
                  <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {title}
                  </h3>
                </div>

                <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
                  {versionLabel}
                </div>

                <div className="text-sm text-slate-500 dark:text-slate-400">
                  {submitter}
                </div>

                <div
                  className="line-clamp-2 text-sm text-slate-600 dark:text-slate-300"
                  title={listingNote === "—" ? undefined : listingNote}
                >
                  {listingNote}
                </div>

                <div className="flex flex-wrap items-center justify-start gap-2">
                  <Button
                    type="default"
                    size="small"
                    icon={<Eye className="size-4" aria-hidden />}
                    onClick={() => onDetailClick(listing)}
                    disabled={isUpdating}
                  >
                    {t("agentRepository.review.viewDetail")}
                  </Button>
                  <Button
                    type="primary"
                    size="small"
                    icon={<Check className="size-4" aria-hidden />}
                    onClick={() => onApprove(listing)}
                    loading={isUpdating}
                    disabled={isUpdating}
                  >
                    {t("agentRepository.review.approve")}
                  </Button>
                  <Button
                    danger
                    size="small"
                    icon={<X className="size-4" aria-hidden />}
                    onClick={() => onReject(listing)}
                    loading={isUpdating}
                    disabled={isUpdating}
                  >
                    {t("agentRepository.review.reject")}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
