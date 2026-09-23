import { useTranslation } from "react-i18next";

import CreateResourceCard from "@/components/resource/CreateResourceCard";

interface AddMcpServiceCardProps {
  onClick: () => void;
}

export default function AddMcpServiceCard({ onClick }: AddMcpServiceCardProps) {
  const { t } = useTranslation("common");
  return (
    <CreateResourceCard
      title={t("mcpTools.mine.addService")}
      onClick={onClick}
    />
  );
}
