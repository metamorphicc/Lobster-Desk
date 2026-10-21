import test from 'node:test';
import assert from 'node:assert/strict';
import { isLaunchPreview, launchFigures } from '../src/lib/launch-preview.ts';

test('homepage figures require the configuration switch and stay isolated to loopback tank views', () => {
  for (const host of ['localhost','127.0.0.1','[::1]']) assert.equal(isLaunchPreview(`http://${host}:3000/`, false, true), true);
  for (const url of ['http://127.0.0.1:3000/operator', 'https://lobster.example/', 'https://localhost.example/', 'https://127.0.0.1.example/', 'invalid']) assert.equal(isLaunchPreview(url, false, true), false);
  assert.equal(isLaunchPreview('http://127.0.0.1:3000/', true, true), false);
  assert.equal(isLaunchPreview('http://127.0.0.1:3000/', false, false), false);
  assert.equal(isLaunchPreview('http://127.0.0.1:3000/?preview=launch', false, false), false);
  assert.equal(isLaunchPreview('http://127.0.0.1:3000/'), false);
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
