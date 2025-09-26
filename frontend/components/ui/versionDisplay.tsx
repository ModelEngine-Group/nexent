import React from "react";
import { useTranslation } from "react-i18next";
import { APP_VERSION } from "@/const/version";

interface VersionDisplayProps {
  className?: string;
}

export const VersionDisplay: React.FC<VersionDisplayProps> = ({
  className = "",
}) => {
  const { t } = useTranslation("common");

  return (
    <span
      className={`text-sm text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors cursor-pointer ${className}`}
      title={`${APP_VERSION}`}
    >
      {t("app.version")}
    </span>
  );
};
