import { Input, Tag } from "antd";
import { useTranslation } from "react-i18next";

interface TagEditorProps {
  /** Optional heading shown above the tag list. */
  title?: string;
  tags: string[];
  tagInput: string;
  onTagInputChange: (value: string) => void;
  onAddTag: () => void;
  onRemoveTag: (index: number) => void;
  /**
   * i18n key used for the remove-button `aria-label`. Defaults to the key used
   * by the add-service flows; the detail flow overrides this so the label
   * matches the surrounding copy.
   */
  removeAriaKey?: string;
  placeholderKey?: string;
}

/**
 * Reusable tag editor: renders the current tag chips (each with a little
 * remove cross) plus an inline input that commits on Enter/blur. Every MCP
 * form that accepts tags uses this component so they all behave identically.
 */
export default function TagEditor({
  title,
  tags,
  tagInput,
  onTagInputChange,
  onAddTag,
  onRemoveTag,
  removeAriaKey = "mcpTools.addModal.removeTagAria",
  placeholderKey = "mcpTools.addModal.tagInputPlaceholder",
}: TagEditorProps) {
  const { t } = useTranslation("common");
  return (
    <div>
      {title ? (
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {title}
        </p>
      ) : null}
      <div className={`${title ? "mt-2 " : ""}flex flex-wrap gap-2`}>
        {tags.map((tag, index) => (
          <span key={`${tag}-${index}`} className="relative inline-flex">
            <Tag className="rounded-full px-3 py-1 m-0 leading-none">{tag}</Tag>
            <button
              type="button"
              onClick={() => onRemoveTag(index)}
              className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
              aria-label={t(removeAriaKey, { tag })}
            >
              x
            </button>
          </span>
        ))}
        <Input
          size="small"
          value={tagInput}
          onChange={(event) => onTagInputChange(event.target.value)}
          onPressEnter={onAddTag}
          onBlur={onAddTag}
          placeholder={t(placeholderKey)}
          className="w-40 rounded-full"
        />
      </div>
    </div>
  );
}
