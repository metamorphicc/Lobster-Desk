import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";
import { WalletSession } from "../src/lib/wallet.ts";
import { AUTH_ORIGIN, AUTH_STATEMENT, messageHex, validateAuthChallenge, validateAuthResult } from "../src/lib/wallet-auth.ts";

const owner = "0x" + "a".repeat(40), signature = "0x" + "1".repeat(130);
function challenge() {
  const issued_at = new Date().toISOString(), expires_at = new Date(Date.parse(issued_at) + 120000).toISOString();
  const nonce = "1".repeat(32), challenge_id = "2".repeat(32);
  return { challenge_id, address: owner, origin: AUTH_ORIGIN, chain_id: 421614, nonce, issued_at, expires_at,
    scope: "testnet:preview", order_submission_enabled: false, fee_collection_enabled: false,
    message: `${AUTH_ORIGIN} wants you to sign in with your Ethereum account:\n${owner}\n\n${AUTH_STATEMENT}\n\nURI: ${AUTH_ORIGIN}\nVersion: 1\nChain ID: 421614\nNonce: ${nonce}\nIssued At: ${issued_at}\nExpiration Time: ${expires_at}\nRequest ID: ${challenge_id}` };
}
class Provider extends EventEmitter {
  calls = [];
  accounts = [owner]; chainId = "0x66eee";
  async request(args) {
    this.calls.push(args);
    if (args.method === "eth_accounts" || args.method === "eth_requestAccounts") return this.accounts;
    if (args.method === "eth_chainId") return this.chainId;
    if (args.method === "personal_sign") return signature;
    throw new Error("Unexpected wallet method");
  }
}
test("only an explicit reviewed authentication request uses personal_sign with UTF-8 hex", async () => {
  const provider = new Provider(), session = new WalletSession();
  await session.connect(provider);
  assert.equal(provider.calls.some(call => call.method === "personal_sign"), false);
  const c = challenge();
  assert.equal(await session.signAuthentication(c, AUTH_ORIGIN), signature);
  assert.deepEqual(provider.calls.find(call => call.method === "personal_sign").params, [messageHex(c.message), owner]);
  assert.equal(provider.calls.some(call => /sendTransaction|signTypedData|switchEthereumChain/.test(call.method)), false);
});
for (const changed of ["origin", "chain_id", "address", "scope", "message", "nonce", "order_submission_enabled", "fee_collection_enabled"]) {
  test(`untrusted ${changed} cannot reach a wallet signature`, async () => {
    const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
    const c = challenge(); c[changed] = typeof c[changed] === "boolean" ? true : "changed";
    await assert.rejects(session.signAuthentication(c, AUTH_ORIGIN));
    assert.equal(provider.calls.some(call => call.method === "personal_sign"), false);
  });
}
test("wrong local origin, wallet network and expired proof are rejected before RPC", async () => {
  const c = challenge();
  assert.throws(() => validateAuthChallenge(c, owner, "http://localhost:3000", "0x66eee"));
  assert.throws(() => validateAuthChallenge(c, owner, AUTH_ORIGIN, "0x1"));
  assert.throws(() => validateAuthChallenge(c, owner, AUTH_ORIGIN, "0x66eee", Date.parse(c.expires_at)));
  assert.throws(() => validateAuthChallenge(c, owner, AUTH_ORIGIN, "0x66eee", Date.parse(c.issued_at) - 3000));
});
for (const event of ["accountsChanged", "chainChanged", "disconnect"]) {
  test(`${event} while wallet prompt is pending discards the signature`, async () => {
    const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
    let resolve, entered;
    const started = new Promise(r => { entered = r; });
    const original = provider.request.bind(provider);
    provider.request = args => args.method === "personal_sign" ? (entered(), new Promise(r => { resolve = r; })) : original(args);
    const pending = session.signAuthentication(challenge(), AUTH_ORIGIN);
    await started; provider.emit(event, []); resolve(signature);
    await assert.rejects(pending, /Wallet changed/);
    assert.equal(session.snapshot().address, null);
  });
}
test("silent provider account change is detected before signing", async () => {
  const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
  provider.accounts = ["0x" + "b".repeat(40)];
  await assert.rejects(session.signAuthentication(challenge(), AUTH_ORIGIN), /changed/);
  assert.equal(provider.calls.some(call => call.method === "personal_sign"), false);
});
test("silent provider network change after signing discards the proof", async () => {
  const provider = new Provider(), session = new WalletSession(); await session.connect(provider);
  const original = provider.request.bind(provider);
  provider.request = async args => { if (args.method === "personal_sign") { provider.chainId = "0x1"; return signature; } return original(args); };
  await assert.rejects(session.signAuthentication(challenge(), AUTH_ORIGIN), /changed/);
});
test("server session flags cannot widen the wallet's local preview scope", () => {
  const result = { address: owner, access_token: "t".repeat(43), expires_at: new Date(Date.now() + 900000).toISOString(),
    scope: "testnet:preview", token_type: "Bearer", authenticated: true, network: "testnet", order_submission_enabled: false, fee_collection_enabled: false };
  assert.equal(validateAuthResult(result, owner).address, owner);
  for (const change of [{ address: "other" }, { scope: "trading" }, { order_submission_enabled: true },
    { fee_collection_enabled: true }, { access_token: "bad" }, { expires_at: "invalid" }, { network: "mainnet" },
    { expires_at: new Date(Date.now() - 1).toISOString() }]) assert.throws(() => validateAuthResult({ ...result, ...change }, owner));
});
