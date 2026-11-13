// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { FileText, Layers, Presentation } from "lucide-react";
import { getSkillRepositoryIconKind } from "@/lib/skillRepositoryIcon";

export default function SkillTypeIcon({
  name,
  tags,
  icon,
}: {
  name: string;
  tags?: string[];
  icon?: string | null;
}) {
  const { Icon, className } = {
    document: { Icon: FileText, className: "bg-[#DFF4CC] text-[#316614]" },
    presentation: {
      Icon: Presentation,
      className: "bg-[#FBE5FA] text-[#B52BA5]",
    },
    general: { Icon: Layers, className: "bg-[#E7EDFF] text-[#2468CC]" },
  }[getSkillRepositoryIconKind({ name, tags, icon })];
  return (
    <div
      className={`flex size-12 shrink-0 items-center justify-center rounded-lg ${className}`}
    >
      <Icon className="size-6" aria-hidden />
    </div>
  );
}
