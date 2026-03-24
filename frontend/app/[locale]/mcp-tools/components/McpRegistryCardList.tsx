import { Button } from "antd";
import type { RegistryMcpCard } from "@/types/mcpTools";
import McpRegistryCard from "./McpRegistryCard";

interface Props {
  registryLoading: boolean;
  services: RegistryMcpCard[];
  hasPrevRegistryPage: boolean;
  hasNextRegistryPage: boolean;
  onPrevRegistryPage: () => void;
  onNextRegistryPage: () => void;
  onSelectRegistryService: (service: RegistryMcpCard) => void;
  onQuickAddFromRegistry: (service: RegistryMcpCard) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function McpRegistryCardList({
  registryLoading,
  services,
  hasPrevRegistryPage,
  hasNextRegistryPage,
  onPrevRegistryPage,
  onNextRegistryPage,
  onSelectRegistryService,
  onQuickAddFromRegistry,
  t,
}: Props) {
  if (registryLoading) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.registry.loading")}
      </div>
    );
  }

  if (services.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.registry.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 max-h-[55vh] overflow-y-auto pr-1">
        {services.map((service, index) => (
          <McpRegistryCard
            key={`${service.name}::${service.version || "-"}::${service.publishedAt || "-"}::${index}`}
            service={service}
            t={t}
            onSelectRegistryService={onSelectRegistryService}
            onQuickAddFromRegistry={onQuickAddFromRegistry}
          />
        ))}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
        <Button className="rounded-full" onClick={onPrevRegistryPage} disabled={!hasPrevRegistryPage || registryLoading}>
          {t("mcpTools.registry.prevPage")}
        </Button>
        <Button className="rounded-full" onClick={onNextRegistryPage} disabled={!hasNextRegistryPage || registryLoading}>
          {t("mcpTools.registry.nextPage")}
        </Button>
      </div>
    </div>
  );
}
