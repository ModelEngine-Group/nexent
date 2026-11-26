// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import Link from "next/link";
import { Card, Flex, Typography } from "antd";
import { ArrowRight, BookOpen, Braces, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

const directions = [
  { id: "prompt", icon: Braces },
  { id: "skill", icon: BookOpen },
  { id: "tool", icon: Wrench },
] as const;

export type EvolutionDirection = (typeof directions)[number]["id"] | "combination";

export function readEvolutionDirection(value: string | null | undefined): EvolutionDirection | undefined {
  if (value === "combination") return value;
  return directions.find(({ id }) => id === value)?.id;
}

type EvolutionScope = { agent?: number; version?: number; evaluationSet?: number };

export function evolutionHref(direction?: EvolutionDirection, scope?: EvolutionScope) {
  const params = new URLSearchParams({ tab: "evolution" });
  if (direction) params.set("direction", direction);
  if (scope?.agent) params.set("agent_id", String(scope.agent));
  if (scope?.version) params.set("version_no", String(scope.version));
  if (scope?.evaluationSet) params.set("set_id", String(scope.evaluationSet));
  return `?${params}`;
}

export function matchesDirection(direction: EvolutionDirection | undefined, kind?: string | null, methods?: string[] | null) {
  if (!direction) return true;
  if (kind === "prompt") {
    const tool = methods?.some(method => method === "T1" || method === "T2");
    const prompt = !tool || !!methods?.some(method => method === "P1" || method === "P2" || method === "P3");
    return direction === "tool" ? !!tool : direction === "prompt" && prompt;
  }
  if (direction === "skill") return !!kind?.startsWith("skill_");
  if (direction === "tool") return !!kind?.startsWith("tool_");
  return direction === "combination" && kind === "combination";
}

export function EvolutionDirectionGuide({ scope }: { scope: EvolutionScope }) {
  const { t } = useTranslation("common");
  return (
    <Flex vertical gap={16}>
      <div>
        <Typography.Title level={4} className="!mb-1">{t("evolution.direction.choose")}</Typography.Title>
        <Typography.Text type="secondary">{t("evolution.direction.intro")}</Typography.Text>
      </div>
      <nav aria-label={t("evolution.direction.choose")} className="grid gap-4 md:grid-cols-3">
        {directions.map(({ id, icon: Icon }) => (
          <Card key={id} size="small" className="h-full">
            <Flex vertical gap={10}>
              <Link href={evolutionHref(id, scope)} className="flex items-center gap-2 text-primary hover:underline">
                <Icon aria-hidden="true" size={18} />
                <span className="font-semibold">{t(`evolution.direction.${id}`)}</span>
                <ArrowRight aria-hidden="true" size={16} className="ms-auto" />
              </Link>
              <Typography.Text type="secondary">{t(`evolution.direction.${id}Description`)}</Typography.Text>
            </Flex>
          </Card>
        ))}
      </nav>
      <Link href={evolutionHref("combination", scope)} className="self-start text-primary hover:underline">
        {t("evolution.direction.combination")}
      </Link>
    </Flex>
  );
}
