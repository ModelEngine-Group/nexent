"use client";

import { useTranslation } from "react-i18next";

import CreateResourceCard from "@/components/resource/CreateResourceCard";

interface CreateNewSkillCardProps {
  onClick: () => void;
}

export function CreateNewSkillCard({ onClick }: CreateNewSkillCardProps) {
  const { t } = useTranslation("common");
  return (
    <CreateResourceCard
      title={t("skillRepository.mine.addSkillService")}
      onClick={onClick}
    />
  );
}
