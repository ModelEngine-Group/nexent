"use client";

import { useMemo } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { theme, Typography, Tag, Switch, Tooltip } from "antd";
import { ShieldCheck, ShieldOff, ShieldAlert, Settings2 } from "lucide-react";

import type {
  GuardrailConfig,
  GuardrailRule,
  GuardrailSeverity,
} from "@/types/agentConfig";

const { Text } = Typography;

const SEVERITY_META: Record<GuardrailSeverity, { color: string; icon: ReactNode }> = {
  block: { color: "error", icon: <ShieldOff size={12} /> },
  mask: { color: "warning", icon: <ShieldAlert size={12} /> },
  pass: { color: "success", icon: <ShieldCheck size={12} /> },
};

interface GuardrailSummaryCardProps {
  config: GuardrailConfig;
  onToggle: (enabled: boolean) => void;
  onOpenConfig: () => void;
}

/**
 * Compact summary card embedded in the agent detail page.
 * Shows enable switch, rule count, severity distribution, and a button to open the modal.
 */
export default function GuardrailSummaryCard({
  config,
  onToggle,
  onOpenConfig,
}: GuardrailSummaryCardProps) {
  const { token } = theme.useToken();
  const { t } = useTranslation("common");

  const severityCounts = useMemo(() => {
    const counts: Record<GuardrailSeverity, number> = { block: 0, mask: 0, pass: 0 };
    config.rules.forEach((r: GuardrailRule) => {
      counts[r.severity] = (counts[r.severity] || 0) + 1;
    });
    return counts;
  }, [config.rules]);

  const enabled = config.enabled;
  const ruleCount = config.rules.length;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 16px",
        borderRadius: 10,
        border: `0.5px solid ${enabled ? "#B5D4F4" : token.colorBorderSecondary}`,
        background: enabled ? "#E6F1FB" : token.colorFillQuaternary,
        transition: "all 0.2s",
      }}
    >
      {/* Icon */}
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: 8,
          background: enabled ? "#185FA5" : token.colorBgContainer,
          color: enabled ? "#fff" : token.colorTextTertiary,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <ShieldCheck size={16} />
      </div>

      {/* Text block */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Text strong style={{ fontSize: 13, color: enabled ? "#042C53" : token.colorText }}>
            {t("agent.guardrail.summaryTitle") || "Guardrail"}
          </Text>
          <Tag
            style={{
              fontSize: 10,
              margin: 0,
              padding: "1px 8px",
              borderRadius: 10,
              border: "none",
              background: enabled ? "#185FA5" : token.colorFillSecondary,
              color: enabled ? "#fff" : token.colorTextTertiary,
            }}
          >
            {ruleCount} {t("agent.guardrail.rules") || "rules"}
          </Tag>
        </div>
        {/* Severity distribution */}
        {enabled && ruleCount > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
            {severityCounts.block > 0 && (
              <Tag
                color="error"
                icon={<ShieldOff size={12} />}
                style={{ margin: 0, fontSize: 10, padding: "1px 8px", display: "inline-flex", alignItems: "center", gap: 3 }}
              >
                {severityCounts.block}
              </Tag>
            )}
            {severityCounts.mask > 0 && (
              <Tag
                color="warning"
                icon={<ShieldAlert size={12} />}
                style={{ margin: 0, fontSize: 10, padding: "1px 8px", display: "inline-flex", alignItems: "center", gap: 3 }}
              >
                {severityCounts.mask}
              </Tag>
            )}
            {severityCounts.pass > 0 && (
              <Tag
                color="success"
                icon={<ShieldCheck size={12} />}
                style={{ margin: 0, fontSize: 10, padding: "1px 8px", display: "inline-flex", alignItems: "center", gap: 3 }}
              >
                {severityCounts.pass}
              </Tag>
            )}
          </div>
        )}
      </div>

      {/* Toggle */}
      <Tooltip title={enabled ? (t("agent.guardrail.disable") || "Disable") : (t("agent.guardrail.enable") || "Enable")}>
        <Switch checked={enabled} onChange={onToggle} size="small" />
      </Tooltip>

      {/* Config button */}
      <button
        onClick={onOpenConfig}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "5px 14px",
          fontSize: 12,
          fontWeight: 500,
          color: enabled ? "#185FA5" : token.colorTextSecondary,
          background: "transparent",
          border: `0.5px solid ${enabled ? "#185FA5" : token.colorBorderSecondary}`,
          borderRadius: 6,
          cursor: "pointer",
          transition: "all 0.15s",
          whiteSpace: "nowrap",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = "#185FA5";
          (e.currentTarget as HTMLButtonElement).style.color = "#fff";
          (e.currentTarget as HTMLButtonElement).style.borderColor = "#0C447C";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = "transparent";
          (e.currentTarget as HTMLButtonElement).style.color = enabled ? "#185FA5" : token.colorTextSecondary;
          (e.currentTarget as HTMLButtonElement).style.borderColor = enabled ? "#185FA5" : token.colorBorderSecondary;
        }}
      >
        <Settings2 size={14} />
        {t("agent.guardrail.configure") || "Configure Rules"}
      </button>
    </div>
  );
}
