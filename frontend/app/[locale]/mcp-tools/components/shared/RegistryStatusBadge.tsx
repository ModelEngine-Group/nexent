import { useTranslation } from "react-i18next";
import { getRegistryStatusBadge } from "@/lib/mcpTools";

interface RegistryStatusBadgeProps {
  status: string | undefined;
  /**
   * Picks between `mcpTools.registry.status.*` and `mcpTools.community.status.*`
   * translation keys. Defaults to `registry`.
   */
  variant?: "registry" | "community";
  /** Extra classes, e.g. to tweak padding on small cards. */
  className?: string;
}

/**
 * Small colour-coded status pill shared by registry & community cards and
 * their detail modals. Centralising it means every surface renders the same
 * colours and translation keys.
 */
export default function RegistryStatusBadge({
  status,
  variant = "registry",
  className = "",
}: RegistryStatusBadgeProps) {
  const { t } = useTranslation("common");
  const badge = getRegistryStatusBadge(status, variant);
  return (
    <span
      className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold ${badge.className} ${className}`}
    >
      {t(badge.textKey)}
    </span>
  );
}
