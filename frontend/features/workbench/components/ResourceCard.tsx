import { useId, type ReactNode } from "react";
import SharedResourceCard from "@/components/resource/ResourceCard";
import { ArrowRight, Bot, BookOpen, Check, Puzzle } from "lucide-react";

export function ResourceCard({
  title,
  description,
  tags = [],
  badges = [],
  icon,
  subtitle,
  disabledReason,
  selected = false,
  disabled = false,
  footer,
  onClick,
  actions,
  resourceType = "agent",
}: {
  title: string;
  description?: string;
  tags?: readonly string[];
  badges?: readonly string[];
  icon?: ReactNode;
  subtitle?: string;
  disabledReason?: string;
  selected?: boolean;
  disabled?: boolean;
  footer?: ReactNode;
  onClick?: () => void;
  actions?: ReactNode;
  resourceType?: "agent" | "skill" | "knowledge";
}) {
  const reasonId = useId();
  const Icon =
    resourceType === "skill"
      ? Puzzle
      : resourceType === "knowledge"
        ? BookOpen
        : Bot;
  const uniqueTags = [
    ...new Set(tags.map((tag) => tag.trim()).filter(Boolean)),
  ];
  return (
    <SharedResourceCard
      title={
        <span className="flex items-center justify-between gap-2">
          {title}
          {selected && (
            <Check size={18} aria-hidden className="shrink-0 text-blue-600" />
          )}
        </span>
      }
      description={description}
      icon={
        <span
          aria-hidden
          className="flex size-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600"
        >
          {icon ?? <Icon size={24} />}
        </span>
      }
      selected={selected}
      disabled={disabled}
      selectionRole="option"
      describedBy={disabledReason ? reasonId : undefined}
      onClick={onClick ?? (() => {})}
      className="h-[220px] min-h-0 rounded-xl p-4 [&_h2]:text-lg [&_h2]:leading-6 [&_.line-clamp-3]:line-clamp-2 [&_.line-clamp-3]:mt-2 [&_.mt-3]:mt-2 [&_.border-t]:pt-3"
      badge={
        badges.length > 0 ? (
          <span
            className="flex gap-1 overflow-hidden whitespace-nowrap"
            aria-label="资源状态"
            title={badges.join("、")}
          >
            {badges.map((badge) => (
              <span
                className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
                key={badge}
              >
                {badge}
              </span>
            ))}
          </span>
        ) : undefined
      }
      tags={
        uniqueTags.length > 0 ? (
          <span
            className="flex max-w-full gap-1 overflow-hidden whitespace-nowrap"
            aria-label="标签"
            title={uniqueTags.join("、")}
          >
            {uniqueTags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                {tag}
              </span>
            ))}
            {uniqueTags.length > 3 && (
              <span
                title={uniqueTags.join("、")}
                aria-label={uniqueTags.join("、")}
              >
                +{uniqueTags.length - 3}
              </span>
            )}
          </span>
        ) : undefined
      }
      meta={
        subtitle || disabledReason ? (
          <div className="space-y-1 text-xs">
            {subtitle && (
              <div className="text-muted-foreground">{subtitle}</div>
            )}
            {disabledReason && (
              <div id={reasonId} className="text-destructive">
                {disabledReason}
              </div>
            )}
          </div>
        ) : undefined
      }
      footer={
        actions ?? (
          <button
            type="button"
            disabled={disabled}
            onClick={onClick}
            className="inline-flex items-center gap-2 whitespace-nowrap text-sm font-medium text-slate-600 hover:text-blue-600 disabled:cursor-not-allowed"
          >
            {disabled ? "不可用" : footer || (selected ? "已选择" : "选择")}
            {!disabled && <ArrowRight size={16} aria-hidden />}
          </button>
        )
      }
    />
  );
}
