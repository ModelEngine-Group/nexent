// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import ResourcePanelTitle from "@/components/resource/ResourcePanelTitle";
import SkillTypeIcon from "./SkillTypeIcon";

export default function SkillPanelTitle({
  name,
  title = name,
  subtitle,
  tags,
  icon,
}: {
  name: string;
  title?: string;
  subtitle?: ReactNode;
  tags?: string[];
  icon?: string | null;
}) {
  return (
    <ResourcePanelTitle
      title={title}
      icon={<SkillTypeIcon name={name} tags={tags} icon={icon} />}
      subtitle={subtitle}
    />
  );
}
