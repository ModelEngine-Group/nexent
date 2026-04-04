import { Button, InputNumber } from "antd";
import { LoadingOutlined } from "@ant-design/icons";

type ContainerPortFieldProps = {
  containerPort: number | undefined;
  containerPortCheckLoading: boolean;
  containerPortSuggesting: boolean;
  containerPortAvailable: boolean;
  setContainerPort: (value: number | undefined) => void;
  handleSuggestContainerPort: () => void;
  t: (key: string, params?: Record<string, unknown>) => string;
};

export default function ContainerPortField({
  containerPort,
  containerPortCheckLoading,
  containerPortSuggesting,
  containerPortAvailable,
  setContainerPort,
  handleSuggestContainerPort,
  t,
}: ContainerPortFieldProps) {
  return (
    <label className="block text-sm text-slate-500">
      {t("mcpTools.addModal.containerPort")}
      <div className="mt-2 flex gap-2">
        <InputNumber
          value={containerPort}
          onChange={(value) => setContainerPort(value === null ? undefined : value)}
          min={1}
          max={65535}
          controls={false}
          className="w-full"
          placeholder={t("mcpTools.addModal.containerPortPlaceholder")}
        />
        <Button
          onClick={handleSuggestContainerPort}
          loading={containerPortSuggesting}
          disabled={containerPortCheckLoading || containerPortSuggesting}
          className="rounded-full"
        >
          {t("mcpTools.addModal.suggestPort")}
        </Button>
      </div>
      {containerPort && containerPortCheckLoading ? (
        <p className="mt-2 inline-flex items-center gap-2 text-xs text-slate-500">
          <LoadingOutlined className="animate-spin" />
          {t("mcpTools.addModal.portChecking")}...
        </p>
      ) : containerPort ? (
        <p className={`mt-2 text-xs ${containerPortAvailable ? "text-emerald-600" : "text-rose-600"}`}>
          {containerPortAvailable
            ? t("mcpTools.addModal.portAvailable", { port: containerPort })
            : t("mcpTools.addModal.portOccupied", { port: containerPort })}
        </p>
      ) : null}
    </label>
  );
}
