// Controlled DOM checks: no model, Telegram or publisher calls.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const script = fs.readFileSync(path.resolve(__dirname, '../../static/js/customer_workflow.js'), 'utf8');

function journeys({ workspace = 'workspace-one', active = true, label = 'Waiting for answers', unsafe = '' } = {}) {
    return `<div id="workflow-journeys" data-workspace="${workspace}" data-active="${active}"><article><h3>${label}</h3><details data-workflow-details="idea-one"><summary>Activity</summary><p>Saved</p></details><a href="/conversation/one">Answer the questions</a><form data-workflow-resume-form action="/resume/one"><button type="submit">Continue</button></form>${unsafe}</article></div>`;
}
function fixture(options = {}) {
    const dom = new JSDOM(`<div data-customer-workflow data-workflow-workspace="workspace-one" data-workflow-status-url="${options.endpoint || '/workspace/one/status/'}"><form data-workflow-create-form><textarea name="idea" required></textarea><button type="submit">Start a post</button></form><button data-workflow-prompt="A new idea" hidden>Use idea</button><h2 id="cw-activity-heading">Posts in progress</h2><p data-workflow-poll-status></p><button data-workflow-apply-updates hidden>New activity</button><p data-workflow-refresh-note hidden>Reload</p>${journeys(options)}</div>`, { runScripts: 'outside-only', url: 'https://smbean.example/workspace/one/start/' });
    const win = dom.window;
    const timers = new Map();
    let serial = 0;
    let hidden = false;
    Object.defineProperty(win.document, 'hidden', { configurable: true, get: () => hidden });
    win.setTimeout = (fn, delay) => { const id = ++serial; timers.set(id, { fn, delay }); return id; };
    win.clearTimeout = id => timers.delete(id);
    const calls = [];
    const responses = [];
    win.fetch = async (url, opts) => {
        calls.push({ url, opts });
        const result = responses.shift();
        if (result instanceof Error) throw result;
        if (!result) throw new Error('No controlled response');
        return result;
    };
    win.confirm = () => false;
    win.eval(script);
    win.document.dispatchEvent(new win.Event('DOMContentLoaded'));
    const query = selector => win.document.querySelector(selector);
    async function advance() {
        const item = [...timers].find(([, timer]) => timer.delay === 30000);
        assert.ok(item, 'Expected one progress poll');
        timers.delete(item[0]);
        await item[1].fn();
    }
    const reply = (data = {}, extra = {}) => responses.push({ ok: true, status: 200, redirected: false, headers: { get: () => 'application/json' }, json: async () => ({ html: journeys(data), active: data.active !== false, checked_at: '2026-10-14T10:00:00Z' }), ...extra });
    return { win, query, timers, calls, responses, advance, reply, hidden(value) { hidden = value; win.document.dispatchEvent(new win.Event('visibilitychange')); } };
}

test('an idle saved idea schedules no polling and ordinary forms remain available', () => {
    const f = fixture({ active: false });
    assert.equal(f.timers.size, 0);
    assert.equal(f.query('button[type="submit"]').disabled, false);
    assert.equal(f.query('[data-workflow-prompt]').hidden, false);
});

test('a prompt never silently overwrites an existing customer idea', () => {
    const f = fixture({ active: false });
    f.query('textarea').value = 'My unsent detail';
    f.query('[data-workflow-prompt]').click();
    assert.equal(f.query('textarea').value, 'My unsent detail');
    f.query('textarea').value = '';
    f.query('[data-workflow-prompt]').click();
    assert.equal(f.query('textarea').value, 'A new idea');
    assert.equal(f.win.document.activeElement, f.query('textarea'));
});

test('a valid native POST prevents duplicate clicks and back navigation restores controls', () => {
    const f = fixture({ active: false });
    const form = f.query('[data-workflow-create-form]');
    f.query('textarea').value = 'Useful idea';
    const event = () => new f.win.Event('submit', { bubbles: true, cancelable: true });
    assert.equal(form.dispatchEvent(event()), true);
    assert.equal(form.querySelector('button').disabled, true);
    assert.equal(form.dispatchEvent(event()), false);
    f.win.dispatchEvent(new f.win.Event('pageshow'));
    assert.equal(form.querySelector('button').disabled, false);
    assert.equal(form.dataset.submitting, undefined);
});

test('focused action controls survive incoming progress until the reader explicitly applies it', async () => {
    const f = fixture();
    const link = f.query('#workflow-journeys a');
    link.focus();
    f.reply({ label: 'The draft needs review', active: false });
    await f.advance();
    assert.equal(f.win.document.activeElement, link);
    assert.match(f.query('#workflow-journeys').textContent, /Waiting for answers/);
    assert.equal(f.query('[data-workflow-apply-updates]').hidden, false);
    f.query('[data-workflow-apply-updates]').click();
    assert.match(f.query('#workflow-journeys').textContent, /The draft needs review/);
    assert.equal(f.win.document.activeElement, f.query('#cw-activity-heading'));
    assert.equal(f.query('[data-workflow-apply-updates]').hidden, true);
});

