// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Button, Input, Popover } from "antd";
import { Search } from "lucide-react";
import { useId, useRef, useState } from "react";
import styles from "./monitoringColumnSearch.module.css";

export function MonitoringColumnSearch({
  search,
  placeholder,
  onSubmit,
  disabled = false,
}: {
  search: string;
  placeholder: string;
  onSubmit: (search: string) => void;
  disabled?: boolean;
}) {
  const triggerId = useId();
  const [open, setOpen] = useState(false);
  const restoreFocus = useRef(false);
  const visible = open && !disabled;

  return (
    <Popover
      trigger="click"
      placement="bottomLeft"
      open={visible}
      onOpenChange={setOpen}
      afterOpenChange={(nextOpen) => {
        if (!nextOpen && restoreFocus.current) {
          restoreFocus.current = false;
          document.getElementById(triggerId)?.focus({ preventScroll: true });
        }
      }}
      destroyOnHidden
      content={
        <Input.Search
          className={styles.input}
          autoFocus
          allowClear
          aria-label={placeholder}
          placeholder={placeholder}
          maxLength={100}
          defaultValue={search}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.stopPropagation();
              restoreFocus.current = true;
              setOpen(false);
            }
          }}
          onSearch={(value) => onSubmit(value.trim())}
        />
      }
    >
      <Button
        id={triggerId}
        color={search ? "primary" : "default"}
        variant="text"
        size="small"
        icon={<Search size={15} aria-hidden />}
        aria-label={placeholder}
        aria-expanded={visible}
        disabled={disabled}
      />
    </Popover>
  );
}
