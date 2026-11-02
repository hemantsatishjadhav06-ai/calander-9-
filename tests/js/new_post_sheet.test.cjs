// The New post sheet's Write it myself address (Phase 3, screen 1, T17): static/js/new-post-sheet.js,
// run in a jsdom page. Open the editor (new-post-self-open) links to composer:compose and binds its href
// to editorUrl(base): the base alone, or the base with scheduled_date, scheduled_time and account, built
// with URLSearchParams, when the sheet was opened with them (a Calendar cell's "+" sends
// new-post:open with {mode: 'self', date, time, account}). Nothing else the opener sends is carried, and
// opening from the New post button afterwards carries nothing. That the cells send those values is
// apps/studio/tests/test_new_post_self.py's; the browser case is T21's.
// Requires the locked development dependencies; this makes no network requests.
// npm ci --ignore-scripts && npm run test:ui
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const script = fs.readFileSync(path.resolve(__dirname, '../../static/js/new-post-sheet.js'), 'utf8');
const BASE = '/workspace/3f1c2a9e-0000-4000-8000-000000000001/compose/';
const ACCOUNT = '9b2f6d7c-1111-4222-8333-444455556666';

/** The sheet's component as Alpine would hold it, in a page with the New post button. */
function sheet() {
  const dom = new JSDOM('<button aria-controls="new-post-sheet" aria-expanded="false">New post</button><div id="root"></div>', {
    runScripts: 'outside-only',
    url: 'https://example.test/workspace/one/calendar/',
  });
  const win = dom.window;
  win.eval(script);
  const component = win.newPostSheet();
  component.$el = win.document.getElementById('root');
  component.$nextTick = (callback) => callback && callback();
  component.init();
  return { win, component };
}

function query(url) {
  const [base, search = ''] = url.split('?');
  return { base, params: [...new URLSearchParams(search)] };
}

test('opened from the New post button, the editor link is the editor alone', () => {
  const { component } = sheet();
  assert.equal(component.editorUrl(BASE), BASE);
  component.open({});
  assert.equal(component.editorUrl(BASE), BASE);
});

test("a cell's date and time are carried as the composer reads them", () => {
  const { component } = sheet();
  component.open({ mode: 'self', date: '2026-11-17', time: '10:00', account: '' });

  assert.equal(component.sheetMode, 'self');
  assert.deepEqual(query(component.editorUrl(BASE)), {
    base: BASE,
    params: [['scheduled_date', '2026-11-17'], ['scheduled_time', '10:00']],
  });
  assert.equal(component.editorUrl(BASE), `${BASE}?scheduled_date=2026-11-17&scheduled_time=10%3A00`);
});

test("a channel slot's account comes first, as the slot's own link has it", () => {
  const { win, component } = sheet();
  win.dispatchEvent(new win.CustomEvent('new-post:open', {
    detail: { mode: 'self', date: '2026-11-17', time: '10:00', account: ACCOUNT },
  }));

  assert.equal(component.sheetOpen, true);
  assert.deepEqual(query(component.editorUrl(BASE)).params, [
    ['account', ACCOUNT],
    ['scheduled_date', '2026-11-17'],
    ['scheduled_time', '10:00'],
  ]);
});

test('only the date, the time and the account are carried, and only those it was given', () => {
  const { component } = sheet();
  component.open({ mode: 'self', date: '2026-11-17', time: '', account: '', caption: 'Hi', next: '/elsewhere/' });
  assert.deepEqual(query(component.editorUrl(BASE)).params, [['scheduled_date', '2026-11-17']]);

  component.sheetContext = { date: '2026-11-17', time: '10:00', account: ACCOUNT, caption: 'Hi', template: '7' };
  assert.deepEqual(
    query(component.editorUrl(BASE)).params.map(([key]) => key),
    ['account', 'scheduled_date', 'scheduled_time'],
  );
});

test('opening from the button after a cell forgets the cell', () => {
  const { component } = sheet();
  component.open({ mode: 'self', date: '2026-11-17', time: '10:00', account: ACCOUNT });
  component.close();
  component.open({});

  assert.equal(component.sheetMode, 'team');
  assert.equal(component.editorUrl(BASE), BASE);
});

test('closing gives focus back to the cell that opened the sheet', () => {
  const { win, component } = sheet();
  const plus = win.document.createElement('a');
  plus.href = `${BASE}?scheduled_date=2026-11-17&scheduled_time=10:00`;
  win.document.body.append(plus);
  component.open({ mode: 'self', date: '2026-11-17', time: '10:00', account: '' }, plus);
  component.close();

  assert.equal(win.document.activeElement, plus);
});