test('incoming progress preserves expanded activity without changing the unsent idea', async () => {
    const f = fixture();
    f.query('details').open = true;
    f.query('textarea').value = 'Unsent customer wording';
    f.reply({ label: 'Draft creation started', active: false });
    await f.advance();
    assert.equal(f.query('details').open, true);
    assert.equal(f.query('textarea').value, 'Unsent customer wording');
    assert.equal(f.query('#workflow-journeys').dataset.active, 'false');
    assert.equal([...f.timers.values()].filter(item => item.delay === 30000).length, 0);
});

test('an expanded disclosure and freshly masked CSRF token are not announced as new activity', async () => {
    const f = fixture();
    f.query('details').open = true;
    const form=f.query('[data-workflow-resume-form]');
    form.insertAdjacentHTML('afterbegin', '<input name="csrfmiddlewaretoken" value="old-masked-token">');
    const html=journeys().replace('<button type="submit">Continue</button>', '<input name="csrfmiddlewaretoken" value="new-masked-token"><button type="submit">Continue</button>');
    f.reply({}, { json: async () => ({ html, active: true }) });
    await f.advance();
    assert.equal(f.query('[data-workflow-poll-status]').textContent, '');
    assert.equal(f.query('[data-workflow-apply-updates]').hidden, true);
    assert.equal(f.query('details').open, true);
});

test('session expiry stops polling, retains the saved view and offers reload', async () => {
    const f = fixture();
    f.reply({}, { ok: false, status: 403 });
    await f.advance();
    assert.equal(f.query('[data-workflow-refresh-note]').hidden, false);
    assert.match(f.query('#workflow-journeys').textContent, /Waiting for answers/);
    assert.equal(f.timers.size, 0);
    assert.equal(f.calls[0].opts.credentials, 'same-origin');
    assert.equal(f.calls[0].opts.headers.Accept, 'application/json');
});

test('login redirects are never inserted into the customer progress panel', async () => {
    const f = fixture();
    f.reply({}, { redirected: true });
    await f.advance();
    assert.equal(f.query('[data-workflow-refresh-note]').hidden, false);
    assert.equal(f.timers.size, 0);
});

test('three transient failures stop automatically instead of polling forever', async () => {
    const f = fixture();
    for (let i = 0; i < 3; i++) { f.responses.push(new Error('Controlled failure')); await f.advance(); }
    assert.equal(f.calls.length, 3);
    assert.equal(f.query('[data-workflow-refresh-note]').hidden, false);
    assert.equal(f.timers.size, 0);
});

test('a response for another company is never displayed', async () => {
    const f = fixture();
    f.reply({ workspace: 'another-company', label: 'Private other data' });
    await f.advance();
    assert.doesNotMatch(f.query('#workflow-journeys').textContent, /Private other data/);
    assert.match(f.query('#workflow-journeys').textContent, /Waiting for answers/);
});

test('active HTML or script URLs in a malformed fragment are rejected', async () => {
    for (const unsafe of ['<script>window.leak=true</script>', '<a href="javascript:alert(1)">Unsafe</a>', '<a href="java\tscript:alert(1)">Unsafe</a>', '<p onclick="alert(1)">Unsafe</p>', '<form action="https://another-company.example/"><button>Unsafe</button></form>']) {
        const f = fixture();
        f.reply({ label: 'Malformed update', unsafe });
        await f.advance();
        assert.doesNotMatch(f.query('#workflow-journeys').textContent, /Malformed update/);
        assert.equal(f.win.leak, undefined);
    }
});

test('an active-state mismatch cannot silently switch the poll lifecycle', async () => {
    const f = fixture();
    f.reply({ active: false, label: 'Mismatch' }, { json: async () => ({ html: journeys({ active: false, label: 'Mismatch' }), active: true }) });
    await f.advance();
    assert.doesNotMatch(f.query('#workflow-journeys').textContent, /Mismatch/);
});

test('a question waiting for a Telegram answer can keep read-only progress polling without claiming active work', async () => {
    const f = fixture();
    f.reply({}, { json: async () => ({ html: journeys({ active: true, label: 'Waiting for your answer' }), active: false, polling: true }) });
    await f.advance();
    assert.match(f.query('#workflow-journeys').textContent, /Waiting for your answer/);
    assert.equal(f.query('#workflow-journeys').dataset.active, 'true');
    assert.equal([...f.timers.values()].filter(item => item.delay === 30000).length, 1);
});

test('hidden tabs stop their timer and resuming the tab schedules one check', () => {
    const f = fixture();
    assert.equal(f.timers.size, 1);
    f.hidden(true);
    assert.equal(f.timers.size, 0);
    f.hidden(false);
    assert.equal(f.timers.size, 1);
});

test('a different-origin status endpoint is never fetched', () => {
    const f = fixture({ endpoint: 'https://another-company.example/status/' });
    assert.equal(f.timers.size, 0);
    assert.equal(f.calls.length, 0);
});
