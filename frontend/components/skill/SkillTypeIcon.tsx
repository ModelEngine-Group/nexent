// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { FileText, Layers, Presentation } from "lucide-react";
import { cn } from "@/lib/utils";
import { getSkillRepositoryIconKind } from "@/lib/skillRepositoryIcon";

export default function SkillTypeIcon({
  name,
  tags,
  icon,
  className,
}: {
  name: string;
  tags?: string[];
  icon?: string | null;
  className?: string;
}) {
  const { Icon, className: tone } = {
    document: { Icon: FileText, className: "bg-[#DFF4CC] text-[#316614]" },
    presentation: {
      Icon: Presentation,
      className: "bg-[#FBE5FA] text-[#B52BA5]",
    },
    general: { Icon: Layers, className: "bg-[#E7EDFF] text-[#2468CC]" },
  }[getSkillRepositoryIconKind({ name, tags, icon })];
  return (
    <div
      className={cn("flex size-12 shrink-0 items-center justify-center rounded-lg", tone, className)}
    >
      <Icon className="size-6" aria-hidden />
    </div>
  );
}
