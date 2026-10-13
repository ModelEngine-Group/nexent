export const DEFAULT_AGENT_AVATAR_COLORS = [
  ["#ffbe59", "#ec71c5"],
  ["#fa91cc", "#875af1"],
  ["#9986fb", "#5acbe3"],
  ["#59c4f4", "#63d68d"],
];

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
      className="inline-flex shrink-0 items-center justify-center rounded-full font-bold italic text-white"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.65,
        lineHeight: 1,
        background: `linear-gradient(135deg, ${colors.join(",")})`,
      }}
    >
      n
    </span>
  );
}