test("a cell's '+' that cannot take focus back (hover-only, hidden again) hands it to the New post button", () => {
  const { win, component } = sheet();
  const plus = win.document.createElement('a'); // no href: like a hidden "+", it cannot be focused
  win.document.body.append(plus);
  component.open({ mode: 'self', date: '2026-11-17', time: '10:00', account: '' }, plus);
  component.close();

  assert.equal(win.document.activeElement, win.document.querySelector('[aria-controls="new-post-sheet"]'));
});

test('values are encoded, never pasted into the address', () => {
  const { component } = sheet();
  component.sheetContext = { date: '2026-11-17&next=/x', time: '10:00#y', account: '' };
  assert.deepEqual(query(component.editorUrl(BASE)).params, [
    ['scheduled_date', '2026-11-17&next=/x'],
    ['scheduled_time', '10:00#y'],
  ]);
  assert.equal(component.editorUrl(BASE).includes('#'), false);
});

// ── Save it as an idea (T18) ─────────────────────────────────────────────────────────────────────
// The idea form's script: its columns and tags come from json_script (never pasted into code), an
// emoji goes into the sheet's own description, pictures go up one by one and are sent as asset ids,
// a new tag goes through the form's tag address, and saving answers in the form's own error line
// (no toast, no browser alert) or fires ideaChanged, closes the sheet and empties the idea form.
const IDEA_ACTION = '/workspace/one/ideas/create/';
const UPLOAD = '/workspace/one/ideas/upload-media/';
const TAGS = '/workspace/one/tags/create/';
const AWKWARD = 'Mike\'s "launch" </script><b>bold</b>';

function jsonScript(id, value) {
  // What Django's json_script writes: <, > and & escaped so the data cannot close the element.
  const text = JSON.stringify(value).replace(/</g, '\\u003C').replace(/>/g, '\\u003E').replace(/&/g, '\\u0026');
  return `<script type="application/json" id="${id}">${text}</script>`;
}

/** The sheet with its idea form, as the page renders it (Alpine's bindings left to the test). */
function ideaSheet({ columns = [{ id: 'col-a', label: 'Unassigned' }, { id: 'col-b', label: 'To do' }], tags } = {}) {
  const html = `
    <textarea class="idea-desc-input" data-testid="idea-description">the shell's own dialog</textarea>
    <button aria-controls="new-post-sheet" aria-expanded="false">New post</button>
    <div id="root">
      ${jsonScript('new-post-idea-columns', columns)}
      ${tags ? jsonScript('new-post-idea-tags', tags) : ''}
      <div data-view="team"><textarea data-testid="new-post-team-idea"></textarea></div>
      <div data-view="idea">
        <form data-testid="new-post-idea" action="${IDEA_ACTION}" method="post" data-upload-url="${UPLOAD}"${tags ? ` data-tag-url="${TAGS}"` : ''}>
          <input type="hidden" name="csrfmiddlewaretoken" value="form-token">
          <select name="group">${columns.map((c) => `<option value="${c.id}">${c.id}</option>`).join('')}</select>
          <input type="text" name="title" data-testid="idea-title">
          <textarea name="description" data-testid="idea-description"></textarea>
          <input type="hidden" name="media_asset_ids" value="">
          <input type="file" class="hidden" multiple>
        </form>
      </div>
    </div>`;
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'https://example.test/workspace/one/studio/' });
  const win = dom.window;
  win.eval(script);
  const component = win.newPostSheet();
  component.$el = win.document.getElementById('root');
  component.$nextTick = (callback) => callback && callback();
  component.init();
  const form = win.document.querySelector('[data-testid="new-post-idea"]');
  const events = { ideaChanged: 0, toasts: [], alerts: [] };
  win.document.body.addEventListener('ideaChanged', () => { events.ideaChanged += 1; });
  win.addEventListener('htmx-error', (event) => events.toasts.push(event.detail.message));
  win.alert = (message) => events.alerts.push(message);
  return { win, component, form, events };
}

/** A fetch that answers each call in turn and remembers what it was sent. */
function answers(win, ...replies) {
  const calls = [];
  win.fetch = (url, init) => {
    calls.push({ url, init });
    const reply = replies.shift() || { status: 204 };
    const status = reply.status || 200;
    return Promise.resolve({
      ok: status < 400,
      status,
      text: () => Promise.resolve(reply.text || (reply.json ? JSON.stringify(reply.json) : '')),
      json: () => (reply.json ? Promise.resolve(reply.json) : Promise.reject(new Error('not json'))),
    });
  };
  return calls;
}

