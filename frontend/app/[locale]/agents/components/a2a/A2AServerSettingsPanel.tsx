"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Tag,
  message,
} from "antd";
import { Copy, CheckCircle, Info } from "lucide-react";

interface A2ASupportedInterface {
  protocolBinding?: string;
  url?: string;
  protocolVersion?: string;
}

interface A2AServerSettingsPanelProps {
  endpointId?: string;
  supportedInterfaces?: A2ASupportedInterface[];
}

export default function A2AServerSettingsPanel({
  endpointId,
  supportedInterfaces,
}: A2AServerSettingsPanelProps) {
  const { t } = useTranslation("common");



  const [messageApi, contextHolder] = message.useMessage();

  const [copiedField, setCopiedField] = useState<string | null>(null);

  const previewData = (() => {
    if (!endpointId || !supportedInterfaces) return null;

    const restInterface = supportedInterfaces.find((iface) => {
      const binding = iface.protocolBinding?.toLowerCase();
      return binding === "http+json" || binding === "httprest";
    });

    const restUrl = restInterface?.url || "";
    return {
      endpointId,
      agentCardUrl: `/nb/a2a/${endpointId}/.well-known/agent-card.json`,
      restEndpoints: {
        message_send: restUrl ? `${restUrl}/message:send` : "",
        message_stream: restUrl ? `${restUrl}/message:stream` : "",
        tasks_get: restUrl ? `${restUrl}/tasks/{task_id}` : "",
      },
    };
  })();

  const handleCopy = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    messageApi.success(t("common.copied"));
    setTimeout(() => setCopiedField(null), 2000);
  };

  const CopyButton = ({
    text,
    field,
  }: {
    text: string;
    field: string;
  }) => (
    <Button
      type="text"
      size="small"
      icon={copiedField === field ? <CheckCircle size={14} /> : <Copy size={14} />}
      onClick={() => handleCopy(text, field)}
    />
  );

  return (
    <>
      {contextHolder}
      <div className="space-y-4">

        <p className="text-sm text-gray-500">
          {t("a2a.server.previewDescription")}
        </p>

        {/* Endpoint Info Preview */}
        {previewData ? (
          <div className="bg-gray-50 rounded p-4 space-y-3 min-w-0">
            {/* Endpoint ID */}
            <div className="flex flex-col sm:flex-row sm:items-start gap-2">
              <div className="sm:w-[150px] sm:flex-shrink-0 flex items-center justify-between">
                <span className="text-sm text-gray-600">{t("a2a.server.endpointId")}</span>
                <CopyButton text={previewData.endpointId} field="endpointId" />
              </div>
              <code className="text-xs bg-gray-100 px-2 py-1 rounded break-all">{previewData.endpointId}</code>
            </div>

            {/* Agent Card URL */}
            <div className="flex flex-col sm:flex-row sm:items-start gap-2">
              <div className="sm:w-[150px] sm:flex-shrink-0 flex items-center justify-between">
                <span className="text-sm text-gray-600">{t("a2a.server.agentCardUrl")}</span>
                <CopyButton text={previewData.agentCardUrl} field="agentCardUrl" />
              </div>
              <div className="flex flex-col gap-1 min-w-0 w-full">
                <code className="text-xs bg-gray-100 px-2 py-1 rounded break-all">{previewData.agentCardUrl}</code>
                <span className="text-xs text-gray-500">
                  {t("a2a.server.urlHint", { defaultValue: "Append base URL to access. For local dev: localhost:5013" })}
                </span>
              </div>
            </div>

            {/* Protocol Version */}
            <div className="flex flex-col sm:flex-row sm:items-start gap-2">
              <div className="sm:w-[150px] sm:flex-shrink-0 text-sm text-gray-600">{t("a2a.server.protocolVersion")}</div>
              <Tag color="green">1.0</Tag>
            </div>

            {/* REST Endpoints */}
            <div className="flex flex-col sm:flex-row sm:items-start gap-2">
              <div className="sm:w-[150px] sm:flex-shrink-0 text-sm text-gray-600">{t("a2a.server.restEndpoints")}</div>
              <div className="flex flex-col gap-1 text-xs min-w-0">
                <div><Tag color="blue">POST</Tag> <code className="break-all">{previewData.restEndpoints.message_send}</code></div>
                <div><Tag color="blue">POST</Tag> <code className="break-all">{previewData.restEndpoints.message_stream}</code></div>
                <div><Tag color="green">GET</Tag> <code className="break-all">{previewData.restEndpoints.tasks_get}</code></div>
              </div>
            </div>

            {/* JSON-RPC Methods */}
            <div className="flex flex-col sm:flex-row sm:items-start gap-2">
              <div className="sm:w-[150px] sm:flex-shrink-0 text-sm text-gray-600">JSON-RPC</div>
              <div className="flex flex-col gap-1 text-xs min-w-0">
                <div>
                  <Tag color="purple">POST</Tag>
                  <span className="text-gray-500 ml-1">{t("a2a.server.sameUrl")}:</span>
                  <code className="break-all ml-1">/nb/a2a/{previewData.endpointId}/v1</code>
                </div>
                <div className="ml-6 text-gray-600">
                  <div>• SendMessage: method="SendMessage"</div>
                  <div>• SendStreamingMessage: method="SendStreamingMessage"</div>
                  <div>• GetTask: method="GetTask"</div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-gray-500 p-4 bg-gray-50 rounded">
            {t("a2a.server.noAgentCard")}
          </div>
        )}

        {/* Usage Note */}
        <div className="text-xs text-gray-500 p-3 bg-blue-50 rounded border border-blue-100">
          <div className="flex items-start gap-2">
            <Info size={14} className="mt-0.5 flex-shrink-0 text-blue-500" />
            <div>
              <p className="font-medium text-blue-700 mb-1">
                {t("a2a.server.usageTitle", { defaultValue: "How to use these endpoints" })}
              </p>
              <p className="mb-1">
                {t("a2a.server.localDevHint", { defaultValue: "For local development: prepend localhost:5013 to the paths above." })}
              </p>
              <p>
                {t("a2a.server.productionHint", { defaultValue: "For production: replace localhost:5013 with your server domain or public IP and port 5013." })}
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
