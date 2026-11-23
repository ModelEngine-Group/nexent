"use client";

import { ConfigProvider, DatePicker } from "antd";
import type { DatePickerProps } from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import "dayjs/locale/zh-cn";

interface AutomationDateTimePickerProps extends DatePickerProps {
  language: string;
}

export default function AutomationDateTimePicker({
  language,
  className,
  ...props
}: AutomationDateTimePickerProps) {
  return (
    <ConfigProvider locale={language.startsWith("zh") ? zhCN : enUS}>
      <DatePicker
        {...props}
        allowClear={false}
        className={`automation-date-time-picker w-full ${className || ""}`}
        classNames={{
          popup: { root: "automation-date-time-picker-popup" },
        }}
        format="YYYY/MM/DD HH:mm"
        inputReadOnly
        placement="bottomLeft"
        showNow={false}
        showTime={{ format: "HH:mm" }}
      />
    </ConfigProvider>
  );
}
