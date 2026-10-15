import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";
import { WalletSession, discoverWallets, normalizeAddress } from "../src/lib/wallet.ts";

const owner = "0x" + "a".repeat(40);
class FakeProvider extends EventEmitter {
  calls = [];
  accounts = [owner];
  async request({ method }) {
    this.calls.push(method);
    if (method === "eth_requestAccounts") return this.accounts;
    if (method === "eth_chainId") return "0x66eee";
    throw new Error("Unexpected RPC: " + method);
  }
}
test("connecting calls only account/chain RPC; disconnect cleans subscriptions", async () => {
  const provider = new FakeProvider(), session = new WalletSession();
  await session.connect(provider);
  assert.equal(session.snapshot().address, owner);
  assert.equal(session.snapshot().status, "connected");
  assert.deepEqual(provider.calls, ["eth_requestAccounts", "eth_chainId"]);
  session.disconnect();
  assert.equal(session.snapshot().address, null);
  assert.equal(provider.listenerCount("accountsChanged"), 0);
  assert.equal(provider.listenerCount("chainChanged"), 0);
});
for (const event of ["accountsChanged", "chainChanged", "disconnect"]) {
  test(event + " invalidates the viewed wallet and its revision", async () => {
    const provider = new FakeProvider(), session = new WalletSession();
    await session.connect(provider);
    const revision = session.snapshot().revision;
    provider.emit(event, ["0x" + "b".repeat(40)]);
    assert.equal(session.snapshot().address, null);
    assert.ok(session.snapshot().revision > revision);
    assert.equal(provider.listenerCount(event), 0);
  });
}
test("late wallet response cannot restore a disconnected account", async () => {
  const provider = new FakeProvider(), session = new WalletSession();
  let resolve;
  provider.request = () => new Promise(r => { resolve = r; });
  const pending = session.connect(provider);
  session.disconnect(); resolve([owner]); await pending;
  assert.equal(session.snapshot().status, "idle");
  assert.equal(session.snapshot().address, null);
});
test("wallet event during connection invalidates the pending result", async () => {
  const provider = new FakeProvider(), session = new WalletSession();
  let resolve;
  provider.request = () => new Promise(r => { resolve = r; });
  const pending = session.connect(provider);
  provider.emit("accountsChanged", []); resolve([owner]); await pending;
  assert.equal(session.snapshot().address, null);
});
test("rejected or malformed account never becomes a session", async () => {
  const provider = new FakeProvider(), session = new WalletSession();
  provider.accounts = ["0x" + "0".repeat(40)];
  await session.connect(provider);
  assert.equal(session.snapshot().status, "error");
  provider.request = async () => { throw { code: 4001, message: "Do not echo wallet payloads" }; };
  await session.connect(provider);
  assert.match(session.snapshot().error, /declined/);
  assert.equal(session.snapshot().address, null);
});
test("provider discovery validates and deduplicates without requesting access", () => {
  const target = new EventTarget(), provider = new FakeProvider();
  target.ethereum = provider;
  target.addEventListener("eip6963:requestProvider", () => {
    const detail = { info: { uuid: "example-wallet", name: "Example", icon: "data:invalid" }, provider };
    target.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail }));
    target.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail }));
  });
  let wallets;
  const release = discoverWallets(target, value => { wallets = value; });
  assert.equal(wallets.length, 1);
  assert.deepEqual(Object.keys(wallets[0]), ["id", "name", "provider"]);
  assert.deepEqual(provider.calls, []);
  release();
  target.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail: { info: { uuid: "late", name: "Late" }, provider: new FakeProvider() } }));
  assert.equal(wallets.length, 1);
});
test("addresses are normalized and cannot be URLs, zero or truncated", () => {
  assert.equal(normalizeAddress("0x" + "A".repeat(40)), owner);
  for (const value of [null, "0x123", "0x" + "0".repeat(40), "https://malicious.invalid"]) assert.equal(normalizeAddress(value), null);
});
test("provider subscription failure does not leave a connecting session", async () => {
  const provider = new FakeProvider(), session = new WalletSession();
  provider.on = () => { throw new Error("Broken provider"); };
  await session.connect(provider);
  assert.equal(session.snapshot().status, "error");
  assert.equal(session.snapshot().address, null);
});
test("late chain response cannot overwrite a newer provider session", async () => {
  const first = new FakeProvider(), second = new FakeProvider(), session = new WalletSession();
  let resolveChain;
  first.request = async ({method}) => method === "eth_requestAccounts" ? [owner] : new Promise(resolve => { resolveChain = resolve; });
  const pending = session.connect(first);
  await Promise.resolve();
  second.accounts = ["0x" + "b".repeat(40)];
  await session.connect(second);
  resolveChain("0x1"); await pending;
  assert.equal(session.snapshot().address, second.accounts[0]);
  assert.equal(session.snapshot().chainId, "0x66eee");
});
