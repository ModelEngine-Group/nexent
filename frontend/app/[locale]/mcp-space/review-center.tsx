"use client";

import { useState } from "react";
import { App, Button, Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { CheckCircle, Clock, Eye, XCircle } from "lucide-react";
import {
  approveCommunityMcpTool,
  rejectCommunityMcpTool,
} from "@/services/mcpToolsService";
import type { CommunityMcpCard } from "@/types/mcpTools";
import {
  formatRegistryDate,
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import { useMcpCommunityReview } from "@/hooks/mcpTools/useMcpCommunityReview";
import McpToolsPagination from "./components/McpToolsPagination";
import McpRepositoryReviewConfirmModal, {
  type McpRepositoryReviewAction,
} from "./components/McpRepositoryReviewConfirmModal";
import TransportIcon from "./components/shared/TransportIcon";
import { PlaceholderBox } from "./mcp-space-shared";

export function McpReviewCenter({
  browser,
  onSelect,
  onReviewed,
}: {
  browser: ReturnType<typeof useMcpCommunityReview>;
  onSelect: (service: CommunityMcpCard) => void;
  onReviewed: () => Promise<void>;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [confirmAction, setConfirmAction] =
    useState<McpRepositoryReviewAction | null>(null);
  const [confirmService, setConfirmService] = useState<CommunityMcpCard | null>(
    null
  );

  const openReviewConfirm = (
    service: CommunityMcpCard,
    action: McpRepositoryReviewAction
  ) => {
    setConfirmService(service);
    setConfirmAction(action);
  };

  const handleReviewConfirm = async (content?: string) => {
    if (!confirmService?.reviewId || !confirmAction) return;
    setReviewingId(confirmService.reviewId);
    try {
      if (confirmAction === "approve") {
        await approveCommunityMcpTool(confirmService.reviewId, content);
        message.success(
          t("repository.review.approveSuccess", { name: confirmService.name })
        );
      } else {
        await rejectCommunityMcpTool(confirmService.reviewId, content);
        message.success(
          t("repository.review.rejectSuccess", { name: confirmService.name })
        );
      }
      setConfirmAction(null);
      setConfirmService(null);
      await onReviewed();
    } catch {
      message.error(t("repository.review.actionFailed"));
      throw new Error("Review action failed");
    } finally {
      setReviewingId(null);
    }
  };

  return (
    <div className="space-y-4">
      {browser.loading ? (
        <PlaceholderBox>
          <Spin />
        </PlaceholderBox>
      ) : browser.services.length === 0 ? (
        <PlaceholderBox>
          <Empty description={t("repository.review.empty")} />
        </PlaceholderBox>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/80">
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.name")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.deploymentType")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.submitter")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.listingNote")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.status")}
                </th>
                <th className="px-5 py-3.5 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.actions")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {browser.services.map((service) => (
                <ReviewTableRow
                  key={service.reviewId || service.communityId || service.name}
                  service={service}
                  reviewing={reviewingId === service.reviewId}
                  onSelect={() => onSelect(service)}
                  onApprove={() => openReviewConfirm(service, "approve")}
                  onReject={() => openReviewConfirm(service, "reject")}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <McpToolsPagination
        mode="cursor"
        page={browser.page}
        resultCount={browser.services.length}
        hasPrevPage={browser.hasPrevPage}
        hasNextPage={browser.hasNextPage}
        onPrevPage={browser.prevPage}
        onNextPage={browser.nextPage}
      />

      <McpRepositoryReviewConfirmModal
        open={Boolean(confirmAction && confirmService)}
        action={confirmAction}
        service={confirmService}
        loading={
          confirmService?.reviewId != null &&
          reviewingId === confirmService.reviewId
        }
        onClose={() => {
          setConfirmAction(null);
          setConfirmService(null);
        }}
        onConfirm={handleReviewConfirm}
      />
    </div>
  );
}

function ReviewTableRow({
  service,
  reviewing,
  onSelect,
  onApprove,
  onReject,
}: {
  service: CommunityMcpCard;
  reviewing: boolean;
  onSelect: () => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const { t } = useTranslation("common");
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const reviewStatus = service.reviewStatus || "pending";
  const isPending = reviewStatus === "pending";
  const author = service.authorDisplayName || service.authorName || "-";
  const submitDate = formatRegistryDate(service.createdAt || "");
  const listingNote = service.content?.trim() || "—";

  const statusBadge = (() => {
    if (reviewStatus === "approved") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700">
          <CheckCircle className="h-3 w-3" />
          {t("repository.review.status.approved")}
        </span>
      );
    }
    if (reviewStatus === "rejected") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700">
          <XCircle className="h-3 w-3" />
          {t("repository.review.status.rejected")}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700">
        <Clock className="h-3 w-3" />
        {t("repository.review.status.pending")}
      </span>
    );
  })();

  return (
    <tr className="group transition hover:bg-slate-50/60">
      {/* MCP Service */}
      <td className="px-5 py-4">
        <div className="flex items-center gap-3">
          <TransportIcon
            transportType={service.transportType}
            deploymentType={deploymentType}
            label={deploymentLabel}
            seed={service.name}
            className="!h-9 !w-9 rounded-lg"
          />
          <div className="min-w-0">
            <div className="text-sm font-medium text-slate-900">
              {service.name}
            </div>
          </div>
        </div>
      </td>

      {/* Deployment Type */}
      <td className="px-5 py-4">
        <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-600">
          {deploymentLabel}
        </span>
      </td>

      {/* Submitter */}
      <td className="px-5 py-4">
        <div className="text-sm text-slate-600">{author}</div>
        <div className="mt-0.5 text-xs text-slate-400">{submitDate}</div>
      </td>

      {/* Listing note */}
      <td className="px-5 py-4">
        <span
          className="line-clamp-2 max-w-[220px] text-sm text-slate-600"
          title={listingNote === "—" ? undefined : listingNote}
        >
          {listingNote}
        </span>
      </td>

      {/* Status */}
      <td className="px-5 py-4">{statusBadge}</td>

      {/* Actions */}
      <td className="px-5 py-4 text-right">
        {isPending ? (
          <div className="inline-flex items-center gap-2">
            <Button
              size="small"
              className="text-xs"
              icon={<Eye className="h-3.5 w-3.5" />}
              onClick={onSelect}
            >
              {t("repository.review.details")}
            </Button>
            <Button
              className="!border-green-600 !bg-green-600 text-white hover:!border-green-700 hover:!bg-green-700 !text-white"
              size="small"
              icon={<CheckCircle className="h-3.5 w-3.5" />}
              loading={reviewing}
              onClick={onApprove}
            >
              {t("repository.review.approve")}
            </Button>
            <Button
              danger
              size="small"
              className="text-xs"
              icon={<XCircle className="h-3.5 w-3.5" />}
              loading={reviewing}
              onClick={onReject}
            >
              {t("repository.review.reject")}
            </Button>
          </div>
        ) : (
          <Button
            size="small"
            className="text-xs"
            icon={<Eye className="h-3.5 w-3.5" />}
            onClick={onSelect}
          >
            {t("repository.review.details")}
          </Button>
        )}
      </td>
    </tr>
  );
}
