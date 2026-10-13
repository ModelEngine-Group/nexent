// Coordinates and colors come from OCTO Version 27's conversation welcome screen.
const glowLayers = [
  {
    left: 467.06,
    top: 176.95,
    width: 758.87,
    height: 436.85,
    color: "#7A66FF",
  },
  { left: 0, top: 145, width: 682.3, height: 437.22, color: "#66EBFF" },
  { left: 341.87, top: 0, width: 825.34, height: 436.85, color: "#669FFF" },
];

export function NewChatWelcomeBackdrop() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 overflow-hidden"
    >
      <div
        className="absolute left-1/2 h-[613.81px] w-[1225.93px] -translate-x-1/2 opacity-[0.61]"
        style={{
          top: "calc(min(30.5556cqh, max(32px, 100cqh - 694px)) - 132.9px)",
        }}
      >
        {glowLayers.map(({ color, ...bounds }) => (
          <div
            key={color}
            className="absolute rounded-[426.67px] opacity-10"
            style={{
              ...bounds,
              background: `radial-gradient(ellipse closest-side at 50% 50%, ${color} 0%, ${color}00 100%)`,
            }}
          />
        ))}
      </div>
    </div>
  );
}
