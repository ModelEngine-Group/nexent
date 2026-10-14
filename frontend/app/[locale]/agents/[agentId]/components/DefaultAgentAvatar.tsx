export const DEFAULT_AGENT_AVATAR_COLORS = [
  ["#ffb746", "#e06edc", "#b386ee"],
  ["#ff71c6", "#b06cf2", "#55bcd9"],
  ["#9b68fb", "#6b96f3", "#6fe4a9"],
  ["#4ccafa", "#54d5d3", "#8bdf51"],
];

/** Shared vector artwork for previews and the uploaded default avatar. */
export function getDefaultAgentAvatarSvg(
  colors = DEFAULT_AGENT_AVATAR_COLORS[0]
) {
  const [top, middle, bottom = middle] = colors;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
    <defs>
      <linearGradient id="base" x1=".2" y1=".1" x2=".75" y2="1"><stop stop-color="${top}"/><stop offset=".55" stop-color="${middle}"/><stop offset="1" stop-color="${bottom}"/></linearGradient>
      <radialGradient id="warm" cx=".36" cy=".38" r=".65"><stop stop-color="${top}" stop-opacity=".95"/><stop offset="1" stop-color="${top}" stop-opacity="0"/></radialGradient>
      <radialGradient id="glass" cx=".4" cy=".32" r=".68"><stop offset=".5" stop-color="white" stop-opacity="0"/><stop offset=".88" stop-color="white" stop-opacity=".12"/><stop offset="1" stop-color="white" stop-opacity=".85"/></radialGradient>
      <filter id="soft"><feGaussianBlur stdDeviation="3"/></filter>
      <filter id="glow"><feGaussianBlur stdDeviation="2"/></filter>
    </defs>
    <g filter="url(#soft)"><circle cx="100" cy="100" r="86" fill="url(#base)"/><circle cx="100" cy="100" r="86" fill="url(#warm)"/><circle cx="100" cy="100" r="86" fill="url(#glass)"/></g>
    <g fill="none" stroke="white" stroke-width="12" stroke-linecap="round"><path d="M81 83 Q76 95 77 111" filter="url(#glow)"/><path d="M116 83 Q111 95 112 111" filter="url(#glow)"/><path d="M81 83 Q76 95 77 111"/><path d="M116 83 Q111 95 112 111"/></g>
  </svg>`;
}

export function DefaultAgentAvatar({
  size = 72,
  colors = DEFAULT_AGENT_AVATAR_COLORS[0],
}: {
  size?: number;
  colors?: string[];
}) {
  return (
    <img
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      className="inline-block shrink-0"
      src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(getDefaultAgentAvatarSvg(colors))}`}
    />
  );
}
