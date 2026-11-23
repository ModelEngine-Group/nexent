"use client";

import { useTranslation } from "react-i18next";

import CreateResourceCard from "@/components/resource/CreateResourceCard";

interface CreateNewAgentCardProps {
  onClick: () => void;
}

export function CreateNewAgentCard({ onClick }: CreateNewAgentCardProps) {
  const { t } = useTranslation("common");
  return (
    <CreateResourceCard
      title={t("agentRepository.mine.createNewAgent")}
      onClick={onClick}
    />
  );
}
