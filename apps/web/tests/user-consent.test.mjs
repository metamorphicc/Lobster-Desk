import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { validateExecutionContext, validateLocalIntent, validatePermissionPlans } from "../src/lib/user-consent.ts";

// Produced by the actual Python UserIntents/SDK contracts, using synthetic inputs.
const fixture = JSON.parse(fs.readFileSync(new URL("./fixtures/user-consent.json", import.meta.url), "utf8"));
const owner = fixture.context.address, profile = fixture.context.profile;

test("actual Python/SDK unsigned contracts retain distinct local and exchange domains", () => {
  assert.equal(validateExecutionContext(fixture.context, owner).profile.agent, profile.agent);
  assert.equal(validateLocalIntent(fixture.intent, profile, fixture.plan, fixture.intent.nonce).typed_data.domain.name, "Lobster Desk Local Intent");
  assert.equal(validatePermissionPlans(fixture.permissions, profile).agent.typed_data.domain.name, "HyperliquidSignTransaction");
  assert.equal(fixture.intent.wallet_signing_enabled, false);
});

for (const field of ["wallet_signing_enabled", "exchange_submission_enabled", "signatures_accepted"]) {
  test(`execution context cannot widen ${field}`, () => {
    assert.throws(() => validateExecutionContext({ ...fixture.context, [field]: true }, owner));
  });
}
test("contexts cannot cross owners, duplicate roles or carry an unbounded journal", () => {
  assert.throws(() => validateExecutionContext(fixture.context, profile.agent));
  assert.throws(() => validateExecutionContext({ ...fixture.context, profile: { ...profile, agent: owner } }, owner));
  assert.throws(() => validateExecutionContext({ ...fixture.context, intents: Array(11).fill(fixture.context.intents[0]) }, owner));
});
for (const change of ["owner", "agent", "builder", "planHash", "builderFeeTenthsBps", "nonce", "validUntil"]) {
  test(`changed local intent ${change} cannot be reviewed as the bound plan`, () => {
    const intent = structuredClone(fixture.intent);
    const value = intent.typed_data.message[change];
    intent.typed_data.message[change] = typeof value === "number" ? value + 1 : "0x" + "9".repeat(change === "planHash" ? 64 : 40);
    assert.throws(() => validateLocalIntent(intent, profile, fixture.plan, fixture.intent.nonce));
  });
}
test("expired intents, financial proofs and changed domains are refused", () => {
  assert.throws(() => validateLocalIntent(fixture.intent, profile, fixture.plan, fixture.intent.expires_ms));
  assert.throws(() => validateLocalIntent({ ...fixture.intent, proof: "untrusted-signature" }, profile, fixture.plan, fixture.intent.nonce));
  const intent = structuredClone(fixture.intent); intent.typed_data.domain.chainId = 1;
  assert.throws(() => validateLocalIntent(intent, profile, fixture.plan, fixture.intent.nonce));
  intent.typed_data.domain.chainId = 421614; intent.typed_data.types.TestnetTradeIntent.push({ name: "hiddenAction", type: "bytes" });
  assert.throws(() => validateLocalIntent(intent, profile, fixture.plan, fixture.intent.nonce));
});
for (const change of ["builder", "maxFeeRate", "nonce", "signatureChainId", "type"]) {
  test(`SDK permission ${change} cannot differ from the reviewed configuration`, () => {
    const data = structuredClone(fixture.permissions);
    const action = data.builder.action;
    action[change] = change === "nonce" ? action.nonce + 1 : "changed";
    data.builder.typed_data.message = structuredClone(action);
    assert.throws(() => validatePermissionPlans(data, profile));
  });
}
test("hidden fields or changed typed messages cannot pass as unsigned SDK approvals", () => {
  const data = structuredClone(fixture.permissions);
  data.agent.action.withdraw = "1000"; data.agent.typed_data.message.withdraw = "1000";
  assert.throws(() => validatePermissionPlans(data, profile));
  assert.throws(() => validatePermissionPlans({ ...fixture.permissions, wallet_signing_enabled: true }, profile));
});
