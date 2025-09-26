import React from "react";
import { useTranslation } from "react-i18next";
import packageJson from "../../package.json";

interface VersionDisplayProps {
  className?: string;
}

export const VersionDisplay: React.FC<VersionDisplayProps> = ({
  className = "",
}) => {
  const { t } = useTranslation("common");
  const version = `${packageJson.version}`;
  return (
    <span
      className={`text-sm text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors cursor-pointer ${className}`}
      title={version}
    >
      {t("app.version")}
    </span>
  );
};
