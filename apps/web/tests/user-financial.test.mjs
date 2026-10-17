import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import test from "node:test";
import { validateFinancialJob, validateFinancialContext } from "../src/lib/user-financial.ts";
import { WalletSession } from "../src/lib/wallet.ts";
import { AUTH_ORIGIN } from "../src/lib/wallet-auth.ts";

const fixture = JSON.parse(fs.readFileSync(new URL("./fixtures/user-financial.json", import.meta.url), "utf8"));
const profile = fixture.profile, owner = profile.address, signature = "0x" + "1".repeat(130);
function live(kind = "builder") {
  const job = structuredClone(fixture.jobs[kind]), now = Date.now();
  job.nonce = now; job.expires_ms = now + 30000; job.typed_data.message.nonce = now;
  if (job.action) job.action.nonce = now;
  else job.typed_data.message.validUntil = job.expires_ms;
  return job;
}
class Provider extends EventEmitter {
  calls = []; accounts = [owner]; chainId = "0x66eee";
  async request(args) {
    this.calls.push(args);
    if (["eth_requestAccounts", "eth_accounts"].includes(args.method)) return this.accounts;
    if (args.method === "eth_chainId") return this.chainId;
    if (args.method === "eth_signTypedData_v4") return signature;
    throw new Error("Unexpected financial wallet method");
  }
}
test("actual Python/SDK financial contracts validate without promoting local rehearsal proofs", () => {
  assert.equal(validateFinancialContext(fixture.context, owner).profile.agent, profile.agent);
  for (const [kind, job] of Object.entries(fixture.jobs)) {
    assert.equal(validateFinancialJob(job, profile, kind, AUTH_ORIGIN, "0x66eee", fixture.plan, job.nonce).kind, kind);
  }
  const trade = structuredClone(fixture.jobs.trade); trade.typed_data.domain.name = "Lobster Desk Local Intent";
  assert.throws(() => validateFinancialJob(trade, profile, "trade", AUTH_ORIGIN, "0x66eee", fixture.plan, trade.nonce));
});
test("only an explicit financial call prompts eth_signTypedData_v4 with the exact payload", async () => {
  const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
  assert.equal(provider.calls.some(call => /sign/i.test(call.method)), false);
  const job = live();
  assert.equal(await session.signFinancial(job, profile, "builder", AUTH_ORIGIN), signature);
  const request = provider.calls.find(call => call.method === "eth_signTypedData_v4");
  assert.deepEqual(request.params, [owner, JSON.stringify(job.typed_data)]);
  assert.equal(provider.calls.some(call => /sendTransaction|switchEthereumChain|personal_sign/.test(call.method)), false);
});
for (const field of ["builder", "maxFeeRate", "type", "hyperliquidChain", "signatureChainId", "nonce"]) {
  test(`widened permission ${field} never reaches the wallet`, async () => {
    const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
    const job = live(); job.action[field] = field === "nonce" ? job.nonce + 1 : "changed";
    job.typed_data.message = structuredClone(job.action);
    await assert.rejects(session.signFinancial(job, profile, "builder", AUTH_ORIGIN));
    assert.equal(provider.calls.some(call => call.method === "eth_signTypedData_v4"), false);
  });
}
test("wrong origin, user, chain, kind and expired plans cannot prompt", async () => {
  const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
  await assert.rejects(session.signFinancial(live(), profile, "builder", "https://foreign.example"));
  await assert.rejects(session.signFinancial(live(), { ...profile, address: profile.agent }, "builder", AUTH_ORIGIN));
  await assert.rejects(session.signFinancial(live(), profile, "revoke_builder", AUTH_ORIGIN));
  const expired = live(); expired.expires_ms = Date.now();
  await assert.rejects(session.signFinancial(expired, profile, "builder", AUTH_ORIGIN));
  provider.chainId = "0x1";
  await assert.rejects(session.signFinancial(live(), profile, "builder", AUTH_ORIGIN));
  assert.equal(provider.calls.some(call => call.method === "eth_signTypedData_v4"), false);
});
for (const event of ["accountsChanged", "chainChanged", "disconnect"]) {
  test(`${event} during financial prompt discards its signature`, async () => {
    const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
    let entered, resolve;
    const started = new Promise(r => { entered = r; });
    const original = provider.request.bind(provider);
    provider.request = args => args.method === "eth_signTypedData_v4" ? (entered(), new Promise(r => { resolve = r; })) : original(args);
    const pending = session.signFinancial(live(), profile, "builder", AUTH_ORIGIN);
    await started; provider.emit(event, []); resolve(signature);
    await assert.rejects(pending, /Wallet changed/);
  });
}
