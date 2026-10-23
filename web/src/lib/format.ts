const UNITS = ["B", "KiB", "MiB", "GiB", "TiB"];

export function bytes(value: number): string {
  let i = 0;
  while (value >= 1024 && i < UNITS.length - 1) {
    value /= 1024;
    i++;
  }
  return i === 0 ? `${Math.round(value)} B` : `${value.toFixed(value < 10 ? 2 : 1)} ${UNITS[i]}`;
}

export const num = (value: number) => value.toLocaleString("en-US");

export function compact(value: number): string {
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}

export function usd(value: number): string {
  if (value === 0) return "$0";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export const pct = (value: number, digits = 0) => `${(value * 100).toFixed(digits)}%`;
