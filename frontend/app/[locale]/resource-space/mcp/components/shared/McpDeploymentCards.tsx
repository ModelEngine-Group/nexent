// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Radio } from "antd";
import { useTranslation } from "react-i18next";
import { McpDeploymentType } from "@/const/mcpTools";
import { cn } from "@/lib/utils";

const deploymentOptions = [
  {
    value: McpDeploymentType.REMOTE_LINK,
    labelKey: "mcpConfig.addServer.title",
    descriptionKey: "mcpTools.addModal.mode.remoteDescription",
  },
  {
    value: McpDeploymentType.CONTAINER,
    labelKey: "mcpTools.addModal.mode.container",
    descriptionKey: "mcpTools.addModal.mode.containerDescription",
  },
  {
    value: McpDeploymentType.API,
    labelKey: "mcpTools.addModal.mode.api",
    descriptionKey: "mcpTools.addModal.mode.apiDescription",
  },
  {
    value: McpDeploymentType.LOCAL_IMAGE,
    labelKey: "mcpConfig.uploadImage.title",
    descriptionKey: "mcpTools.addModal.mode.uploadDescription",
  },
] as const;

export default function McpDeploymentCards({
  value,
  includeLocalImage = false,
  onChange,
  ariaLabel,
  className,
}: {
  value: McpDeploymentType;
  includeLocalImage?: boolean;
  onChange?: (value: McpDeploymentType) => void;
  ariaLabel: string;
  className?: string;
}) {
  const { t } = useTranslation("common");
  const options = deploymentOptions.filter(
    (option) =>
      option.value !== McpDeploymentType.LOCAL_IMAGE ||
      includeLocalImage ||
      option.value === value
  );

  return (
    <Radio.Group
      aria-label={ariaLabel}
      value={value}
      disabled={onChange ? undefined : true}
      onChange={(event) => onChange?.(event.target.value)}
      className={cn(
        "!grid w-full grid-cols-[repeat(auto-fit,minmax(min(100%,155px),1fr))] gap-4",
        className
      )}
    >
      {options.map((option) => (
        <Radio.Button
          key={option.value}
          value={option.value}
          className={cn(
            "!h-auto min-h-[104px] !whitespace-normal !rounded-lg !border !px-4 !py-4 !leading-5 before:!hidden",
            !onChange && "!cursor-default !bg-background",
            !onChange &&
              (value === option.value ? "!border-primary" : "!border-border")
          )}
        >
          <span className="block font-medium text-[#191919]">
            {t(option.labelKey)}
          </span>
          <span className="mt-1 block font-normal text-[#777777]">
            {t(option.descriptionKey)}
          </span>
        </Radio.Button>
      ))}
    </Radio.Group>
  );
}
