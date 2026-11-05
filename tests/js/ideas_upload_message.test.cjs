// The Ideas page's refused upload (templates/composer/create_landing.html, kanbanBoard's ideaHelpers):
// composer:idea_upload_media answers a refused file with 400 {"error": upload_rejection_message(e)}
// (wrong type, too large, quota), and the create and edit idea dialogs alert that sentence
// (err.userMessage) instead of the generic one. Until Phase 3 T19 the page ran base.html's
// window.ideaModalHelpers, which carried the reason; T19 removed it, so the page's own helpers must.
// The helpers are read from the template and run in a jsdom page against a mocked fetch.
// Requires the locked development dependencies; this makes no network requests.
// npm ci --ignore-scripts && npm run test:ui
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const template = fs.readFileSync(path.resolve(__dirname, '../../templates/composer/create_landing.html'), 'utf8');
const UPLOAD_URL = '/workspace/3f1c2a9e-0000-4000-8000-000000000001/ideas/upload-media/';
const GENERIC = 'One of the files failed to upload. Please try again.';

/** The source of `const ideaHelpers = …;`, up to the semicolon that closes its outermost braces. */
function helpersSource() {
  const start = template.indexOf('const ideaHelpers = ');
  assert.notEqual(start, -1, 'create_landing.html defines const ideaHelpers');
  let depth = 0;
  let quote = '';
  for (let i = start; i < template.length; i += 1) {
    const ch = template[i];
    if (quote) {
      if (ch === '\\') i += 1;
      else if (ch === quote) quote = '';
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') quote = ch;
    else if (ch === '{') depth += 1;
    else if (ch === '}') depth -= 1;
    else if (ch === ';' && depth === 0) return template.slice(start, i + 1);
  }
  throw new Error('const ideaHelpers has no closing semicolon');
}

/** The page's helpers in a page with a CSRF field, fetch answering with `answer`. */
function page(t, answer) {
  const source = helpersSource();
  assert.doesNotMatch(source, /\{%|\{\{/, 'the helpers carry no template syntax, so they run as written');
  const dom = new JSDOM('<input type="hidden" name="csrfmiddlewaretoken" value="token-1">', {
    runScripts: 'outside-only',
    url: 'https://example.test/workspace/one/create/',
  });
  const win = dom.window;
  t.after(() => win.close());
  const calls = [];
  win.fetch = (url, init) => {
    calls.push({ url, init });
    return Promise.resolve(answer);
  };
  const helpers = win.eval(`(function () { ${source} return ideaHelpers; })()`);
  return { win, helpers, calls };
}

function file(win) {
  return new win.File(['x'], 'notes.txt', { type: 'text/plain' });
}

async function refusal(promise) {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('the upload was expected to be refused');
}

test("a refused file rejects with the server's sentence as its userMessage", async (t) => {
  const answer = { ok: false, status: 400, json: () => Promise.resolve({ error: 'That file is too large.' }) };
  const { win, helpers, calls } = page(t, answer);
  const uploaded = [];

  const error = await refusal(helpers.uploadIdeaMediaAsset(UPLOAD_URL, file(win), (data) => uploaded.push(data)));

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, UPLOAD_URL);
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers['X-CSRFToken'], 'token-1');
  assert.equal(error.message, 'upload_failed');
  assert.equal(error.userMessage, 'That file is too large.');
  assert.equal((error && error.userMessage) || GENERIC, 'That file is too large.', 'the dialog alerts the reason');
  assert.deepEqual(uploaded, []);
});

test('a refusal without a readable body leaves the generic sentence to the dialog', async (t) => {
  const answer = { ok: false, status: 502, json: () => Promise.reject(new SyntaxError('Unexpected token <')) };
  const { win, helpers } = page(t, answer);

  const error = await refusal(helpers.uploadIdeaMediaAsset(UPLOAD_URL, file(win)));

  assert.equal(error.message, 'upload_failed');
  assert.ok(!error.userMessage);
  assert.equal((error && error.userMessage) || GENERIC, GENERIC);
});

test('an accepted file is handed to the dialog once', async (t) => {
  const data = { asset_id: 'a-1', url: '/media/a.png', filename: 'a.png', media_type: 'image' };
  const { win, helpers } = page(t, { ok: true, status: 200, json: () => Promise.resolve(data) });
  const items = [];

  const done = await helpers.uploadIdeaMediaAsset(UPLOAD_URL, file(win), (answer, uploadedFile) => {
    helpers.appendUploadedMedia(items, answer, uploadedFile);
    helpers.appendUploadedMedia(items, answer, uploadedFile);
  });

  assert.equal(done, true);
  assert.equal(items.length, 1);
  assert.equal(items[0].asset_id, 'a-1');
  assert.equal(helpers.mediaAssetIdsCsv(items), 'a-1');
});

test("the page runs its own helpers: nothing on window is consulted", (t) => {
  const source = helpersSource();
  assert.doesNotMatch(source, /window\.ideaModalHelpers/, 'nothing defines window.ideaModalHelpers since T19');
  const { win } = page(t, { ok: true, json: () => Promise.resolve({}) });
  win.ideaModalHelpers = { uploadIdeaMediaAsset: () => 'shadowed' };
  const helpers = win.eval(`(function () { ${source} return ideaHelpers; })()`);
  assert.notEqual(helpers, win.ideaModalHelpers);
});
