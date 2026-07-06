import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

interface AddMcpServiceCardProps {
  onClick: () => void;
}

export default function AddMcpServiceCard({ onClick }: AddMcpServiceCardProps) {
  const { t } = useTranslation("common");

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-[292px] cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-slate-300 bg-white p-5 shadow-sm transition hover:border-blue-400 hover:bg-blue-50/30 hover:shadow-md"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-600 transition group-hover:bg-blue-100">
        <Plus className="h-6 w-6" />
      </div>
      <span className="text-sm font-medium text-slate-500 transition group-hover:text-blue-600">
        {t("mcpTools.mine.addService")}
      </span>
    </button>
  );
}
