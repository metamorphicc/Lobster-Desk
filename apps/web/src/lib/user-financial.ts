/** Explicit financial signing contracts. No provider calls in validators. */
import { typed, validateLocalIntent, validateExecutionProfile, type ExecutionProfile, type TypedData } from "./user-consent.ts";
import { AUTH_ORIGIN } from "./wallet-auth.ts";

export type FinancialKind = "agent" | "builder" | "revoke_builder" | "trade";
export type BoundPlan = { id: string; plan_hash: string; episode_id: string; expires_at: string };
export type FinancialJob = { id: string; owner: string; kind: FinancialKind; status: string; network: "testnet" | "mainnet";
  scope: "testnet-financial-consent-v1" | "mainnet-financial-consent-v1"; nonce: number; expires_ms: number; expired: boolean; proof: null;
  wallet_signing_enabled: true; submission_from_api: false; typed_data: TypedData;
  action?: Record<string, unknown>; plan_id?: string; plan_hash?: string; episode_id?: string; profile_hash: string };
export type FinancialContext = { schema: "lobster-user-financial-context-v1"; owner: string; network: "testnet" | "mainnet";
  enabled: boolean; profile: ExecutionProfile | null; jobs: FinancialJob[]; submission_from_api: false;
  execution: null | { trades: { id: string; status: string; reason: string; filled_quantity: string; protected_quantity: string }[] } };
function check(value: unknown): asserts value { if (!value) throw new Error("Financial payload does not match the reviewed testnet wallet, permission or plan."); }
function object(value: unknown): Record<string, unknown> { check(value && typeof value === "object" && !Array.isArray(value)); return value as Record<string, unknown>; }
function integer(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }

export function validateFinancialContext(value: unknown, owner: string, network: "testnet" | "mainnet" = "testnet"): FinancialContext {
  const data = object(value);
  check(data.schema === "lobster-user-financial-context-v1" && data.owner === owner && data.network === network && typeof data.enabled === "boolean" && data.submission_from_api === false);
  if (data.profile !== null) validateExecutionProfile(data.profile, owner, network);
  check(Array.isArray(data.jobs) && data.jobs.length <= 30);
  for (const value of data.jobs) { const job = object(value); check(job.owner === owner && job.proof === null && job.network === network && typeof job.status === "string"); }
  if (data.execution !== null) { const execution = object(data.execution); check(Array.isArray(execution.trades) && execution.trades.length <= 20); }
  return value as FinancialContext;
}

export function validateFinancialJob(value: unknown, profile: ExecutionProfile, kind: FinancialKind, origin: string,
  chainId: string, plan?: BoundPlan, now = Date.now(), network: "testnet" | "mainnet" = "testnet"): FinancialJob {
  check(origin === AUTH_ORIGIN && /^0x[0-9a-f]+$/i.test(chainId) && BigInt(chainId) === (network === "testnet" ? 421614n : 42161n));
  validateExecutionProfile(profile, profile.address, network);
  const data = object(value);
  check(data.owner === profile.address && data.kind === kind && data.network === network && data.scope === `${network}-financial-consent-v1`
    && data.status === "unsigned" && data.proof === null && data.wallet_signing_enabled === true && data.submission_from_api === false && data.expired === false);
  check(typeof data.id === "string" && /^[a-f0-9]{32}$/.test(data.id) && integer(data.nonce) && integer(data.expires_ms)
    && data.nonce >= now - 30000 && data.nonce <= now + 1000 && data.expires_ms > now && data.expires_ms <= now + 32000);
  if (kind === "trade") {
    check(plan);
    const actual = object(data.typed_data), domain = object(actual.domain);
    check(domain.name === "Lobster Desk Execution Consent");
    // Validate the original network/domain/type before a structural-only check.
    // The normalized copy is never returned or signed; the wallet signs `value`.
    const primary = network === "testnet" ? "TestnetTradeIntent" : "MainnetTradeIntent";
    const types = object(actual.types);
    check(domain.chainId === (network === "testnet" ? 421614 : 42161) && actual.primaryType === primary
      && Object.keys(types).length === 2 && "EIP712Domain" in types && primary in types);
    validateLocalIntent({ ...data, address: profile.address, wallet_signing_enabled: false, exchange_submission_enabled: false,
      scope: "local-testnet-trade-intent", typed_data: { ...actual, primaryType: "TestnetTradeIntent",
        types: { EIP712Domain: types.EIP712Domain, TestnetTradeIntent: types[primary] },
        domain: { ...domain, chainId: 421614, name: "Lobster Desk Local Intent" } } }, { ...profile, network: "testnet" }, plan, now);
  } else {
    check(data.plan_id === null);
    const agent = kind === "agent", action = object(data.action);
    const fields = [{ name: "hyperliquidChain", type: "string" }, ...(agent ? [{ name: "agentAddress", type: "address" }, { name: "agentName", type: "string" }] :
      [{ name: "maxFeeRate", type: "string" }, { name: "builder", type: "address" }]), { name: "nonce", type: "uint64" }];
    const primary = "HyperliquidTransaction:" + (agent ? "ApproveAgent" : "ApproveBuilderFee");
    const dataTyped = typed(data.typed_data, "HyperliquidSignTransaction", primary, fields, network);
    const expected: Record<string, unknown> = { type: agent ? "approveAgent" : "approveBuilderFee", hyperliquidChain: network === "testnet" ? "Testnet" : "Mainnet", signatureChainId: network === "testnet" ? "0x66eee" : "0xa4b1", nonce: data.nonce };
    if (agent) Object.assign(expected, { agentAddress: profile.agent, agentName: "Lobster Desk " + network });
    else Object.assign(expected, { builder: profile.builder, maxFeeRate: kind === "revoke_builder" ? "0%" : `${profile.fee_tenths_bps / 1000}%` });
    for (const candidate of [action, dataTyped.message]) {
      check(Object.keys(candidate).length === Object.keys(expected).length && Object.entries(expected).every(([key, val]) => candidate[key] === val));
    }
  }
  return value as FinancialJob;
}
