import { ContainerOutlined, LinkOutlined } from "@ant-design/icons";
import { McpTransportType } from "@/const/mcpTools";

interface TransportVisual {
  Icon: typeof LinkOutlined;
  className: string;
}

/**
 * Visual mapping for transport-type icons rendered on MCP cards.
 * Only URL and CONTAINER are mapped explicitly; legacy HTTP/SSE values
 * fall back to the URL visual.
 */
const TRANSPORT_VISUALS: Record<string, TransportVisual> = {
  [McpTransportType.URL]: {
    Icon: LinkOutlined,
    className: "bg-sky-50 text-sky-600",
  },
  [McpTransportType.CONTAINER]: {
    Icon: ContainerOutlined,
    className: "bg-violet-50 text-violet-600",
  },
};

const DEFAULT_VISUAL: TransportVisual = {
  Icon: LinkOutlined,
  className: "bg-sky-50 text-sky-600",
};

interface TransportIconProps {
  transportType: string;
  label?: string;
  className?: string;
}

export default function TransportIcon({
  transportType,
  label,
  className,
}: TransportIconProps) {
  const visual = TRANSPORT_VISUALS[transportType] || DEFAULT_VISUAL;
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
