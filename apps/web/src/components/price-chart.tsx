"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import type { Episode, Market } from "@/lib/types";
import { aggregateCandles, type ChartInterval } from "@/lib/candles";

export function PriceChart({ market, episode }: { market: Market; episode?: Episode }) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const fitted = useRef(false);
  const [interval, setInterval] = useState<ChartInterval>(1);
  const bars = useMemo(() => {
    try { return aggregateCandles(market.candles, interval); } catch { return null; }
  }, [market.candles, interval]);

  useEffect(() => {
    if (!element.current) return;
    const tokens = getComputedStyle(document.documentElement);
    const color = (name: string) => {
      // Chart's canvas API accepts CSS colors resolved by the browser.
      const probe = document.createElement("span");
      probe.style.color = tokens.getPropertyValue(name).trim();
      document.body.append(probe);
      const resolved = getComputedStyle(probe).color;
      probe.remove();
      // Convert OKLCH to canvas-normalized sRGB; lightweight-charts parses rgb/hex.
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d")!;
      context.fillStyle = resolved;
      context.fillRect(0, 0, 1, 1);
      const [r, g, b] = context.getImageData(0, 0, 1, 1).data;
      return `rgb(${r}, ${g}, ${b})`;
    };
    const instance = createChart(element.current, {
      autoSize: true, height: 300,
      layout: { background: { type: ColorType.Solid, color: color("--color-panel") }, textColor: color("--color-muted"),
        fontFamily: tokens.getPropertyValue("--font-mono").trim(), fontSize: 10,
        attributionLogo: true },
      grid: { vertLines: { color: color("--color-chart-grid") }, horzLines: { color: color("--color-chart-grid") } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: .12, bottom: .12 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: color("--color-muted"), style: LineStyle.Dashed }, horzLine: { color: color("--color-muted") } },
      handleScroll: { vertTouchDrag: false },
    });
    const candles = instance.addSeries(CandlestickSeries, {
      upColor: color("--color-positive"), downColor: color("--color-negative"), borderVisible: false,
      wickUpColor: color("--color-positive"), wickDownColor: color("--color-negative"), priceLineVisible: false,
    });
    chart.current = instance;
    series.current = candles;
    return () => { instance.remove(); chart.current = null; series.current = null; fitted.current = false; };
  }, []);

  useEffect(() => {
    fitted.current = false;
  }, [interval, market.source]);

  useEffect(() => {
    if (!series.current) return;
    series.current.setData((bars || []).map(c => ({ time: c.time as UTCTimestamp,
      open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close) })));
    if (!fitted.current && bars?.length) { chart.current?.timeScale().fitContent(); fitted.current = true; }
  }, [bars]);

  useEffect(() => {
    if (!series.current || !episode) return;
    const instance = series.current;
    const lines = ([ ["entry", "--color-accent"], ["stop", "--color-negative"], ["target", "--color-positive"] ] as const).map(([key, token]) => {
      // Use a browser-resolved token through a temporary canvas for the library parser.
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d")!;
      context.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
      context.fillRect(0, 0, 1, 1);
      const [r, g, b] = context.getImageData(0, 0, 1, 1).data;
      return instance.createPriceLine({ price: Number(episode.pitch[key]), color: `rgb(${r},${g},${b})`,
        lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: key });
    });
    return () => {
      // React runs effect cleanups in declaration order. The chart may already
      // be disposed by the first effect when navigation unmounts this component.
      if (series.current === instance) lines.forEach(line => instance.removePriceLine(line));
    };
  }, [episode]);

  return <div className="chart-container">
    <div className="chart-toolbar"><div role="group" aria-label="Candle interval">{([1, 5, 15] as const).map(value =>
      <button key={value} className={interval === value ? "is-selected" : ""} type="button" disabled={!bars?.length} aria-pressed={interval === value} onClick={() => setInterval(value)}>{value}m</button>)}</div><span>BTC perpetual · UTC</span></div>
    {(!bars || !bars.length) && <p className="form-error" role="status">Candle history is unavailable. Waiting for the next market update.</p>}
    <div ref={element} className="price-chart" aria-label={`BTC ${interval}-minute candlestick chart in UTC. Drag to pan, scroll to zoom.`} role="img" />
  </div>;
}

