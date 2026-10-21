import type { Episode } from "./types.ts";

export const tankAgents = [
  { name: "Clawdius", role: "Market analyst", key: "analyst" },
  { name: "Pinch", role: "Risk manager", key: "risk" },
  { name: "Ledger", role: "Capital & execution", key: "banker" },
] as const;

export function tankPhase(episode: Episode | undefined, available: boolean) {
  if (!available) return "offline";
  if (!episode) return "idle";
  if (episode.status === "rejected" || Object.values(episode.reviews).some(r => r?.verdict === "reject")) return "vetoed";
  if (["needs_review", "needs_reconciliation", "needs_protection", "emergency"].includes(episode.status)) return "attention";
  if (["analyzing", "risk_check", "capital_check", "queued"].includes(episode.status)) return "reviewing";
  if (["approved", "staged"].includes(episode.status)) return "approved";
  if (episode.status === "submitting") return "submitting";
  if (["protected", "filled"].includes(episode.status)) return "open";
  if (["closing", "closing_cleanup"].includes(episode.status)) return "closing";
  if (episode.status === "closed") return "closed";
  return "idle";
}

// Display-only movement between two observed balances, never an accounting input.
// Use fixed-point integers so equal decimal observations do not produce phantom changes.
export function equityDelta(previous: string | null, next: string | null): string | null {
  const parse = (v: string | null) => {
    if (v === null || !/^-?\d+(\.\d+)?$/.test(v)) return null;
    const negative = v.startsWith("-");
    const [whole, fraction = ""] = v.replace("-", "").split(".");
    return { digits: (negative ? -1n : 1n) * BigInt(whole + fraction), scale: fraction.length };
  };
  const a = parse(previous), b = parse(next);
  if (!a || !b) return null;
  const scale = Math.max(a.scale, b.scale, 2);
  const difference = b.digits * 10n ** BigInt(scale - b.scale) - a.digits * 10n ** BigInt(scale - a.scale);
  const cents = difference / 10n ** BigInt(scale - 2);
  if (cents === 0n) return null;
  const magnitude = (cents < 0n ? -cents : cents).toString().padStart(3, "0");
  return `${cents < 0n ? "−" : "+"}$${magnitude.slice(0, -2)}.${magnitude.slice(-2)}`;
}
