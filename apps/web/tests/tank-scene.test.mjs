import test from 'node:test';
import assert from 'node:assert/strict';
import { tankPhase, equityDelta } from '../src/lib/tank-scene.ts';

const ep = (status, reviews = {}) => ({ status, reviews });
test('tank distinguishes approval, submission and observed fill and fails closed on stale data', () => {
  for (const [status, expected] of [['approved','approved'],['staged','approved'],['submitting','submitting'],['protected','open'],['filled','open'],['closed','closed'],['needs_protection','attention']]) {
    assert.equal(tankPhase(ep(status), true), expected);
    assert.equal(tankPhase(ep(status), false), 'offline');
  }
  assert.equal(tankPhase(undefined, true), 'idle');
  assert.equal(tankPhase(ep('unexpected'), true), 'idle');
  assert.equal(tankPhase(ep('approved', {risk:{verdict:'reject'}}), true), 'vetoed');
});
test('equity animations require two observed balances and never invent profit on reconnection', () => {
  assert.equal(equityDelta(null, '1000'), null);
  assert.equal(equityDelta('1000', null), null);
  assert.equal(equityDelta('1000.10', '1000.1'), null);
  assert.equal(equityDelta('1000.10', '1001.11'), '+$1.01');
  assert.equal(equityDelta('1000.10', '999.99'), '−$0.11');
  assert.equal(equityDelta('9007199254740992.01', '9007199254740992.02'), '+$0.01');
  assert.equal(equityDelta('1.001', '1.009'), null);
  assert.equal(equityDelta('NaN', '100'), null);
});
