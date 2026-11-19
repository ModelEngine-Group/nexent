// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
