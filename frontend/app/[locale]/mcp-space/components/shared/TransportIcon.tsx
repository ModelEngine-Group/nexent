import {
  ApiOutlined,
  CloudOutlined,
  CodeOutlined,
  ContainerOutlined,
  DatabaseOutlined,
  DesktopOutlined,
  GlobalOutlined,
  LinkOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { McpDeploymentType, McpTransportType } from "@/const/mcpTools";

interface TransportVisual {
  Icon: typeof LinkOutlined;
  className: string;
}

const DEPLOYMENT_VISUALS: Record<string, TransportVisual> = {
  [McpDeploymentType.REMOTE_LINK]: {
    Icon: LinkOutlined,
    className: "bg-blue-50 text-blue-600",
  },
  [McpDeploymentType.CONTAINER]: {
    Icon: ContainerOutlined,
    className: "bg-blue-50 text-blue-600",
  },
  [McpDeploymentType.API]: {
    Icon: ApiOutlined,
    className: "bg-blue-50 text-blue-600",
  },
  [McpDeploymentType.LOCAL_IMAGE]: {
    Icon: CloudOutlined,
    className: "bg-blue-50 text-blue-600",
  },
};

const ICON_POOL: Array<typeof LinkOutlined> = [
  LinkOutlined,
  GlobalOutlined,
  ThunderboltOutlined,
  RocketOutlined,
  DatabaseOutlined,
  CodeOutlined,
  DesktopOutlined,
  CloudOutlined,
  ApiOutlined,
  ContainerOutlined,
];

const COLOR_POOL: string[] = [
  "bg-blue-50 text-blue-600",
  "bg-sky-50 text-sky-600",
  "bg-indigo-50 text-indigo-600",
  "bg-blue-100 text-blue-700",
  "bg-sky-100 text-sky-700",
  "bg-indigo-100 text-indigo-700",
  "bg-blue-50 text-blue-600",
  "bg-sky-50 text-sky-600",
];

const DEFAULT_VISUAL: TransportVisual =
  DEPLOYMENT_VISUALS[McpDeploymentType.REMOTE_LINK];

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

interface TransportIconProps {
  transportType: string;
  deploymentType?: string;
  label?: string;
  className?: string;
  seed?: string;
}

export default function TransportIcon({
  transportType,
  deploymentType,
  label,
  className,
  seed,
}: TransportIconProps) {
  const baseVisual =
    (deploymentType && DEPLOYMENT_VISUALS[deploymentType]) ||
    DEFAULT_VISUAL;

  let Icon = baseVisual.Icon;
  let iconClassName = baseVisual.className;

  if (seed) {
    const seedHash = hashString(seed);
    Icon = ICON_POOL[seedHash % ICON_POOL.length];
    iconClassName = COLOR_POOL[seedHash % COLOR_POOL.length];
  }

  return (
    <span
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-base ${iconClassName}${
        className ? ` ${className}` : ""
      }`}
      aria-label={label}
      title={label}
    >
      <Icon aria-hidden />
    </span>
  );
}
