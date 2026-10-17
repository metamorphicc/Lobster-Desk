import type { Market } from "./types.ts";

export type ChartInterval = 1 | 5 | 15;
type Bar = Market["candles"][number];

/** Aggregate observed OHLC only. Never interpolate prices or fill missing minutes. */
export function aggregateCandles(input: Bar[], interval: ChartInterval): Bar[] {
  const minutes = new Map<number, Bar>();
  for (const c of input) {
    const [o, h, l, close] = [c.open, c.high, c.low, c.close].map(Number);
    if (!Number.isSafeInteger(c.time) || c.time % 60 || ![o, h, l, close].every(v => Number.isFinite(v) && v > 0)
      || l > Math.min(o, close) || h < Math.max(o, close)) throw new Error("Invalid candle history");
    if (minutes.has(c.time)) throw new Error("Duplicate candle timestamp");
    minutes.set(c.time, c);
  }
  const ordered = [...minutes.values()].sort((a, b) => a.time - b.time);
  if (interval === 1) return ordered;
  const groups = new Map<number, Bar[]>();
  for (const c of ordered) {
    const time = Math.floor(c.time / (interval * 60)) * interval * 60;
    if (!groups.has(time)) groups.set(time, []);
    groups.get(time)!.push(c);
  }
  const result: Bar[] = [];
  for (const [time, bars] of groups) {
    // Skip partial leading/gapped historical buckets. The final active bucket
    // may be shorter, but must start at its actual interval boundary.
    if (bars[0].time !== time || bars.some((c, i) => c.time !== time + i * 60)) continue;
    if (bars.length !== interval && bars.at(-1)!.time !== ordered.at(-1)!.time) continue;
    result.push({ time, open: bars[0].open, close: bars.at(-1)!.close,
      high: bars.reduce((a, b) => Number(a) > Number(b.high) ? a : b.high, bars[0].high),
      low: bars.reduce((a, b) => Number(a) < Number(b.low) ? a : b.low, bars[0].low) });
  }
  return result;
}
