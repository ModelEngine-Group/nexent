// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import {
  DEFAULT_AGENT_ICONS,
  type DefaultAgentIconKey,
} from "@/lib/chat/agentIconUtils";

interface AgentAvatarOptionsProps {
  disabled: boolean;
  selectedKey?: DefaultAgentIconKey | null;
  onSelect: (key: DefaultAgentIconKey, svg: SVGSVGElement) => void;
}

export default function AgentAvatarOptions({
  disabled,
  selectedKey,
  onSelect,
}: AgentAvatarOptionsProps) {
  const { t } = useTranslation("common");
  const label = t("agent.highFidelity.defaultAvatars");

  return (
    <div
      className="flex min-w-0 flex-col gap-2"
      role="group"
      aria-label={label}
    >
      <span className="text-xs leading-[22px] text-[#808080]">{label}</span>
      <div className="flex flex-wrap gap-2">
        {DEFAULT_AGENT_ICONS.map(({ key, icon: Icon }) => {
          const name = t(`agent.avatar.${key}`);
          const selected = selectedKey === key;
          return (
            <Tooltip key={key} title={name}>
              <Button
                type="default"
                aria-label={t("agent.avatar.choose", { name })}
                aria-pressed={selected}
                disabled={disabled}
                className={`!flex !size-9 !shrink-0 !items-center !justify-center !rounded-lg !p-0 !text-[#0067d1] disabled:!opacity-50 ${selected ? "!border-[#0067d1] !bg-[#e6f2fd]" : "!border-[#dce3eb] !bg-white hover:!border-[#0067d1] hover:!bg-[#f0f7ff]"}`}
                onClick={(event) => {
                  const svg = event.currentTarget.querySelector("svg");
                  if (svg) onSelect(key, svg);
                }}
              >
                <Icon size={20} aria-hidden="true" />
              </Button>
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}
