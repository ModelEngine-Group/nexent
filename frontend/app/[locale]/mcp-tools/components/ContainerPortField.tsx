import { Button, InputNumber } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useContainerPortAvailability } from "@/hooks/mcpTools/useContainerPortAvailability";

interface ContainerPortFieldProps {
  scope: string;
  enabled?: boolean;
  containerPort: number | undefined;
  setContainerPort: (value: number | undefined) => void;
}

export default function ContainerPortField({
  scope,
  enabled = true,
  containerPort,
  setContainerPort,
}: ContainerPortFieldProps) {
  const { t } = useTranslation("common");
  const { portCheckLoading, portAvailable, suggesting, suggestPort } =
    useContainerPortAvailability({
      scope,
      enabled,
      containerPort,
      setContainerPort,
    });

  return (
    <label className="block text-sm text-slate-500">
      {t("mcpTools.addModal.containerPort")}
      <div className="mt-2 flex gap-2">
        <InputNumber
          value={containerPort}
          onChange={(value) =>
            setContainerPort(value === null ? undefined : value)
          }
          min={1}
          max={65535}
          controls={false}
          className="w-full"
          placeholder={t("mcpTools.addModal.containerPortPlaceholder")}
        />
        <Button
          onClick={suggestPort}
          loading={suggesting}
          disabled={portCheckLoading || suggesting}
          className="rounded-full"
        >
          {t("mcpTools.addModal.suggestPort")}
        </Button>
      </div>
      {containerPort && portCheckLoading ? (
        <p className="mt-2 inline-flex items-center gap-2 text-xs text-slate-500">
          <LoadingOutlined className="animate-spin" />
          {t("mcpTools.addModal.portChecking")}...
        </p>
      ) : containerPort ? (
        <p
          className={`mt-2 text-xs ${portAvailable ? "text-emerald-600" : "text-rose-600"}`}
        >
          {portAvailable
            ? t("mcpTools.addModal.portAvailable", { port: containerPort })
            : t("mcpTools.addModal.portOccupied", { port: containerPort })}
        </p>
      ) : null}
    </label>
  );
}
