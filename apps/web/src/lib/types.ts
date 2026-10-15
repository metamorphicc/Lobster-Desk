export type Pitch = {
  author: string; symbol: "BTC"; direction: "long" | "short";
  entry: string; stop: string; target: string; leverage: number; thesis: string;
};
export type Review = {
  verdict: "approve" | "reject"; summary: string; evidence: string[];
  metadata: { provider: string; model: string; prompt_version: string; input_tokens: number; output_tokens: number };
};
export type Episode = {
  id: string; pitch: Pitch; status: string; created_at: string; expires_at: string;
  reason: string; reviews: Partial<Record<"analyst" | "risk", Review>>;
  risk: { quantity: string; notional: string; margin: string; planned_loss: string; reward_risk: string; approved: boolean; reasons: string[] } | null;
  approval_hash: string | null; position_id: string | null;
};
export type Position = {
  id: string; episode_id: string; direction: "long" | "short"; status: "open" | "closed";
  quantity: string; entry_price: string; exit_price: string | null; stop: string; target: string;
  entry_fee: string; exit_fee: string; net_pnl: string | null; margin: string;
  opened_at: string; closed_at: string | null; close_reason: string | null;
  market_source: string; entry_fill_id: string; exit_fill_id: string | null;
};
export type JournalEvent = {
  id: number; timestamp: string; actor: string; kind: string; message: string;
  episode_id: string | null; data: Record<string, unknown>;
};
export type Market = {
  source: "demo" | "hyperliquid"; price: string; timestamp: string;
  funding: string; open_interest: string; change_24h: string;
  candles: { time: number; open: string; high: string; low: string; close: string }[];
};
export type State = {
  market: Market | null; episodes: Episode[]; positions: Position[]; events: JournalEvent[]; last_event_id: number;
  account: { initial_capital: string; cash: string; equity: string | null; available_cash: string | null;
    net_realized_pnl: string; fees_paid: string; builder_revenue: string; paused: boolean; halt_reason: string | null;
    high_water_equity: string; day_start_equity: string; funding_included: boolean; created_at: string };
  policy: { risk_fraction: string; max_leverage: number; max_notional_fraction: string; version: string };
  service: { execution_mode: "paper"; market_source: string; agent_provider: string; model: string;
    data_stale: boolean; market_error: string | null; worker_error: string | null;
    operator_enabled: boolean; worker_enabled: boolean; user_trading_enabled: boolean; fee_collection_enabled: boolean };
};

export const money = (value: string | number | null | undefined, digits = 2) => value == null ? "—" :
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(value));
export const number = (value: string | number, digits = 2) => new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(Number(value));
export const signed = (value: string | number | null) => value == null ? "—" : `${Number(value) >= 0 ? "+" : "−"}${money(Math.abs(Number(value)))}`;
export const statusLabel = (status: string) => ({ queued: "In queue", analyzing: "Analyst reviewing", risk_check: "Risk reviewing", capital_check: "Banker reviewing",
  approved: "Entry pending", filled: "Position open", rejected: "Rejected", expired: "Expired", closed: "Closed" }[status] || status);

