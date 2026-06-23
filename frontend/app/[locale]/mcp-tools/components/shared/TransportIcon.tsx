import {
  ApiOutlined,
  CloudOutlined,
  ContainerOutlined,
  LinkOutlined,
} from "@ant-design/icons";
import { McpDeploymentType, McpTransportType } from "@/const/mcpTools";

interface TransportVisual {
  Icon: typeof LinkOutlined;
  className: string;
}

const DEPLOYMENT_VISUALS: Record<string, TransportVisual> = {
  [McpDeploymentType.REMOTE_LINK]: {
    Icon: LinkOutlined,
    className: "bg-sky-50 text-sky-600",
  },
  [McpDeploymentType.CONTAINER]: {
    Icon: ContainerOutlined,
    className: "bg-violet-50 text-violet-600",
  },
  [McpDeploymentType.API]: {
    Icon: ApiOutlined,
    className: "bg-emerald-50 text-emerald-600",
  },
  [McpDeploymentType.LOCAL_IMAGE]: {
    Icon: CloudOutlined,
    className: "bg-amber-50 text-amber-600",
  },
};

const TRANSPORT_VISUALS: Record<string, TransportVisual> = {
  [McpTransportType.URL]: DEPLOYMENT_VISUALS[McpDeploymentType.REMOTE_LINK],
  [McpTransportType.CONTAINER]: DEPLOYMENT_VISUALS[McpDeploymentType.CONTAINER],
};

const DEFAULT_VISUAL: TransportVisual =
  DEPLOYMENT_VISUALS[McpDeploymentType.REMOTE_LINK];

interface TransportIconProps {
  transportType: string;
  deploymentType?: string;
  label?: string;
  className?: string;
}

export default function TransportIcon({
  transportType,
  deploymentType,
  label,
  className,
}: TransportIconProps) {
  const visual =
    (deploymentType && DEPLOYMENT_VISUALS[deploymentType]) ||
    TRANSPORT_VISUALS[transportType] ||
    DEFAULT_VISUAL;
  const Icon = visual.Icon;

  return (
    <span
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-base ${visual.className}${
        className ? ` ${className}` : ""
      }`}
      aria-label={label}
      title={label}
    >
      <Icon aria-hidden />
    </span>
  );
}
