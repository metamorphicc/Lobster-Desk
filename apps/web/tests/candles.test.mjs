import test from 'node:test';
import assert from 'node:assert/strict';
import { aggregateCandles } from '../src/lib/candles.ts';

const bar = (time, close = '101') => ({ time, open: '100', high: '103', low: '98', close });
test('intervals preserve observed opening/high/low/last close in chronological order', () => {
  const rows = [bar(240, '102'), bar(0), bar(180), bar(120), bar(60)];
  assert.deepEqual(aggregateCandles(rows, 5), [{ time: 0, open: '100', high: '103', low: '98', close: '102' }]);
  assert.equal(aggregateCandles(rows, 1)[0].time, 0);
});
test('never fill a missing minute or invent an opening for a partial leading bucket', () => {
  assert.deepEqual(aggregateCandles([bar(60), bar(120), bar(180), bar(300)], 5), [bar(300)]);
  assert.deepEqual(aggregateCandles([bar(0), bar(120), bar(300)], 5), [bar(300)]);
});
test('reject nonfinite/negative/invalid OHLC and duplicate timestamps', () => {
  for (const invalid of [{...bar(0),high:'99'}, {...bar(0),low:'102'}, {...bar(0),close:'NaN'}, {...bar(0),open:'-1'},bar(1)]) {
    assert.throws(() => aggregateCandles([invalid], 1));
  }
  assert.throws(() => aggregateCandles([bar(0), bar(0)], 1));
});
