// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Table } from "antd";

import { useEffect, useId, useState } from "react";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
} from "antd";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
import { useResourceReviews } from "@/hooks/resourceReview/useResourceReviews";
import type {
  ResourceRepositoryTarget,
  ResourceType,
} from "@/types/resourceRepository";
import type {
  ResourceReview,
  ResourceReviewQuery,
  ReviewDecision,
  ReviewStatus,
} from "@/types/resourceReview";

const dateText = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "—";

export default function ResourceReviewCenter({
  target,
  detailOnly = false,
}: {
  target: ResourceRepositoryTarget;
  detailOnly?: boolean;
}) {
  const { t } = useTranslation("common");
  const opinionId = useId();
  const { message } = App.useApp();
  const displayName = useUserDisplayName();
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const filterType = params.get("review_type") || target.resourceType || "all";
  const filterStatus = params.get("status") || "all";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const query: ResourceReviewQuery = {
    type: ["agent", "skill", "mcp"].includes(filterType)
      ? (filterType as ResourceType)
      : "all",
    status: ["pending_review", "approved", "rejected"].includes(filterStatus)
      ? (filterStatus as ReviewStatus)
      : "all",
    search: params.get("search") || "",
    page,
    page_size: [10, 20, 50, 100].includes(Number(params.get("page_size")))
      ? Number(params.get("page_size"))
      : 10,
  };
  const { list, detail, decision } = useResourceReviews(
    query,
    target.resourceType,
    target.reviewId,
    detailOnly
  );
  const [opinion, setOpinion] = useState("");
  const [action, setAction] = useState<{
    row: ResourceReview;
    decision: ReviewDecision;
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const [reconciled, setReconciled] = useState(false);
  const updateUrl = (
    changes: Record<string, string | null>,
    replace = false
  ) => {
    const next = new URLSearchParams(params.toString());
    Object.entries(changes).forEach(([key, value]) =>
      value === null ? next.delete(key) : next.set(key, value)
    );
    router[replace ? "replace" : "push"](`${pathname}?${next.toString()}`);
  };
  const filter = (key: string, value: string) =>
    updateUrl({
      [key]: value,
      page: "1",
      review_id: null,
      resource_type: null,
    });
  const total = list.data?.pagination.total ?? 0;
  useEffect(() => {
    if (
      list.isSuccess &&
      !list.isFetching &&
      page > Math.max(1, list.data.pagination.total_pages)
    ) {
      const next = new URLSearchParams(params.toString());
      next.set("page", String(Math.max(1, list.data.pagination.total_pages)));
      router.replace(`${pathname}?${next.toString()}`);
    }
  }, [
    list.isSuccess,
    list.isFetching,
    list.data,
    page,
    params,
    pathname,
    router,
  ]);
  const open = (row: ResourceReview) =>
    updateUrl({
      resource_type: null,
      review_id: row.review_id,
    });
  const begin = (row: ResourceReview, value: ReviewDecision) => {
    open(row);
    setAction({ row, decision: value });
    setOpinion("");
    setFailed(false);
    setReconciled(false);
  };
  const latest = detail.data;
  const stale =
    !!action &&
    !!latest &&
    (latest.review_id !== action.row.review_id ||
      latest.status !== "pending_review");
  const submit = async () => {
    if (!action || stale || (failed && !reconciled)) return;
    try {
      await decision.mutateAsync({
        type: action.row.resource_type,
        id: action.row.review_id,
        decision: action.decision,
        reason: opinion,
      });
      setAction(null);
      message.success(t("resourceCenter.review.success"));
    } catch {
      setFailed(true);
      setReconciled(false);
      const current = await detail.refetch();
      setReconciled(current.isSuccess);
    }
  };
  const typeOptions = ["all", "agent", "mcp", "skill"].map((value) => ({
    value,
    label: t(`resourceCenter.${value === "all" ? "allTypes" : `tab.${value}`}`),
  }));
  const statusOptions = ["all", "pending_review", "approved", "rejected"].map(
    (value) => ({ value, label: t(`resourceCenter.status.${value}`) })
  );
  const actions = (row: ResourceReview, inline = false) => (
    <Space size={inline ? 12 : 16}>
      {row.allowed_actions.map((value) => (
        <Button
          key={value}
          autoInsertSpace={false}
          type={inline ? "link" : "default"}
          className={inline ? "!h-auto !p-0" : undefined}
          onClick={() => begin(row, value)}
        >
          {t(`resourceCenter.review.${value}`)}
        </Button>
      ))}
    </Space>
  );
  return (
    <div
      className="space-y-4 rounded-2xl bg-white"
      data-testid="resource-review-center"
    >
      {!detailOnly && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Input.Search
              key={query.search}
              defaultValue={query.search}
              placeholder={t("resourceCenter.search")}
              allowClear
              onSearch={(value) => filter("search", value.trim())}
              className="w-full sm:!w-[594px]"
            />
            <Select
              aria-label={t("resourceCenter.type")}
              value={query.type}
              options={typeOptions}
              onChange={(value) => filter("review_type", value)}
              className="!w-full sm:!w-[296px]"
            />
            <Select
              aria-label={t("resourceCenter.statusLabel")}
              value={query.status}
              options={statusOptions}
              onChange={(value) => filter("status", value)}
              className="!w-full sm:!w-[296px]"
            />
          </div>
          {list.isError && (
            <Alert
              type="error"
              showIcon
              message={t("resourceCenter.loadFailed")}
              action={
                <Button onClick={() => list.refetch()}>
                  {t("resourceCenter.retry")}
                </Button>
              }
            />
          )}
          <Table<ResourceReview>
            className="resource-review-table resource-scroll-table"
            size="middle"
            scroll={{ x: 1500, y: "100%" }}
            rowKey={(row) => row.review_id}
            loading={list.isFetching}
            dataSource={list.data?.items || []}
            locale={{
              emptyText: <Empty description={t("resourceCenter.empty")} />,
            }}
            columns={[
              {
                title: t("resourceCenter.name"),
                dataIndex: "name",
                width: 300,
                render: (_, row) => (
                  <div className="flex min-w-0 items-center gap-2">
                    <button
                      type="button"
                      className="min-w-0 cursor-pointer truncate text-left text-[#0067d1] hover:underline"
                      title={row.name}
                      onClick={() => open(row)}
                    >
                      {row.name}
                    </button>
                    {row.version_label && (
                      <Tag
                        className="!m-0 max-w-[120px] shrink-0 truncate"
                        title={row.version_label}
                      >
                        {row.version_label}
                      </Tag>
                    )}
                  </div>
                ),
              },
              {
                title: t("resourceCenter.type"),
                dataIndex: "resource_type",
                width: 180,
                render: (value) => t(`resourceCenter.tab.${value}`),
              },
              {
                title: t("resourceCenter.statusLabel"),
                dataIndex: "status",
                width: 180,
                render: (value) => (
                  <span
                    className={`inline-flex rounded px-2 font-['HarmonyOS_Sans_SC',sans-serif] text-xs font-normal leading-5 tracking-normal ${
                      value === "approved"
                        ? "bg-[#BCF2DB]/60 text-[#036142]"
                        : value === "rejected"
                          ? "bg-[#FEE7E8] text-[#C7000B]"
                          : "bg-[#D0D8FD]/50 text-[#1F55B5]"
                    }`}
                  >
                    {t(`resourceCenter.status.${value}`)}
                  </span>
                ),
              },
              {
                title: t("resourceCenter.submitter"),
                width: 180,
                ellipsis: true,
                render: (_, row) =>
                  displayName(
                    row.submitter.cas_username,
                    row.submitter.display_name || "—"
                  ),
              },
              {
                title: t("resourceCenter.submittedAt"),
                dataIndex: "submitted_at",
                width: 180,
                render: dateText,
              },
              {
                title: t("resourceCenter.submission"),
                dataIndex: "submit_description",
                ellipsis: true,
                render: (value) => value || "—",
              },
              {
                title: t("resourceCenter.actions"),
                width: 240,
                fixed: "right",
                render: (_, row) => actions(row, true),
              },
            ]}
            pagination={{
              current: page,
              pageSize: query.page_size,
              total,
              showSizeChanger: true,
              showQuickJumper: total > query.page_size,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (count) =>
                t("resourceCenter.totalPages", {
                  count: Math.ceil(count / query.page_size),
                }),
              onChange: (nextPage, size) =>
                updateUrl({
                  page: String(size !== query.page_size ? 1 : nextPage),
                  page_size: String(size),
                }),
            }}
          />
        </>
      )}
      <Modal
        open={!!target.reviewId && !action}
        title={latest?.name || t("resourceCenter.detail")}
        centered
        width={760}
        onCancel={() => updateUrl({ review_id: null, resource_type: null })}
        footer={latest ? actions(latest) : null}
        destroyOnHidden
      >
        {detail.isLoading ? (
          <Spin />
        ) : detail.isError ? (
          <Alert type="error" message={t("resourceCenter.unavailable")} />
        ) : (
          latest && (
            <div className="max-h-[65vh] space-y-4 overflow-auto">
              <Descriptions
                column={1}
                styles={{
                  label: { whiteSpace: "nowrap" },
                  content: { wordBreak: "break-word" },
                }}
                size="small"
                items={[
                  {
                    key: "type",
                    label: t("resourceCenter.type"),
                    children: t(`resourceCenter.tab.${latest.resource_type}`),
                  },
                  {
                    key: "status",
                    label: t("resourceCenter.statusLabel"),
                    children: t(`resourceCenter.status.${latest.status}`),
                  },
                  {
                    key: "submitter",
                    label: t("resourceCenter.submitter"),
                    children: displayName(
                      latest.submitter.cas_username,
                      latest.submitter.display_name || "—"
                    ),
                  },
                  {
                    key: "submitted",
                    label: t("resourceCenter.submittedAt"),
                    children: dateText(latest.submitted_at),
                  },
                  {
                    key: "published",
                    label: t("resourceCenter.publishedAt"),
                    children: dateText(latest.published_at),
                  },
                  {
                    key: "description",
                    span: 1,
                    label: t("resourceCenter.description"),
                    children: latest.description || "—",
                  },
                  {
                    key: "submission",
                    span: 1,
                    label: t("resourceCenter.submission"),
                    children: latest.submit_description || "—",
                  },
                  {
                    key: "opinion",
                    span: 1,
                    label: t("resourceCenter.opinion"),
                    children: latest.review_comment || "—",
                  },
                ]}
              />
              {latest.resource_detail.readme && (
                <div className="whitespace-pre-wrap rounded border p-4">
                  {latest.resource_detail.readme}
                </div>
              )}
              {latest.resource_detail.files_unavailable && (
                <Alert
                  type="warning"
                  showIcon
                  message={t("resourceCenter.archiveUnavailable")}
                />
              )}
              {(latest.resource_detail.file_count || 0) >
                (latest.resource_detail.file_manifest?.length || 0) && (
                <p className="text-sm text-muted-foreground">
                  {t("resourceCenter.filePreviewLimit", {
                    shown: latest.resource_detail.file_manifest?.length || 0,
                    total: latest.resource_detail.file_count,
                  })}
                </p>
              )}
              {latest.resource_detail.file_manifest?.map((file) => (
                <div key={file.path} className="text-sm">
                  {file.path} · {file.size_bytes} B
                </div>
              ))}
              {latest.resource_detail.agents?.map((agent, index) => (
                <section key={index} className="rounded border p-3">
                  <h3 className="font-medium">{agent.name}</h3>
                  <p>{agent.description}</p>
                  <p className="whitespace-pre-wrap">{agent.prompt}</p>
                  <p>{agent.tools?.join(", ")}</p>
                </section>
              ))}
              {latest.resource_type === "mcp" && (
                <>
                  <p>
                    {latest.resource_detail.transport_type} ·{" "}
                    {latest.resource_detail.server_url}
                  </p>
                  {Object.entries(
                    latest.resource_detail.shared_fields || {}
                  ).map(([name, shared]) => (
                    <div key={name}>
                      {name}:{" "}
                      {t(
                        shared
                          ? "resourceCenter.sharedField"
                          : "resourceCenter.privateField"
                      )}
                    </div>
                  ))}
                  {latest.resource_detail.sensitive_fields?.map((field) => (
                    <div key={field.name}>
                      {field.name}:{" "}
                      {t(
                        field.configured
                          ? "resourceCenter.masked"
                          : "resourceCenter.notConfigured"
                      )}
                    </div>
                  ))}
                </>
              )}
            </div>
          )
        )}
      </Modal>
      <Modal
        open={!!action}
        title={
          <span className="block font-['HarmonyOS_Sans_SC',sans-serif] text-xl font-medium leading-7 tracking-normal text-[#191919]">
            {t(
              `resourceCenter.review.${action?.decision === "reject" ? "confirmReject" : "confirmApprove"}`
            )}
          </span>
        }
        width={768}
        classNames={{
          container:
            "!rounded-lg !bg-white !px-6 !py-5 !shadow-[0_16px_48px_0_rgba(0,0,0,0.16)]",
          body: "!my-4",
        }}
        centered
        onCancel={() => !decision.isPending && setAction(null)}
        footer={
          <div className="flex justify-end gap-2 pb-1 pt-2">
            <Button
              className="!min-w-[88px]"
              disabled={decision.isPending}
              onClick={() => setAction(null)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              className="!min-w-[88px]"
              loading={decision.isPending}
              onClick={submit}
              disabled={
                stale ||
                (failed && !reconciled) ||
                Array.from(opinion.trim()).length > 1000
              }
            >
              {t("common.confirm")}
            </Button>
          </div>
        }
      >
        <p className="mb-2.5 font-['HarmonyOS_Sans_SC',sans-serif] text-sm font-normal leading-[22px] tracking-normal text-[#191919]">
          {t(
            action?.decision === "reject"
              ? "repository.review.confirmRejectContent"
              : "repository.review.confirmApproveContent",
            { name: action?.row.name }
          )}
        </p>
        {failed && (
          <Alert
            className="mb-3"
            type="warning"
            showIcon
            message={t(
              stale
                ? "resourceCenter.review.changed"
                : "resourceCenter.review.failed"
            )}
            action={
              stale && latest?.status === "pending_review" ? (
                <Button
                  onClick={() => {
                    setAction(
                      (current) => current && { ...current, row: latest }
                    );
                    setFailed(false);
                  }}
                >
                  {t("resourceCenter.review.reconfirm")}
                </Button>
              ) : !reconciled ? (
                <Button
                  onClick={async () =>
                    setReconciled((await detail.refetch()).isSuccess)
                  }
                >
                  {t("resourceCenter.retry")}
                </Button>
              ) : undefined
            }
          />
        )}
        <label
          htmlFor={opinionId}
          className="mb-2 block text-sm leading-[22px] text-[#191919]"
        >
          {t("resourceCenter.opinion")}
        </label>
        <div className="relative">
          <Input.TextArea
            id={opinionId}
            value={opinion}
            onChange={(event) => setOpinion(event.target.value)}
            className="!h-[98px] !min-h-[98px] !rounded !border-[#c9c9c9] !bg-white !px-3 !pt-[5px] !pb-6 placeholder:!text-[#AEAEAE]"
            placeholder={t("resourceCenter.review.reason")}
          />
          <span className="pointer-events-none absolute bottom-1 right-2 text-xs leading-[18px] text-[#777777]">
            {Array.from(opinion.trim()).length}/1000
          </span>
        </div>
      </Modal>
    </div>
  );
}
