// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
const chineseUnits = [
  [BigInt(10_000), "万"],
  [BigInt(100_000_000), "亿"],
  [BigInt(1_000_000_000_000), "万亿"],
] as const;
const englishUnits = [
  [BigInt(1_000), "K"],
  [BigInt(1_000_000), "M"],
  [BigInt(1_000_000_000), "B"],
  [BigInt(1_000_000_000_000), "T"],
] as const;
const hundred = BigInt(100);

export function formatCompactMonitoringTokens(
  value: string | null,
  language: string
): string {
  if (value === null) return "—";
  const number = new Intl.NumberFormat(language);
  const count = BigInt(value);
  const units = /^zh(?:-|$)/i.test(language) ? chineseUnits : englishUnits;
  let index = units.findLastIndex(([base]) => count >= base);
  if (index < 0) return number.format(count);

  const round = (base: bigint) => (count * hundred + base / BigInt(2)) / base;
  let scaled = round(units[index][0]);
  const next = units[index + 1];
  if (next && scaled * units[index][0] >= next[0] * hundred) {
    index += 1;
    scaled = round(next[0]);
  }
  const fraction = scaled % hundred;
  const decimal =
    number.formatToParts(0.1).find((part) => part.type === "decimal")?.value ??
    ".";
  const fractionText = fraction
    ? decimal + fraction.toString().padStart(2, "0").replace(/0$/, "")
    : "";
  return `${number.format(scaled / hundred)}${fractionText} ${units[index][1]}`;
}
