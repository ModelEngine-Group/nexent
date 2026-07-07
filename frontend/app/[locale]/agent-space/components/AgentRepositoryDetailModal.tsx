"use client";

import { Button, Modal, Spin, Tag } from "antd";
import {
  Bot,
  Calendar,
  CheckCircle2,
  Clock,
  Cpu,
  Download,
  Wrench,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AgentDetailModalData } from "@/lib/agentRepositoryDetail";
import type { AgentRepositoryListingStatus } from "@/types/agentRepository";

interface AgentRepositoryDetailModalProps {
  open: boolean;
  onClose: () => void;
  detail: AgentDetailModalData | null | undefined;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
}

function formatCreatedAt(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString();
}

function resolveDetailTitle(
  detail: AgentDetailModalData,
  untitledLabel: string
): string {
  return detail.display_name?.trim() || detail.name?.trim() || untitledLabel;
}

function StatusBadge({ status }: { status: AgentRepositoryListingStatus }) {
  const { t } = useTranslation("common");

  const config: Record<
    AgentRepositoryListingStatus,
    { className: string; Icon: typeof CheckCircle2 }
  > = {
    shared: {
      className:
        "border-primary/30 bg-primary/10 text-primary dark:border-primary/40 dark:bg-primary/20",
      Icon: CheckCircle2,
    },
    pending_review: {
      className:
        "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300",
      Icon: Clock,
    },
    rejected: {
      className:
        "border-red-300 bg-red-50 text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300",
      Icon: XCircle,
    },
    not_shared: {
      className:
        "border-slate-300 bg-slate-50 text-slate-600 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300",
      Icon: Clock,
    },
  };

  const { className, Icon } = config[status];

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${className}`}
    >
      <Icon className="size-3" aria-hidden />
      {t(`agentRepository.detail.status.${status}`)}
    </span>
  );
}

function AgentRepositoryDetailLoading() {
  return (
    <div className="flex items-center justify-center py-20">
      <Spin size="large" />
    </div>
  );
}

function AgentRepositoryDetailError({
  onRetry,
  isFetching,
}: {
  onRetry: () => void;
  isFetching: boolean;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-20 text-center">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t("agentRepository.detail.loadError")}
      </p>
      <Button type="primary" onClick={onRetry} loading={isFetching}>
        {t("agentRepository.detail.retry")}
      </Button>
    </div>
  );
}

function AgentRepositoryDetailIcon({ icon }: { icon?: string | null }) {
  const trimmedIcon = icon?.trim();
  if (trimmedIcon) {
    return <span aria-hidden>{trimmedIcon}</span>;
  }
  return <Bot className="size-8 text-primary" aria-hidden />;
}

function AgentRepositoryDetailMeta({
  detail,
  downloads,
  createdAtText,
}: {
  detail: AgentDetailModalData;
  downloads: number;
  createdAtText: string | null;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
      {detail.model_name ? (
        <span className="inline-flex items-center gap-1">
          <Cpu className="size-3.5" aria-hidden />
          {detail.model_name}
        </span>
      ) : null}
      {detail.version_label ? <span>{detail.version_label}</span> : null}
      <span className="inline-flex items-center gap-1">
        <Download className="size-3.5" aria-hidden />
        {t("agentRepository.detail.downloads", {
          count: downloads.toLocaleString(),
        })}
      </span>
      {createdAtText ? (
        <span className="inline-flex items-center gap-1">
          <Calendar className="size-3.5" aria-hidden />
          {createdAtText}
        </span>
      ) : null}
    </div>
  );
}

function AgentRepositoryDetailHeader({ detail }: { detail: AgentDetailModalData }) {
  const { t } = useTranslation("common");
  const title = resolveDetailTitle(detail, t("agentRepository.card.untitled"));
  const downloads = detail.downloads ?? 0;
  const createdAtText = formatCreatedAt(detail.created_at);

  return (
    <div className="border-b border-slate-200 bg-slate-50 p-6 dark:border-slate-700 dark:bg-slate-900/40">
      <div className="flex items-start gap-4">
        <div className="flex size-16 shrink-0 items-center justify-center rounded-2xl bg-white text-3xl shadow-sm dark:bg-slate-800">
          <AgentRepositoryDetailIcon icon={detail.icon} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
              {title}
            </h2>
            {detail.status ? <StatusBadge status={detail.status} /> : null}
          </div>
          <AgentRepositoryDetailMeta
            detail={detail}
            downloads={downloads}
            createdAtText={createdAtText}
          />
        </div>
      </div>
    </div>
  );
}

function AgentRepositoryDetailTools({ tools }: { tools: string[] }) {
  const { t } = useTranslation("common");

  if (tools.length === 0) {
    return null;
  }

  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
        <Wrench className="size-4 text-primary" aria-hidden />
        {t("agentRepository.detail.tools")}
      </h3>
      <div className="flex flex-wrap gap-1.5">
        {tools.map((tool) => (
          <Tag key={tool} className="m-0 font-mono text-xs">
            {tool}
          </Tag>
        ))}
      </div>
    </section>
  );
}

function AgentRepositoryDetailDutyPrompt({
  dutyPrompt,
}: {
  dutyPrompt?: string | null;
}) {
  const { t } = useTranslation("common");
  const trimmedPrompt = dutyPrompt?.trim();

  if (!trimmedPrompt) {
    return null;
  }

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
        {t("agentRepository.detail.role")}
      </h3>
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs leading-relaxed text-slate-600 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300">
        {trimmedPrompt}
      </pre>
    </section>
  );
}

function AgentRepositoryDetailContent({ detail }: { detail: AgentDetailModalData }) {
  const { t } = useTranslation("common");
  const tools = detail.tools?.filter((tool) => tool.trim()) ?? [];

  return (
    <div className="max-h-[80vh] overflow-y-auto">
      <AgentRepositoryDetailHeader detail={detail} />
      <div className="space-y-6 p-6">
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {t("agentRepository.detail.intro")}
          </h3>
          <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">
            {detail.description?.trim() ||
              t("agentRepository.card.noDescription")}
          </p>
        </section>
        <AgentRepositoryDetailTools tools={tools} />
        <AgentRepositoryDetailDutyPrompt dutyPrompt={detail.duty_prompt} />
      </div>
    </div>
  );
}

function resolveDetailModalBody({
  isLoading,
  isError,
  isFetching,
  detail,
  onRetry,
}: Pick<
  AgentRepositoryDetailModalProps,
  "isLoading" | "isError" | "isFetching" | "detail" | "onRetry"
>) {
  if (isLoading) {
    return <AgentRepositoryDetailLoading />;
  }
  if (isError) {
    return (
      <AgentRepositoryDetailError onRetry={onRetry} isFetching={isFetching} />
    );
  }
  if (!detail) {
    return null;
  }
  return <AgentRepositoryDetailContent detail={detail} />;
}

export function AgentRepositoryDetailModal({
  open,
  onClose,
  detail,
  isLoading,
  isError,
  isFetching,
  onRetry,
}: AgentRepositoryDetailModalProps) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      centered
      destroyOnHidden
      title={null}
      className="agent-repository-detail-modal"
      styles={{ body: { padding: 0 } }}
    >
      {resolveDetailModalBody({
        isLoading,
        isError,
        isFetching,
        detail,
        onRetry,
      })}
    </Modal>
  );
}
