/** Unsigned review contracts only. This module never calls a wallet/provider. */
export type ExecutionProfile = { address: string; agent: string; builder: string; fee_tenths_bps: number; network: "testnet" };
export type IntentSummary = { id: string; plan_id: string; plan_hash: string; status: "unsigned" | "verified_local" | "claimed_offline"; expires_ms: number; expired: boolean };
export type ExecutionContext = { schema: "lobster-user-execution-context-v1"; address: string; network: "testnet";
  profile: ExecutionProfile | null; intents: IntentSummary[]; wallet_signing_enabled: false; exchange_submission_enabled: false; signatures_accepted: false };
export type TypedData = { domain: Record<string, unknown>; primaryType: string; types: Record<string, { name: string; type: string }[]>; message: Record<string, unknown> };
export type LocalIntent = IntentSummary & { address: string; episode_id: string; nonce: number; profile_hash: string;
  typed_data: TypedData; proof: null; scope: "local-testnet-trade-intent"; wallet_signing_enabled: false; exchange_submission_enabled: false };
export type PermissionPlans = { address: string; network: "testnet"; wallet_signing_enabled: false; submitted: false;
  agent: { action: Record<string, unknown>; typed_data: TypedData }; builder: { action: Record<string, unknown>; typed_data: TypedData } };
const zero = "0x" + "0".repeat(40);
const domainFields = [{ name: "name", type: "string" }, { name: "version", type: "string" }, { name: "chainId", type: "uint256" }, { name: "verifyingContract", type: "address" }];
function check(value: unknown): asserts value { if (!value) throw new Error("Unsigned consent data did not match this wallet, plan or disabled scope."); }
function object(value: unknown): Record<string, unknown> { check(value && typeof value === "object" && !Array.isArray(value)); return value as Record<string, unknown>; }
function keys(value: Record<string, unknown>, expected: string[]) { check(Object.keys(value).length === expected.length && expected.every(key => key in value)); }
function address(value: unknown) { check(typeof value === "string" && /^0x[0-9a-f]{40}$/.test(value) && value !== zero); return value; }
function id(value: unknown) { check(typeof value === "string" && /^[a-f0-9]{32}$/.test(value)); }
function hash(value: unknown) { check(typeof value === "string" && /^[a-f0-9]{64}$/.test(value)); }
function integer(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
function profile(value: unknown, owner: string): ExecutionProfile {
  const p = object(value); check(address(p.address) === owner && p.network === "testnet");
  check(new Set([owner, address(p.agent), address(p.builder)]).size === 3 && integer(p.fee_tenths_bps) && p.fee_tenths_bps <= 100);
  return value as ExecutionProfile;
}
function typed(value: unknown, name: string, primary: string, fields: { name: string; type: string }[]): TypedData {
  const data = object(value), domain = object(data.domain), types = object(data.types); object(data.message);
  keys(data, ["domain", "types", "primaryType", "message"]); keys(domain, ["name", "version", "chainId", "verifyingContract"]);
  keys(types, [primary, "EIP712Domain"]);
  check(domain.name === name && domain.version === "1" && domain.chainId === 421614 && domain.verifyingContract === zero && data.primaryType === primary);
  check(JSON.stringify(types.EIP712Domain) === JSON.stringify(domainFields) && JSON.stringify(types[primary]) === JSON.stringify(fields));
  return value as TypedData;
}
function summary(value: unknown): IntentSummary {
  const data = object(value); id(data.id); id(data.plan_id); hash(data.plan_hash);
  check(["unsigned", "verified_local", "claimed_offline"].includes(String(data.status)) && integer(data.expires_ms) && typeof data.expired === "boolean");
  return value as IntentSummary;
}
export function validateExecutionContext(value: unknown, owner: string): ExecutionContext {
  const data = object(value); check(data.schema === "lobster-user-execution-context-v1" && data.address === owner && data.network === "testnet");
  check(data.wallet_signing_enabled === false && data.exchange_submission_enabled === false && data.signatures_accepted === false);
  if (data.profile !== null) profile(data.profile, owner);
  check(Array.isArray(data.intents) && data.intents.length <= 10); data.intents.forEach(summary);
  return value as ExecutionContext;
}
export function validateLocalIntent(value: unknown, p: ExecutionProfile, plan: { id: string; plan_hash: string; episode_id: string; expires_at: string }, now = Date.now()): LocalIntent {
  const data = object(value); summary(value); profile(p, p.address); hash(data.profile_hash);
  check(data.address === p.address && data.plan_id === plan.id && data.plan_hash === plan.plan_hash && data.episode_id === plan.episode_id && data.status === "unsigned");
  check(data.proof === null && data.scope === "local-testnet-trade-intent" && data.wallet_signing_enabled === false && data.exchange_submission_enabled === false && data.expired === false);
  check(integer(data.nonce) && integer(data.expires_ms) && data.nonce <= now + 1000 && data.nonce >= now - 30000
    && data.expires_ms > now && data.expires_ms <= now + 32000 && data.expires_ms <= Date.parse(plan.expires_at));
  const fields = [{ name: "owner", type: "address" }, { name: "planHash", type: "bytes32" }, { name: "agent", type: "address" },
    { name: "builder", type: "address" }, { name: "builderFeeTenthsBps", type: "uint256" }, { name: "nonce", type: "uint64" }, { name: "validUntil", type: "uint64" }];
  const dataTyped = typed(data.typed_data, "Lobster Desk Local Intent", "TestnetTradeIntent", fields), message = dataTyped.message;
  keys(message, fields.map(field => field.name));
  check(message.owner === p.address && message.planHash === "0x" + plan.plan_hash && message.agent === p.agent && message.builder === p.builder &&
    message.builderFeeTenthsBps === p.fee_tenths_bps && message.nonce === data.nonce && message.validUntil === data.expires_ms);
  return value as LocalIntent;
}
export function validatePermissionPlans(value: unknown, p: ExecutionProfile): PermissionPlans {
  const data = object(value); profile(p, p.address);
  check(data.address === p.address && data.network === "testnet" && data.wallet_signing_enabled === false && data.submitted === false);
  let previous = 0;
  for (const kind of ["agent", "builder"] as const) {
    const part = object(data[kind]), action = object(part.action), agent = kind === "agent";
    const fields = [{ name: "hyperliquidChain", type: "string" }, ...(agent ? [{ name: "agentAddress", type: "address" }, { name: "agentName", type: "string" }] :
      [{ name: "maxFeeRate", type: "string" }, { name: "builder", type: "address" }]), { name: "nonce", type: "uint64" }];
    const primary = "HyperliquidTransaction:" + (agent ? "ApproveAgent" : "ApproveBuilderFee");
    const dataTyped = typed(part.typed_data, "HyperliquidSignTransaction", primary, fields);
    keys(action, ["type", "signatureChainId", ...fields.map(field => field.name)]);
    check(action.type === (agent ? "approveAgent" : "approveBuilderFee") && action.signatureChainId === "0x66eee" && action.hyperliquidChain === "Testnet" && integer(action.nonce));
    check(Object.keys(dataTyped.message).length === Object.keys(action).length && Object.entries(action).every(([key, val]) => dataTyped.message[key] === val));
    if (agent) check(action.agentAddress === p.agent && action.agentName === "Lobster Desk testnet");
    else check(action.builder === p.builder && action.maxFeeRate === `${p.fee_tenths_bps / 1000}%` && action.nonce === previous + 1);
    previous = action.nonce;
  }
  return value as PermissionPlans;
}
