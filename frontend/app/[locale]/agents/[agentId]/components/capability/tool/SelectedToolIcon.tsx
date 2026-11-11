// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Blocks, Server } from "lucide-react";

export function SelectedToolIcon({ service = false }: { service?: boolean }) {
  const Icon = service ? Server : Blocks;

  return (
    <span
      aria-hidden="true"
      className="grid size-6 shrink-0 place-items-center rounded-md bg-gradient-to-br from-[#b9dcff] via-[#78a7f8] to-[#3978da] shadow-[0_2px_6px_rgba(57,120,218,0.24)]"
    >
      <Icon size={16} strokeWidth={2} className="text-white" />
    </span>
  );
}