test('the columns and the tags come from json_script, a quote and markup included, as plain text', () => {
  const columns = [{ id: 'col-a', label: AWKWARD }, { id: 'col-b', label: 'To do' }];
  const { component } = ideaSheet({ columns, tags: ['awards', AWKWARD] });

  assert.deepEqual(JSON.parse(JSON.stringify(component.ideaColumns)), columns);
  assert.equal(component.ideaGroup, 'col-a');
  assert.deepEqual(JSON.parse(JSON.stringify(component.ideaAllTags)), ['awards', AWKWARD]);
});

test('without the templates switch there are no tags to offer', () => {
  const { component } = ideaSheet();
  assert.deepEqual(JSON.parse(JSON.stringify(component.ideaAllTags)), []);
});

test("an emoji goes in at the caret of the sheet's own description, or replaces what is selected", () => {
  const { win, component } = ideaSheet();
  const description = win.document.querySelector('#root [data-testid="idea-description"]');
  description.value = 'A bright idea ';
  description.selectionStart = description.selectionEnd = 14;
  component.emojiPickerOpen = true;
  component._emojiSearch = 'spark';

  component._insertEmoji('✨');
  assert.equal(description.value, 'A bright idea ✨');
  assert.equal(component._emojiSearch, '');
  assert.equal(win.document.querySelector('.idea-desc-input').value, "the shell's own dialog");

  description.selectionStart = 0;
  description.selectionEnd = description.value.length;
  component._insertEmoji('🎉');
  assert.equal(description.value, '🎉');
});

test('a picture goes up to the upload address and is sent as its asset id, in order and once', async () => {
  const { win, component } = ideaSheet();
  const calls = answers(
    win,
    { json: { asset_id: 'asset-1', url: '/media/1.jpg', media_type: 'image', filename: '1.jpg' } },
    { json: { asset_id: 'asset-2', url: '/media/2.mp4', media_type: 'video', filename: '2.mp4' } },
    { json: { asset_id: 'asset-1', url: '/media/1.jpg', media_type: 'image', filename: '1.jpg' } },
  );
  const file = (name, type) => new win.File(['x'], name, { type });

  await component._enqueueMediaFiles([file('1.jpg', 'image/jpeg'), file('2.mp4', 'video/mp4'), file('1.jpg', 'image/jpeg')]);

  assert.deepEqual(calls.map((call) => call.url), [UPLOAD, UPLOAD, UPLOAD]);
  assert.equal(calls[0].init.headers['X-CSRFToken'], 'form-token');
  assert.equal(component.ideaMediaIds(), 'asset-1,asset-2');
  assert.equal(component.ideaPrimaryMediaId(), 'asset-1');
  assert.equal(component.ideaUploads, 0);
  component.removeIdeaMedia(0);
  assert.equal(component.ideaMediaIds(), 'asset-2');
});

test('a picture the server refuses says why in the form\'s own line, with no browser alert', async () => {
  const { win, component, events } = ideaSheet();
  answers(win, { status: 400, json: { error: 'This file is larger than 20 MB.' } });

  await component._enqueueMediaFiles([new win.File(['x'], 'huge.jpg', { type: 'image/jpeg' })]);

  assert.equal(component.ideaError, 'This file is larger than 20 MB.');
  assert.deepEqual(events.alerts, []);
  assert.deepEqual(events.toasts, []);
  assert.equal(component.ideaUploads, 0);
});

test("a new tag goes through the form's tag address and is chosen", async () => {
  const { win, component } = ideaSheet({ tags: ['launch'] });
  const calls = answers(win, { json: { id: 't', name: 'awards', created: true } });

  component.addIdeaTag('  awards ');

  assert.deepEqual(JSON.parse(JSON.stringify(component.ideaTags)), ['awards']);
  assert.deepEqual(JSON.parse(JSON.stringify(component.ideaAllTags)), ['awards', 'launch']);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, TAGS);
  assert.equal(String(calls[0].init.body), 'name=awards');
  assert.equal(calls[0].init.headers['X-CSRFToken'], 'form-token');
  component.toggleIdeaTag('awards');
  assert.deepEqual(JSON.parse(JSON.stringify(component.ideaTags)), []);
});

