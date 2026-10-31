import assert from 'node:assert/strict';
import test from 'node:test';

import { withCleanAuditTabs, withCpuSlowdown } from './lifecycle.mjs';

test('interaction timing always restores normal CPU and detaches, including failure', async () => {
  for (const fails of [false, true]) {
    const calls = [];
    const cdp = { async send(method, value) { calls.push([method, value.rate]); }, async detach() { calls.push(['detach']); } };
    const result = withCpuSlowdown(cdp, async () => { if (fails) throw new Error('input failed'); return 7; });
    if (fails) await assert.rejects(result, /input failed/);
    else assert.equal(await result, 7);
    assert.deepEqual(calls, [['Emulation.setCPUThrottlingRate', 4], ['Emulation.setCPUThrottlingRate', 1], ['detach']]);
  }
});

test('an audit never leaves extra tabs running between samples, even on failure', async () => {
  for (const fails of [false, true]) {
    let closed = 0;
    const original = { async close() { throw new Error('The caller owns this page.'); } };
    const extra = { async close() { closed++; } };
    let pages = [original];
    const context = { pages: () => pages };
    const result = withCleanAuditTabs(context, async () => { pages = [original, extra]; if (fails) throw new Error('audit failed'); return 9; });
    if (fails) await assert.rejects(result, /audit failed/);
    else assert.equal(await result, 9);
    assert.equal(closed, 1);
  }
});
