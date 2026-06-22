import { Button, Pagination } from "antd";
import { useTranslation } from "react-i18next";

interface OffsetPaginationProps {
  mode: "offset";
  current: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}

interface CursorPaginationProps {
  mode: "cursor";
  page: number;
  resultCount: number;
  hasPrevPage: boolean;
  hasNextPage: boolean;
  onPrevPage: () => void;
  onNextPage: () => void;
}

type McpToolsPaginationProps = OffsetPaginationProps | CursorPaginationProps;

export default function McpToolsPagination(props: McpToolsPaginationProps) {
  const { t } = useTranslation("common");

  if (props.mode === "offset") {
    if (props.total <= props.pageSize) return null;
    return (
      <div className="flex justify-center rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <Pagination
          current={props.current}
          pageSize={props.pageSize}
          total={props.total}
          showSizeChanger={false}
          onChange={props.onChange}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <span className="text-sm text-slate-500">
        {t("mcpTools.community.pageResult", {
          page: props.page,
          count: props.resultCount,
        })}
      </span>
      <div className="flex justify-end gap-2">
        <Button onClick={props.onPrevPage} disabled={!props.hasPrevPage}>
          {t("mcpTools.community.prevPage")}
        </Button>
        <Button onClick={props.onNextPage} disabled={!props.hasNextPage}>
          {t("mcpTools.community.nextPage")}
        </Button>
      </div>
    </div>
  );
}
