import { Table, type TableProps } from "antd";

import { cn } from "@/lib/utils";

const standardTableStyles =
  "text-[14px] text-[#191919] ![letter-spacing:0px] " +
  "[&_.ant-table]:!bg-white " +
  "[&_.ant-table-cell]:!text-[14px] [&_.ant-table-cell]:!text-[#191919] [&_.ant-table-cell]:![letter-spacing:0px] " +
  "[&_.ant-table-thead>tr>th]:!h-10 [&_.ant-table-thead>tr>th]:!bg-[#f3f3f3] [&_.ant-table-thead>tr>th]:!py-0 [&_.ant-table-thead>tr>th]:!text-[#191919] [&_.ant-table-thead>tr>th]:!border-b [&_.ant-table-thead>tr>th]:!border-solid [&_.ant-table-thead>tr>th]:!border-b-[#f0f0f0] " +
  "[&_.ant-table-thead>tr>th:not(:last-child):not([colspan])::before]:!top-1/2 [&_.ant-table-thead>tr>th:not(:last-child):not([colspan])::before]:![transform:translateY(-50%)] [&_.ant-table-thead>tr>th:not(:last-child):not([colspan])::before]:!h-[14px] [&_.ant-table-thead>tr>th:not(:last-child):not([colspan])::before]:!bg-[#c9c9c9] " +
  "[&_.ant-table-tbody>tr>td]:!h-10 [&_.ant-table-tbody>tr>td]:!bg-white [&_.ant-table-tbody>tr>td]:!py-0 [&_.ant-table-tbody>tr>td]:!border-b [&_.ant-table-tbody>tr>td]:!border-solid [&_.ant-table-tbody>tr>td]:!border-b-[#f0f0f0]";

/**
 * Shared Ant Design table wrapper. Keep the TableProps API pass-through compatible.
 */
export function StandardTable<
  RecordType extends object = Record<string, unknown>,
>({ className, ...props }: TableProps<RecordType>) {
  return (
    <Table<RecordType>
      {...props}
      className={cn("nexent-standard-table", standardTableStyles, className)}
    />
  );
}
