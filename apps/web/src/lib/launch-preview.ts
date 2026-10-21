// Owner-requested illustrative fixtures. Never import into accounting or execution.
export function isLaunchPreview(url: string, internal = false, enabled = false): boolean {
  try {
    const location = new URL(url);
    return enabled && !internal && ["http:", "https:"].includes(location.protocol)
      && ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)
      && location.pathname === "/";
  } catch { return false; }
}

export type LaunchFigures = { source: "illustrative-launch-preview"; equity: string; profit: string;
  donations: { allocated: string; sent: string; outstanding: string } };

export function launchFigures(tick: number): LaunchFigures {
  if (!Number.isSafeInteger(tick) || tick < 0) throw new Error("Preview tick must be a nonnegative integer.");
  const results = [380n, 560n, -240n, 820n, 410n, -160n, 690n, 280n];
  const cycles = BigInt(Math.floor(tick / results.length));
  const profit = 28460n + cycles * results.reduce((sum, result) => sum + result, 0n)
    + results.slice(0, tick % results.length).reduce((sum, result) => sum + result, 0n);
  const allocated = profit / 2n, sent = 8000n;
  const format = (cents: bigint) => `${cents / 100n}.${(cents % 100n).toString().padStart(2, "0")}`;
  return { source: "illustrative-launch-preview", equity: format(100000n + profit - sent), profit: format(profit),
    donations: { allocated: format(allocated), sent: format(sent), outstanding: format(allocated - sent) } };
}
