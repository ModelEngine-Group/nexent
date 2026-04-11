import { useMemo, useState } from "react";
import { Button, Input } from "antd";
import { MarkdownRenderer } from "@/components/ui/markdownRenderer";

type Props = {
  label: string;
  value?: string;
  t: (key: string, params?: Record<string, unknown>) => string;
  readOnly?: boolean;
  onChange?: (value: string) => void;
  minRows?: number;
  maxRows?: number;
  toggleMinChars?: number;
  toggleMinLines?: number;
  wrapperClassName?: string;
};

export default function McpDescriptionField({
  label,
  value,
  t,
  readOnly = false,
  onChange,
  minRows = 1,
  maxRows = 24,
  toggleMinChars = 160,
  toggleMinLines = 1,
  wrapperClassName = "text-sm text-slate-500",
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const editable = !readOnly && typeof onChange === "function";
  const descriptionText = useMemo(() => {
    const text = String(value || "").trim();
    return text || "-";
  }, [value]);

  const canToggle = useMemo(() => {
    const lineCount = descriptionText.split("\n").length;
    return descriptionText.length > toggleMinChars || lineCount > toggleMinLines;
  }, [descriptionText, toggleMinChars, toggleMinLines]);

  return (
    <div className={wrapperClassName}>
      <div className="flex items-center justify-between">
        <span>{label}</span>
        <div className="flex items-center gap-2">
          {editable && isEditing ? (
            <Button type="link" className="px-0" onClick={() => setIsEditing(false)}>
              {t("mcpTools.detail.descriptionEditDone")}
            </Button>
          ) : null}
          {canToggle ? (
            <button
              type="button"
              className="text-slate-500 transition hover:text-slate-700"
              aria-label={expanded ? t("mcpTools.detail.descriptionCollapse") : t("mcpTools.detail.descriptionExpand")}
              onClick={() => setExpanded((prev) => !prev)}
            >
              {expanded ? "▾" : "▸"}
            </button>
          ) : null}
        </div>
      </div>

      {editable && isEditing ? (
        <>
          <Input.TextArea
            value={value || ""}
            onChange={(event) => onChange?.(event.target.value)}
            autoSize={{ minRows, maxRows }}
            className="mt-2 w-full rounded-2xl"
            placeholder={t("mcpTools.community.descriptionMarkdownPlaceholder")}
          />
          <p className="mt-2 text-[11px] text-slate-400">{t("mcpTools.community.descriptionMarkdownHint")}</p>
        </>
      ) : (
        <div
          role={editable ? "button" : undefined}
          tabIndex={editable ? 0 : undefined}
          className={`mt-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 ${editable ? "cursor-text" : ""}`}
          onClick={editable ? () => setIsEditing(true) : undefined}
          onKeyDown={
            editable
              ? (event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setIsEditing(true);
                  }
                }
              : undefined
          }
        >
          <div
            className={
              expanded
                ? "max-h-[600px] overflow-auto transition-[max-height] duration-300 ease-in-out"
                : `max-h-12 overflow-hidden transition-[max-height] duration-300 ease-in-out`
            }
          >
            <MarkdownRenderer
              content={descriptionText}
              className="text-sm text-slate-700"
              enableMultimodal={false}
              showDiagramToggle={false}
            />
          </div>
          {editable ? <p className="mt-2 text-[11px] text-slate-400">{t("mcpTools.detail.descriptionClickToEdit")}</p> : null}
        </div>
      )}
    </div>
  );
}
