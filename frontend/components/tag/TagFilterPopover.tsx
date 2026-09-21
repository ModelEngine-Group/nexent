"use client";

import { Button, Popover } from "antd";
import { Tag } from "lucide-react";
import { useTranslation } from "react-i18next";

import TagFilterControls from "@/components/tag/TagFilterControls";
import type { TagDefinition, TagResourcePredicate } from "@/types/tagManagement";

interface TagFilterPopoverProps {
  definitions: TagDefinition[];
  value: TagResourcePredicate[];
  onChange: (predicates: TagResourcePredicate[]) => void;
}

export default function TagFilterPopover({
  definitions,
  value,
  onChange,
}: TagFilterPopoverProps) {
  const { t } = useTranslation("common");

  return (
    <Popover
      trigger="click"
      placement="bottomRight"
      content={
        <div className="w-72">
          <TagFilterControls
            definitions={definitions}
            value={value}
            onChange={onChange}
          />
          {value.length > 0 ? (
            <button
              type="button"
              className="mt-2 text-xs text-blue-600 hover:underline"
              onClick={() => onChange([])}
            >
              {t("repository.tagFilter.clear")}
            </button>
          ) : null}
        </div>
      }
    >
      <Button
        type={value.length > 0 ? "primary" : "default"}
        className="h-11"
        icon={<Tag className="size-3.5" aria-hidden />}
      >
        {t("repository.tagFilter.button")}
      </Button>
    </Popover>
  );
}
