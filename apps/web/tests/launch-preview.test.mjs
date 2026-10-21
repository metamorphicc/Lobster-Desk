import test from 'node:test';
import assert from 'node:assert/strict';
import { isLaunchPreview, launchFigures } from '../src/lib/launch-preview.ts';

test('invented figures require an explicit loopback-only tank URL and cannot enter operator mode', () => {
  for (const host of ['localhost','127.0.0.1','[::1]']) assert.equal(isLaunchPreview(`http://${host}:3000/?preview=launch`), true);
  for (const url of ['http://127.0.0.1:3000/', 'http://127.0.0.1:3000/operator?preview=launch', 'https://lobster.example/?preview=launch', 'https://localhost.example/?preview=launch', 'https://127.0.0.1.example/?preview=launch', 'invalid']) assert.equal(isLaunchPreview(url), false);
  assert.equal(isLaunchPreview('http://127.0.0.1:3000/?preview=launch', true), false);
});

test('illustrative capital, profit and donation figures stay internally consistent and include losses', () => {
  const cents = s => BigInt(s.replace('.',''));
  for (const tick of [0,1,2,3,8,30,1000]) {
    const data = launchFigures(tick);
    assert.equal(data.source, 'illustrative-launch-preview');
    assert.equal(cents(data.equity), 100000n + cents(data.profit) - cents(data.donations.sent));
    assert.equal(cents(data.donations.allocated) * 2n, cents(data.profit));
    assert.equal(cents(data.donations.outstanding), cents(data.donations.allocated) - cents(data.donations.sent));
  }
  assert.ok(cents(launchFigures(3).equity) < cents(launchFigures(2).equity));
  assert.throws(() => launchFigures(-1));
});
