export const DEFAULT_AGENT_AVATAR_COLORS = [
  ["#ffbe59", "#ec71c5"],
  ["#fa91cc", "#875af1"],
  ["#9986fb", "#5acbe3"],
  ["#59c4f4", "#63d68d"],
];

// Outlined HarmonyOS Sans SC bold n, italicized and centered in a 100x100 box.
// Font attribution and license: public/fonts/harmonyos-sans-sc/LICENSE.txt.
export const DEFAULT_AGENT_AVATAR_GLYPH_PATH =
  "M69.224 46.815 64.787 69H54.84L58.633 50.036Q60.665 39.874 53.938 39.874Q50.36 39.874 47.626 42.629Q44.893 45.384 43.891 50.394L40.169 69H30.222L37.636 31.93H46.367Q45.852 36.296 45.823 37.87Q50.775 31 59.076 31Q65.231 31 68 35.043Q70.77 39.087 69.224 46.815Z";

export function DefaultAgentAvatar({
  size = 72,
  colors = DEFAULT_AGENT_AVATAR_COLORS[0],
}: {
  size?: number;
  colors?: string[];
}) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center rounded-full"
      style={{
        width: size,
        height: size,
        lineHeight: 1,
        background: `linear-gradient(135deg, ${colors.join(",")})`,
      }}
    >
      <svg
        viewBox="0 0 100 100"
        width={size}
        height={size}
        style={{ display: "block", flexShrink: 0 }}
      >
        <path d={DEFAULT_AGENT_AVATAR_GLYPH_PATH} fill="white" />
      </svg>
    </span>
  );
}
