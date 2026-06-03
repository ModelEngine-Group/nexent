import { useEffect, useRef, useState } from "react";
import { Input, Tag } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { InputRef } from "antd";
import { useTranslation } from "react-i18next";

interface TagEditorProps {
  /** Optional heading shown above the tag list. */
  title?: string;
  tags: string[];
  /** Owned input value (when undefined, the editor manages it internally). */
  tagInput?: string;
  onTagInputChange?: (value: string) => void;
  onAddTag: (value?: string) => void;
  onRemoveTag: (index: number) => void;
  removeAriaKey?: string;
  placeholderKey?: string;
  /** Disable interactions while saving. */
  loading?: boolean;
}

/**
 * Reusable tag editor with default AntD Tag styles. Tags are added through a
 * "+" affordance that toggles an inline input, instead of an always-visible
 * input pill — this matches AntD's recommended pattern and keeps the row
 * tidy when no tags are present.
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
  loading = false,
}: TagEditorProps) {
  const { t } = useTranslation("common");
  const isControlled = tagInput !== undefined;
  const [internalValue, setInternalValue] = useState("");
  const value = isControlled ? (tagInput ?? "") : internalValue;
  const setValue = (next: string) => {
    if (isControlled) onTagInputChange?.(next);
    else setInternalValue(next);
  };

  const [editing, setEditing] = useState(false);
  const inputRef = useRef<InputRef>(null);
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const commit = () => {
    if (loading) return;
    const next = value.trim();
    if (next) onAddTag(next);
    setValue("");
    setEditing(false);
  };

  return (
    <div>
      {title ? (
        <p className="mb-1 block text-sm font-normal text-slate-500">
          {title}
        </p>
      ) : null}
      <div
        className={`flex flex-wrap items-center gap-2 ${loading ? "opacity-60 pointer-events-none" : ""}`}
      >
        {tags.map((tag, index) => (
          <Tag
            key={`${tag}-${index}`}
            closable={!loading}
            closeIcon
            onClose={(event) => {
              event.preventDefault();
              onRemoveTag(index);
            }}
            aria-label={t(removeAriaKey, { tag })}
            className="m-0"
          >
            {tag}
          </Tag>
        ))}
        {editing ? (
          <Input
            ref={inputRef}
            size="small"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onPressEnter={commit}
            onBlur={commit}
            placeholder={t(placeholderKey)}
            className="w-32"
          />
        ) : (
          <Tag
            onClick={() => !loading && setEditing(true)}
            className={`m-0 cursor-pointer border-dashed bg-transparent ${loading ? "" : ""}`}
          >
            <PlusOutlined /> {loading ? t("mcpTools.detail.saving") : t("common.add")}
          </Tag>
        )}
      </div>
    </div>
  );
}
