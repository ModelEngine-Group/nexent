// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Table } from "antd";
import type { Key, ReactNode } from "react";
import { TrajectoryMarkdown } from "./TrajectoryMarkdown";

export function TrajectoryModelTable<Row extends { key: Key; label: string }>({
  rows,
  name,
  nested = false,
  fitContent = false,
  labelWidth = nested ? 96 : 128,
  renderValue,
}: {
  rows: Row[];
  name: string;
  nested?: boolean;
  fitContent?: boolean;
  labelWidth?: number;
  renderValue: (row: Row) => ReactNode;
}) {
  return (
    <Table
      aria-label={name}
      className={nested ? "trajectory-model-nested-table" : undefined}
      dataSource={rows}
      size="small"
      pagination={false}
      showHeader={false}
      rowHoverable={false}
      tableLayout={fitContent ? "auto" : "fixed"}
      bordered={nested}
      styles={{
        root: fitContent
          ? { inlineSize: "fit-content", maxInlineSize: "100%" }
          : undefined,
        body: { cell: { verticalAlign: "top", overflowWrap: "anywhere" } },
      }}
      columns={[
        {
          dataIndex: "label",
          rowScope: "row",
          width: labelWidth,
          onCell: () => ({
            style: {
              background: "transparent",
              color: "inherit",
              fontWeight: "normal",
              paddingInlineEnd: 8,
            },
          }),
        },
        { key: "value", render: (_value, row) => renderValue(row) },
      ]}
    />
  );
}

export function TrajectoryModelText({ text }: { text: string }) {
  return (
    <div className="markdown-body trajectory-model-content">
      <TrajectoryMarkdown text={text} />
    </div>
  );
}
