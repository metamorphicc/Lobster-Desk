import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import test from "node:test";
import { validateFinancialJob, validateFinancialContext } from "../src/lib/user-financial.ts";
import { WalletSession } from "../src/lib/wallet.ts";
import { AUTH_ORIGIN, AUTH_STATEMENT, validateAuthChallenge } from "../src/lib/wallet-auth.ts";

const fixture = JSON.parse(fs.readFileSync(new URL("./fixtures/user-mainnet.json", import.meta.url), "utf8"));
const profile = fixture.profile, owner = profile.address, signature = "0x" + "1".repeat(130);
function live(kind = "builder") {
  const job = structuredClone(fixture.jobs[kind]), now = Date.now();
  job.nonce = now; job.expires_ms = now + 30000; job.typed_data.message.nonce = now;
  if (job.action) job.action.nonce = now;
  else job.typed_data.message.validUntil = job.expires_ms;
  return job;
}
class Provider extends EventEmitter {
  calls = []; accounts = [owner]; chainId = "0xa4b1";
  async request(args) {
    this.calls.push(args);
    if (["eth_requestAccounts", "eth_accounts"].includes(args.method)) return this.accounts;
    if (args.method === "eth_chainId") return this.chainId;
    if (["eth_signTypedData_v4", "personal_sign"].includes(args.method)) return signature;
    throw new Error("Unexpected wallet request");
  }
}

test("Python/SDK mainnet contracts validate only against explicit mainnet expectation", () => {
  assert.equal(validateFinancialContext(fixture.context, owner, "mainnet").network, "mainnet");
  assert.throws(() => validateFinancialContext(fixture.context, owner));
  for (const [kind, job] of Object.entries(fixture.jobs)) {
    assert.equal(validateFinancialJob(job, profile, kind, AUTH_ORIGIN, "0xa4b1", fixture.plan, job.nonce, "mainnet"), job);
    assert.throws(() => validateFinancialJob(job, profile, kind, AUTH_ORIGIN, "0xa4b1", fixture.plan, job.nonce));
  }
});
test("only explicit mainnet signing sends the original exact mainnet SDK payload", async () => {
  const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
  const job = live();
  await assert.rejects(session.signFinancial(job, profile, "builder", AUTH_ORIGIN));
  assert.equal(provider.calls.some(call => /sign/i.test(call.method)), false);
  assert.equal(await session.signMainnetFinancial(job, profile, "builder", AUTH_ORIGIN), signature);
  const actual = provider.calls.find(call => call.method === "eth_signTypedData_v4");
  assert.deepEqual(actual.params, [owner, JSON.stringify(job.typed_data)]);
  assert.equal(JSON.parse(actual.params[1]).message.hyperliquidChain, "Mainnet");
});
test("mainnet trade structural checks never substitute a testnet domain in the signed payload", async () => {
  const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
  const job = live("trade"), plan = { ...fixture.plan, expires_at: new Date(job.expires_ms).toISOString() };
  await session.signMainnetFinancial(job, profile, "trade", AUTH_ORIGIN, plan);
  const typed = JSON.parse(provider.calls.find(call => call.method === "eth_signTypedData_v4").params[1]);
  assert.deepEqual(typed, job.typed_data);
  assert.equal(typed.primaryType, "MainnetTradeIntent"); assert.equal(typed.domain.chainId, 42161);
  for (const altered of [
    { ...job, typed_data: { ...job.typed_data, domain: { ...job.typed_data.domain, chainId: 421614 } } },
    { ...job, typed_data: { ...job.typed_data, primaryType: "TestnetTradeIntent" } },
    { ...job, scope: "testnet-financial-consent-v1" },
  ]) await assert.rejects(session.signMainnetFinancial(altered, profile, "trade", AUTH_ORIGIN, plan));
  assert.equal(provider.calls.filter(call => call.method === "eth_signTypedData_v4").length, 1);
});
for (const field of ["builder", "maxFeeRate", "hyperliquidChain", "signatureChainId"]) {
  test(`mainnet permission refuses altered ${field} before a wallet prompt`, async () => {
    const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
    const job = live(); job.action[field] = "changed"; job.typed_data.message = structuredClone(job.action);
    await assert.rejects(session.signMainnetFinancial(job, profile, "builder", AUTH_ORIGIN));
    assert.equal(provider.calls.some(call => /sign/i.test(call.method)), false);
  });
}
test("mainnet sign-in has an independent statement/chain/scope and explicit wallet method", async () => {
  const issued_at = new Date().toISOString(), expires_at = new Date(Date.parse(issued_at) + 120000).toISOString();
  const nonce = "1".repeat(32), challenge_id = "2".repeat(32);
  const c = { challenge_id, address: owner, origin: AUTH_ORIGIN, chain_id: 42161, nonce, issued_at, expires_at,
    scope: "mainnet:preview", order_submission_enabled: false, fee_collection_enabled: false,
    message: `${AUTH_ORIGIN} wants you to sign in with your Ethereum account:\n${owner}\n\n${AUTH_STATEMENT.replace("testnet", "mainnet")}\n\nURI: ${AUTH_ORIGIN}\nVersion: 1\nChain ID: 42161\nNonce: ${nonce}\nIssued At: ${issued_at}\nExpiration Time: ${expires_at}\nRequest ID: ${challenge_id}` };
  assert.throws(() => validateAuthChallenge(c, owner, AUTH_ORIGIN, "0xa4b1"));
  const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
  await assert.rejects(session.signAuthentication(c, AUTH_ORIGIN));
  assert.equal(await session.signMainnetAuthentication(c, AUTH_ORIGIN), signature);
  assert.equal(provider.calls.filter(call => call.method === "personal_sign").length, 1);
});
for (const event of ["accountsChanged", "chainChanged", "disconnect"]) {
  test(`mainnet ${event} during a prompt discards the financial proof`, async () => {
    const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
    let entered, resolve;
    const started = new Promise(r => { entered = r; }); const original = provider.request.bind(provider);
    provider.request = args => args.method === "eth_signTypedData_v4" ? (entered(), new Promise(r => { resolve = r; })) : original(args);
    const pending = session.signMainnetFinancial(live(), profile, "builder", AUTH_ORIGIN);
    await started; provider.emit(event, []); resolve(signature);
    await assert.rejects(pending, /Wallet changed/);
  });
}
