"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Bot,
  CheckCircle2,
  FileCode2,
  Loader2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { buildSkillSavePayload } from "../creationRuntime";
import { searchAgentInfo } from "@/services/agentConfigService";
import { fetchMyEditableSkills } from "@/services/skillRepositoryService";

type SkillPayload = NonNullable<ReturnType<typeof buildSkillSavePayload>>;

export function AgentCreationResultCard({
  agentId,
  name,
  description,
  completed = true,
}: {
  agentId: number;
  name?: string;
  description?: string;
  completed?: boolean;
}) {
  const { t } = useTranslation("common");
  const [agentDetails, setAgentDetails] = useState<{
    name: string;
    description?: string;
  } | null>(null);

  useEffect(() => {
    if (name) return;
    let cancelled = false;
    void searchAgentInfo(agentId, undefined, 0)
      .then((result) => {
        if (cancelled || !result.success || !result.data) return;
        setAgentDetails({
          name: String(result.data.display_name || result.data.name || "Agent"),
          description: result.data.description || undefined,
        });
      })
      .catch(() => {
        // The Agent ID is still a usable route if details cannot be loaded.
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, name]);

  const displayName =
    name ||
    agentDetails?.name ||
    `${t("workbench.creation.agentType", "智能体应用")} #${agentId}`;
  const displayDescription = description || agentDetails?.description;
  return (
    <Link
      href={`/agents?agent_id=${agentId}`}
      className="group my-4 block w-full min-w-0 overflow-hidden rounded-2xl border border-border bg-card shadow-sm transition-all hover:border-primary/45 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="flex items-start gap-3 p-4">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Bot className="size-5" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              {t("workbench.creation.agentType", "智能体应用")}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700 dark:bg-sky-950 dark:text-sky-300">
              <CheckCircle2 className="size-3" aria-hidden="true" />
              {completed
                ? t("workbench.creation.agentDraftReady", "草稿已生成")
                : t("workbench.creation.agentDraftSaved", "草稿已保存")}
            </span>
          </div>
          <h3 className="mt-1 truncate text-base font-semibold text-foreground">
            {displayName}
          </h3>
          {displayDescription ? (
            <p className="mt-1 line-clamp-2 text-sm leading-5 text-muted-foreground">
              {displayDescription}
            </p>
          ) : null}
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-border/70 bg-muted/30 px-4 py-2.5 text-sm font-medium text-primary">
        <span>{t("workbench.creation.openAgent", "进入智能体开发")}</span>
        <ArrowUpRight
          className="size-4 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      </div>
    </Link>
  );
}

export function SkillCreationResultCard({
  payload,
  saved,
  onSave,
}: {
  payload: SkillPayload | null;
  saved: boolean;
  onSave: (payload: SkillPayload) => Promise<void>;
}) {
  const { t } = useTranslation("common");
  const [saving, setSaving] = useState(false);
  const [lookup, setLookup] = useState<{
    name: string;
    status: "checking" | "saved" | "unsaved" | "error";
  }>({ name: payload?.name ?? "", status: "checking" });
  const [lookupVersion, setLookupVersion] = useState(0);
  const skillName = payload?.name;

  useEffect(() => {
    if (!skillName || saved) return;
    let cancelled = false;
    const name = skillName;
    void (async () => {
      try {
        for (let page = 1; ; page += 1) {
          const result = await fetchMyEditableSkills({
            ownership: "created",
            search: name,
            page,
            page_size: 100,
            new_skill_padding: false,
          });
          if (cancelled) return;
          if (
            result.items.some(
              (item) => "skill_id" in item && item.name === name
            )
          ) {
            setLookup({ name, status: "saved" });
            return;
          }
          if (page >= result.pagination.total_pages) break;
        }
        setLookup({ name, status: "unsaved" });
      } catch {
        if (!cancelled) setLookup({ name, status: "error" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [skillName, saved, lookupVersion]);

  if (!payload) {
    return (
      <p className="my-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
        {t(
          "workbench.creation.invalidSkill",
          "生成的 SKILL.md 缺少有效的 name 或 description，暂不能保存；请继续让智能体修正。"
        )}
      </p>
    );
  }
  const status = lookup.name === payload.name ? lookup.status : "checking";
  const isSaved = saved || status === "saved";
  return (
    <div className="my-4 rounded-xl border border-primary/25 bg-primary/5 p-4">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <FileCode2 className="size-4" />
        {isSaved
          ? t("workbench.creation.skillCreated", "Skill 已保存")
          : t("workbench.creation.skillReady", "Skill 草稿已生成")}
      </div>
      <p className="my-2 text-sm font-medium">{payload.name}</p>
      <p className="mb-3 text-xs text-muted-foreground">
        {payload.description} · {payload.files.length + 1} files
      </p>
      {isSaved ? (
        <Button asChild size="sm" variant="outline">
          <Link href="/skill-space?tab=mine">
            {t("workbench.creation.openSkills", "查看我的 Skills")}
          </Link>
        </Button>
      ) : status === "error" ? (
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setLookup({ name: payload.name, status: "checking" });
            setLookupVersion((version) => version + 1);
          }}
        >
          {t("workbench.creation.retrySkillLookup", "重新查询 Skill 状态")}
        </Button>
      ) : (
        <Button
          size="sm"
          disabled={saving || status === "checking"}
          onClick={async () => {
            setSaving(true);
            try {
              await onSave(payload);
            } finally {
              setSaving(false);
            }
          }}
        >
          {saving || status === "checking" ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : null}
          {t("workbench.creation.saveSkill", "保存 Skill")}
        </Button>
      )}
    </div>
  );
}
