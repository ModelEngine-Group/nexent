// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";
import {
  openImportWizardWithFile,
  type ImportAgentData,
} from "@/lib/agentImportUtils";
import log from "@/lib/logger";

export function useAgentFileImport() {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const [importData, setImportData] = useState<ImportAgentData | null>(null);

  const openImport = () =>
    openImportWizardWithFile({ onSuccess: setImportData, message, t, log });

  return {
    importData,
    openImport,
    closeImport: () => setImportData(null),
  };
}
