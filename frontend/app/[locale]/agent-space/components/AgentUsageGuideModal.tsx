"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Modal, Spin, Tabs, Typography } from "antd";
import { Copy, ExternalLink, RefreshCw, SquareX } from "lucide-react";
import { useTranslation } from "react-i18next";
import A2AServerSettingsPanel from "../../agents/components/a2a/A2AServerSettingsPanel";
import {
  buildAgentShareUrl,
  buildNorthboundDocsUrl,
  buildNorthboundCurl,
  buildNorthboundRunUrl,
  buildUserApiKeyPath,
  getAgentUsageGuideAccess,
  getA2AGuideState,
  reduceAgentShareGuideState,
} from "@/lib/agentUsageGuide";
import { a2aClientService } from "@/services/a2aService";
import { agentShareService } from "@/services/agentShareService";
import { configService } from "@/services/configService";
import type { MyEditableAgentItem } from "@/types/agentRepository";

interface AgentUsageGuideModalProps {
  agent: MyEditableAgentItem | null;
  locale: string;
  open: boolean;
  onClose: () => void;
}

export function AgentUsageGuideModal({
  agent,
  locale,
  open,
  onClose,
}: AgentUsageGuideModalProps) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("share");
  const agentId = agent?.agent_id;
  const agentName = agent?.name?.trim() || "agent";
  const { canManageShare } = getAgentUsageGuideAccess({
    currentVersionNo: agent?.current_version_no,
    permission: agent?.permission,
  });

  useEffect(() => {
    if (open) {
      setActiveTab("share");
    }
  }, [agentId, open]);

  const shareQuery = useQuery({
    queryKey: ["agent-share", agentId],
    queryFn: () => agentShareService.get(agentId!),
    enabled: open && activeTab === "share" && canManageShare && agentId != null,
  });
  const frontendConfigQuery = useQuery({
    queryKey: ["frontend-config"],
    queryFn: () => configService.fetchRuntimeFrontendConfig(),
    enabled: open && activeTab === "northbound",
  });
  const a2aQuery = useQuery({
    queryKey: ["a2aServerSettings", agentId],
    queryFn: () => a2aClientService.getServerSettings(agentId!),
    enabled: open && activeTab === "a2a" && agentId != null,
  });

  const refreshShare = () =>
    queryClient.invalidateQueries({ queryKey: ["agent-share", agentId] });
  const enableShare = useMutation({
    mutationFn: () => agentShareService.enable(agentId!),
    onSuccess: (share) => {
      queryClient.setQueryData(
        ["agent-share", agentId],
        reduceAgentShareGuideState(shareQuery.data ?? null, {
          type: "saved",
          share,
        })
      );
      void refreshShare();
      message.success(t("agentUsageGuide.share.enabled"));
    },
    onError: () => message.error(t("agentUsageGuide.share.error")),
  });
  const rotateShare = useMutation({
    mutationFn: () => agentShareService.rotate(agentId!),
    onSuccess: (share) => {
      queryClient.setQueryData(
        ["agent-share", agentId],
        reduceAgentShareGuideState(shareQuery.data ?? null, {
          type: "saved",
          share,
        })
      );
      void refreshShare();
      message.success(t("agentUsageGuide.share.rotated"));
    },
    onError: () => message.error(t("agentUsageGuide.share.error")),
  });
  const revokeShare = useMutation({
    mutationFn: () => agentShareService.revoke(agentId!),
    onSuccess: () => {
      queryClient.setQueryData(
        ["agent-share", agentId],
        reduceAgentShareGuideState(shareQuery.data ?? null, {
          type: "revoked",
        })
      );
      void refreshShare();
      message.success(t("agentUsageGuide.share.revoked"));
    },
    onError: () => message.error(t("agentUsageGuide.share.error")),
  });

  const shareUrl = useMemo(() => {
    if (!shareQuery.data || typeof window === "undefined") return "";
    return buildAgentShareUrl(
      window.location.origin,
      locale,
      shareQuery.data.share_token
    );
  }, [locale, shareQuery.data]);
  const northboundUrl = buildNorthboundRunUrl(
    frontendConfigQuery.data?.northboundBaseUrl,
    typeof window === "undefined" ? undefined : window.location.origin
  );
  const northboundCurl = buildNorthboundCurl(agentName, northboundUrl);
  const a2aGuideState = getA2AGuideState({
    isLoading: a2aQuery.isLoading,
    isError: a2aQuery.isError,
    isEnabled: Boolean(
      a2aQuery.data?.success && a2aQuery.data.data?.is_enabled
    ),
  });
  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      message.success(t("common.copied"));
    } catch {
      message.error(t("agentUsageGuide.copyFailed"));
    }
  };

  const confirm = (
    title: string,
    content: string,
    action: () => Promise<unknown>
  ) => {
    modal.confirm({ title, content, onOk: action });
  };

  return (
    <Modal
      title={t("agentUsageGuide.title", { name: agent?.name })}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      mask={{ closable: true }}
      width={760}
    >
      <div
        data-testid="agent-usage-guide-content"
        data-stable-height="true"
        className="min-h-[420px] max-h-[420px] overflow-y-auto pr-1"
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "share",
              label: t("agentUsageGuide.tabs.share"),
              children: canManageShare ? (
                <div className="space-y-4">
                  <Alert
                    type="info"
                    showIcon
                    message={t("agentUsageGuide.share.notice")}
                  />
                  <div className="pt-2">
                    {shareQuery.isLoading ? (
                      <Spin />
                    ) : shareQuery.isError ? (
                      <Button onClick={() => shareQuery.refetch()}>
                        {t("common.retry")}
                      </Button>
                    ) : shareUrl ? (
                      <div className="space-y-3">
                        <Typography.Paragraph
                          copyable={{ text: shareUrl }}
                          className="mb-0 break-all rounded bg-slate-50 p-3"
                        >
                          {shareUrl}
                        </Typography.Paragraph>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            icon={<Copy className="size-4" aria-hidden />}
                            onClick={() => copy(shareUrl)}
                          >
                            {t("common.copy")}
                          </Button>
                          <Button
                            icon={
                              <ExternalLink className="size-4" aria-hidden />
                            }
                            onClick={() =>
                              window.open(
                                shareUrl,
                                "_blank",
                                "noopener,noreferrer"
                              )
                            }
                          >
                            {t("agentUsageGuide.share.open")}
                          </Button>
                          <Button
                            icon={<RefreshCw className="size-4" aria-hidden />}
                            onClick={() =>
                              confirm(
                                t("agentUsageGuide.share.rotateTitle"),
                                t("agentUsageGuide.share.rotateContent"),
                                () => rotateShare.mutateAsync()
                              )
                            }
                          >
                            {t("agentUsageGuide.share.rotate")}
                          </Button>
                          <Button
                            danger
                            icon={<SquareX className="size-4" aria-hidden />}
                            onClick={() =>
                              confirm(
                                t("agentUsageGuide.share.revokeTitle"),
                                t("agentUsageGuide.share.revokeContent"),
                                () => revokeShare.mutateAsync()
                              )
                            }
                          >
                            {t("agentUsageGuide.share.revoke")}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <Button
                        type="primary"
                        loading={enableShare.isPending}
                        onClick={() =>
                          confirm(
                            t("agentUsageGuide.share.enableTitle"),
                            t("agentUsageGuide.share.enableContent"),
                            () => enableShare.mutateAsync()
                          )
                        }
                      >
                        {t("agentUsageGuide.share.enable")}
                      </Button>
                    )}
                  </div>
                </div>
              ) : (
                <Alert
                  type="info"
                  showIcon
                  message={t("agentUsageGuide.share.readOnly")}
                />
              ),
            },
            {
              key: "northbound",
              label: t("agentUsageGuide.tabs.northbound"),
              children: (
                <div className="space-y-4">
                  <ol className="list-decimal space-y-1 pl-5 text-sm">
                    <li>
                      <a
                        className="text-primary hover:underline"
                        href={buildUserApiKeyPath(locale)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t("agentUsageGuide.northbound.stepKey")}
                      </a>
                    </li>
                    <li>{t("agentUsageGuide.northbound.stepCall")}</li>
                    <li>{t("agentUsageGuide.northbound.stepResult")}</li>
                  </ol>
                  {frontendConfigQuery.isLoading ? (
                    <Spin />
                  ) : frontendConfigQuery.isError ? (
                    <Button onClick={() => frontendConfigQuery.refetch()}>
                      {t("common.retry")}
                    </Button>
                  ) : (
                    <div
                      data-testid="northbound-curl-example"
                      className="relative rounded bg-slate-950 p-3 text-slate-100"
                    >
                      <Button
                        size="small"
                        className="absolute right-2 top-2"
                        style={{
                          color: "#f8fafc",
                          backgroundColor: "#1e293b",
                          borderColor: "#475569",
                        }}
                        icon={<Copy className="size-4" aria-hidden />}
                        onClick={() => copy(northboundCurl)}
                      >
                        {t("common.copy")}
                      </Button>
                      <pre className="m-0 overflow-x-auto whitespace-pre-wrap pr-16 font-mono text-xs leading-5 text-slate-100">
                        <code>{northboundCurl}</code>
                      </pre>
                    </div>
                  )}
                  <Alert
                    type="info"
                    showIcon
                    message={t("agentUsageGuide.northbound.keyNotice")}
                  />
                  <div className="pt-2">
                    <a
                      href={buildNorthboundDocsUrl(locale)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t("agentUsageGuide.northbound.docs")}{" "}
                      <ExternalLink className="inline size-3" aria-hidden />
                    </a>
                  </div>
                </div>
              ),
            },
            {
              key: "a2a",
              label: t("agentUsageGuide.tabs.a2a"),
              children:
                a2aGuideState === "loading" ? (
                  <Spin />
                ) : a2aGuideState === "error" ? (
                  <Button onClick={() => a2aQuery.refetch()}>
                    {t("common.retry")}
                  </Button>
                ) : a2aGuideState === "enabled" ? (
                  <A2AServerSettingsPanel
                    endpointId={a2aQuery.data!.data!.endpoint_id}
                    supportedInterfaces={
                      a2aQuery.data!.data!.supported_interfaces
                    }
                  />
                ) : (
                  <Alert
                    type="info"
                    showIcon
                    message={t("agentUsageGuide.a2a.notEnabled")}
                  />
                ),
            },
          ]}
        />
      </div>
    </Modal>
  );
}