test("saving fires ideaChanged, closes the sheet and empties the idea form, keeping Ask the team's words", async () => {
  const { win, component, form, events } = ideaSheet();
  const calls = answers(win, { status: 204 });
  win.document.querySelector('[data-testid="new-post-team-idea"]').value = 'Ask about parking';
  component.open({});
  component.setMode('idea');
  component.ideaGroup = 'col-b';
  form.querySelector('[name="group"]').value = 'col-b';
  form.querySelector('[name="title"]').value = 'Covered parking';
  component.ideaMedia = [{ asset_id: 'asset-1', url: '', filename: '', media_type: 'image' }];
  component.ideaTags = ['launch'];

  await component.saveIdea({ target: form });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, IDEA_ACTION);
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers['X-CSRFToken'], 'form-token');
  assert.equal(calls[0].init.body.get('title'), 'Covered parking');
  assert.equal(calls[0].init.body.get('group'), 'col-b');
  assert.equal(events.ideaChanged, 1);
  assert.equal(component.sheetOpen, false);
  assert.equal(form.querySelector('[name="title"]').value, '');
  assert.equal(component.ideaGroup, 'col-a');
  assert.deepEqual(JSON.parse(JSON.stringify([component.ideaMedia, component.ideaTags])), [[], []]);
  assert.equal(component.ideaError, '');
  assert.equal(win.document.querySelector('[data-testid="new-post-team-idea"]').value, 'Ask about parking');
  assert.deepEqual(events.toasts, []);
});

test("a refused idea says why in the form's own line, keeps what was typed and makes no toast", async () => {
  const { win, component, form, events } = ideaSheet();
  answers(win, { status: 400, text: 'Title is required.' });
  component.open({ mode: 'idea' });
  form.querySelector('[name="description"]').value = 'Three reasons';

  const saved = await component.saveIdea({ target: form });

  assert.equal(saved, false);
  assert.equal(component.ideaError, 'Title is required.');
  assert.equal(component.sheetOpen, true);
  assert.equal(form.querySelector('[name="description"]').value, 'Three reasons');
  assert.equal(events.ideaChanged, 0);
  assert.deepEqual(events.toasts, []);
  assert.equal(component.ideaSaving, false);
});

test('nothing is sent while a picture is still going up', async () => {
  const { win, component, form } = ideaSheet();
  const calls = answers(win);
  component.ideaUploads = 1;

  await component.saveIdea({ target: form });

  assert.equal(calls.length, 0);
});

// ── New > Idea from the phone drawer (T18's review) ──────────────────────────────────────────────
// Where the sheet is, base.html's New > Idea sends new-post:open with {mode: 'idea'} from inside the
// open phone drawer. open() closes the drawer first, but the drawer's own trap hands focus back to its
// button as it lets go, and in the browser that can land just after the sheet put focus in its field
// (tests/e2e/self/phone-menu-focus.spec.ts). The field takes it back once; nothing else is pulled in.

test('opened from the open phone drawer, the field keeps focus when the drawer hands it back', () => {
  const { win, component } = ideaSheet();
  win.HTMLElement.prototype.getClientRects = function () { return [{}]; }; // jsdom lays nothing out
  const drawerButton = win.document.createElement('button');
  const item = win.document.createElement('button');
  win.document.body.append(drawerButton, item);
  const title = win.document.querySelector('[data-testid="idea-title"]');
  component.mobileMenuOpen = true;
  item.focus();

  win.dispatchEvent(new win.CustomEvent('new-post:open', { detail: { mode: 'idea' } }));
  assert.equal(component.mobileMenuOpen, false);
  assert.equal(component.sheetMode, 'idea');
  assert.equal(win.document.activeElement, title);

  drawerButton.focus(); // the drawer's trap, letting go
  assert.equal(win.document.activeElement, title);
  drawerButton.focus(); // once only: from here the sheet's own trap keeps focus in
  assert.equal(win.document.activeElement, drawerButton);
});

test('opened with the drawer closed, nothing pulls focus back', () => {
  const { win, component } = ideaSheet();
  win.HTMLElement.prototype.getClientRects = function () { return [{}]; };
  const elsewhere = win.document.createElement('button');
  win.document.body.append(elsewhere);
  const title = win.document.querySelector('[data-testid="idea-title"]');

  component.open({ mode: 'idea' });
  assert.equal(win.document.activeElement, title);
  elsewhere.focus();
  assert.equal(win.document.activeElement, elsewhere);
});
