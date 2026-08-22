import { useTranslation } from "react-i18next";
import { McpServerStatus, McpServiceStatus } from "@/const/mcpTools";

interface RegistryStatusBadgeProps {
  status: string | undefined;
  className?: string;
}

/**
 * Registry / community server status (active, deprecated, unknown) using
 * `mcpTools.status.*` keys.
 */
export default function RegistryStatusBadge({
  status
}: RegistryStatusBadgeProps) {
  const { t } = useTranslation("common");
  const normalized = String(status || "").toLowerCase();

  let toneClass: string;
  let textKey: string;
  switch (normalized) {
    case McpServiceStatus.ENABLED:
      toneClass = "bg-emerald-100 text-emerald-700";
      textKey = "mcpTools.status.enabled";
      break;
    case McpServiceStatus.DISABLED:
      toneClass = "bg-slate-100 text-slate-600";
      textKey = "mcpTools.status.disabled";
      break;
    case McpServerStatus.ACTIVE:
      toneClass = "bg-emerald-100 text-emerald-700";
      textKey = "mcpTools.status.active";
      break;
    case McpServerStatus.DEPRECATED:
      toneClass = "bg-amber-100 text-amber-700";
      textKey = "mcpTools.status.deprecated";
      break;
    default:
      toneClass = "bg-slate-100 text-slate-600";
      textKey = "mcpTools.status.unknown";
  }

  return (
    <span
      className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold ${toneClass}`}
    >
      {t(textKey)}
    </span>
  );
}
