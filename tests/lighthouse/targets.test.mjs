import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { SEEDED_WORKSPACE, validateTarget } from './budgets.mjs';
import { TARGETS, selectTargets, targetOption } from './targets.mjs';

const config = JSON.parse(await readFile(new URL('../../.lighthouserc.json', import.meta.url), 'utf8'));
const origin = 'http://127.0.0.1:8151';
const target = (fields) => ({ name: 'probe', path: `${SEEDED_WORKSPACE}studio/`, testId: 'home-today', async interact() {}, ...fields });

test('with no selection the runner measures the three CI targets, in .lighthouserc.json\'s order', () => {
  for (const value of [undefined, '', '  ']) {
    const selected = selectTargets(value, config);
    assert.deepEqual(selected.map((entry) => entry.path), config.ci.collect.url);
    assert.deepEqual(selected.map((entry) => entry.name), ['home', 'approvals', 'calendar']);
    assert.deepEqual(selected.map((entry) => entry.testId), ['home-today', 'approvals-list', 'calendar-shell']);
  }
});

test('the default selection fails closed when a CI URL has no registered target', () => {
  const moved = structuredClone(config);
  moved.ci.collect.url[2] = `${SEEDED_WORKSPACE}calendar/`;
  assert.throws(() => selectTargets(undefined, moved), /no Lighthouse target/);
});

test('named targets are measured in the order given, each once', () => {
  assert.deepEqual(selectTargets('calendar,home', config).map((entry) => entry.name), ['calendar', 'home']);
  assert.deepEqual(selectTargets(' approvals , calendar ', config).map((entry) => entry.name), ['approvals', 'calendar']);
  assert.throws(() => selectTargets('home,home', config), /once/);
  assert.throws(() => selectTargets('home,,calendar', config), /separated by commas/);
  assert.throws(() => selectTargets('home,', config), /separated by commas/);
});

test('an unknown name is refused before anything is measured', () => {
  for (const name of ['inbox', 'Home', 'home ', '../home', 'home-1']) {
    assert.throws(() => validateTarget(name, TARGETS), /Unknown Lighthouse target/, name);
  }
  assert.throws(() => selectTargets('home,inbox', config), /Unknown Lighthouse target "inbox"/);
  assert.throws(() => validateTarget(undefined, TARGETS), /Unknown Lighthouse target/);
});

test('a path outside the seeded workspace is refused; public and portal pages wait for screens 10 and 11', () => {
  const outside = [
    '/portal/',
    '/portal/approvals/',
    '/',
    '/how-it-works/',
    '/request-invite/',
    '/accounts/login/',
    '/workspace/00000000-0000-4000-8000-00000000000b/studio/',
    '/workspace/00000000-0000-4000-8000-00000000000a',
    'workspace/00000000-0000-4000-8000-00000000000a/studio/',
    'https://example.com/workspace/00000000-0000-4000-8000-00000000000a/studio/',
    '//example.com/workspace/00000000-0000-4000-8000-00000000000a/studio/',
  ];
  for (const path of outside) {
    assert.throws(() => validateTarget('probe', [target({ path })]), /seeded workspace.*public and portal/s, path);
  }
  const disguised = [
    `${SEEDED_WORKSPACE}../../portal/`,
    `${SEEDED_WORKSPACE}%2e%2e/%2E%2E/portal/`,
    `${SEEDED_WORKSPACE}studio\\..\\..\\portal/`,
    `${SEEDED_WORKSPACE}studio/#new-post`,
    `${SEEDED_WORKSPACE}studio/ `,
  ];
  for (const path of disguised) {
    assert.throws(() => validateTarget('probe', [target({ path })]), /exactly/, path);
  }
  for (const path of [undefined, 42]) {
    assert.throws(() => validateTarget('probe', [target({ path })]), /seeded workspace/, String(path));
  }
});

test('a target needs a slug name, a ready test id and an interaction, and is registered once', () => {
  assert.equal(validateTarget('probe', [target({})]).name, 'probe');
  assert.throws(() => validateTarget('probe', [target({}), target({})]), /registered twice/);
  assert.throws(() => validateTarget('Probe', [target({ name: 'Probe' })]), /slug/);
  assert.throws(() => validateTarget('a/b', [target({ name: 'a/b' })]), /slug/);
  for (const testId of [undefined, '', 'has space', 42]) {
    assert.throws(() => validateTarget('probe', [target({ testId })]), /test id/, String(testId));
  }
  for (const interact of [undefined, 'click', {}]) {
    assert.throws(() => validateTarget('probe', [target({ interact })]), /interaction/, String(interact));
  }
});

test('every registered target is valid, uniquely named and cannot be changed by its callers', () => {
  assert.ok(Object.isFrozen(TARGETS));
  assert.equal(new Set(TARGETS.map((entry) => entry.name)).size, TARGETS.length);
  for (const entry of TARGETS) {
    assert.equal(validateTarget(entry.name, TARGETS), entry);
    assert.ok(Object.isFrozen(entry), entry.name);
  }
});

test('the command line, then LIGHTHOUSE_TARGETS, chooses the targets; anything else is refused', () => {
  assert.equal(targetOption([], {}), undefined);
  assert.equal(targetOption(['--targets=home,calendar'], {}), 'home,calendar');
  assert.equal(targetOption([], { LIGHTHOUSE_TARGETS: 'calendar' }), 'calendar');
  assert.equal(targetOption(['--targets=home'], { LIGHTHOUSE_TARGETS: 'calendar' }), 'home');
  // The manual workflow passes an empty input through: the three CI targets.
  assert.equal(targetOption(['--targets='], { LIGHTHOUSE_TARGETS: 'calendar' }), '');
  assert.throws(() => targetOption(['--targets', 'home'], {}), /Unknown argument/);
  assert.throws(() => targetOption(['--target=home'], {}), /Unknown argument/);
  assert.throws(() => targetOption(['--targets=home', '--targets=calendar'], {}), /once/);
});

// A page that records each input by test id, so a change to what a target measures shows here.
function recordingPage({ visible = true, ok = true } = {}) {
  const steps = [];
  const predicates = [];
  const locator = (id) => ({
    getByTestId: (child) => locator(`${id} > ${child}`),
    first: () => locator(`${id}:first`),
    async click() { steps.push(`click ${id}`); },
    async waitFor(options) { steps.push(`wait ${id}${options?.state ? ` ${options.state}` : ''}`); },
    async pressSequentially(text) { steps.push(`type ${id} ${text}`); },
    async press(key) { steps.push(`press ${id} ${key}`); },
    async isVisible() { steps.push(`visible? ${id}`); return visible; },
  });
  const page = {
    getByTestId: (id) => locator(id),
    waitForResponse(predicate) { predicates.push(predicate); return Promise.resolve({ ok: () => ok }); },
  };
  return { page, steps, predicates };
}

// The New post sheet (Phase 3, screen 1, T23): its own button opens it (floating on a phone, in the
// header on a desktop), Ask the team takes a few words, Save it as an idea instead shows the idea form,
// and the emoji picker's first opening, a search and a choice are measured before Back to New post.
const SHEET_IDEA_EMOJI = [
  'click new-post-open',
  'wait new-post-sheet visible',
  'type new-post-team-idea Site visits this Saturday',
  'click new-post-save-idea',
  'click idea-emoji-toggle',
  'wait idea-emoji-option:first',
  'type idea-emoji-search sparkles',
  'click idea-emoji-option',
  'click idea-close',
];
const timezone = (select) => [
  `click ${select} > ui-select-toggle`,
  `wait ${select} > ui-select-option-UTC visible`,
  `click ${select} > ui-select-option-UTC`,
  `click ${select} > ui-select-toggle`,
  `wait ${select} > ui-select-option-UTC visible`,
  `press ${select} > ui-select-toggle Escape`,
];
const byName = Object.fromEntries(TARGETS.map((entry) => [entry.name, entry]));

test('the CI targets keep the inputs the runner measured before they moved, the New post sheet in the old menu\'s place', async () => {
  const expected = {
    home: [
      'click thread-composer-body',
      'type thread-composer-body Plan next week',
      'press thread-composer-body ControlOrMeta+A',
      'press thread-composer-body Backspace',
      ...SHEET_IDEA_EMOJI,
    ],
    approvals: [
      ...timezone('ui-select-displayTimezone'),
      'click approvals-row-42 > approvals-row-details',
      'click approvals-row-42 > approvals-row-details',
    ],
    calendar: [
      ...timezone('ui-select-calendarFilters.tz'),
      'click calendar-mode-list',
      'click calendar-mode-calendar',
      'wait calendar-shell',
      ...SHEET_IDEA_EMOJI,
    ],
  };
  for (const [name, steps] of Object.entries(expected)) {
    const recorded = recordingPage();
    await byName[name].interact(recorded.page, { origin, reviewId: 42 });
    assert.deepEqual(recorded.steps, steps, name);
  }
});

test('Home and Calendar open the New post sheet; Approvals has no trigger and touches neither it nor the old menu', async () => {
  // The shell's New menu left with T19; the sheet's button is on the page itself at every width, so
  // no target opens the phone drawer to reach it.
  for (const visible of [true, false]) {
    for (const entry of TARGETS) {
      const { page, steps } = recordingPage({ visible });
      await entry.interact(page, { origin, reviewId: 42 });
      const touched = steps.join('\n');
      assert.doesNotMatch(touched, /sidebar-new-|mobile-menu-toggle/, entry.name);
      if (entry.name === 'approvals') {
        assert.doesNotMatch(touched, /new-post-|idea-/, entry.name);
        continue;
      }
      const opened = steps.indexOf('click new-post-open');
      assert.ok(opened >= 0, `${entry.name} presses New post`);
      assert.equal(steps[opened + 1], 'wait new-post-sheet visible', `${entry.name} waits for the sheet before typing in it`);
      assert.ok(steps.indexOf('click new-post-save-idea') > opened, `${entry.name} reaches the idea form through the sheet`);
      assert.equal(steps.at(-1), 'click idea-close', entry.name);
    }
  }
});

test('the filter and mode switches wait for this server\'s answers and fail when one fails', async () => {
  const response = (url) => ({ url: () => url });
  const approvals = recordingPage();
  await byName.approvals.interact(approvals.page, { origin, reviewId: 42 });
  const [filtered] = approvals.predicates;
  assert.equal(filtered(response(`${origin}/workspace/a/approvals/?tz=UTC`)), true);
  assert.equal(filtered(response(`${origin}/workspace/a/approvals/?tz=Asia%2FKolkata`)), false);
  assert.equal(filtered(response('http://127.0.0.1:9999/workspace/a/approvals/?tz=UTC')), false);

  const calendar = recordingPage();
  await byName.calendar.interact(calendar.page, { origin, reviewId: 42 });
  const [, list, back] = calendar.predicates;
  assert.equal(list(response(`${origin}/workspace/a/calendar/?mode=list&_switch_mode=1`)), true);
  assert.equal(back(response(`${origin}/workspace/a/calendar/?mode=calendar&_switch_mode=1`)), true);
  assert.equal(list(response(`${origin}/workspace/a/calendar/?mode=list`)), false);

  await assert.rejects(byName.approvals.interact(recordingPage({ ok: false }).page, { origin, reviewId: 42 }), /Timezone filter failed/);
  await assert.rejects(byName.calendar.interact(recordingPage({ ok: false }).page, { origin, reviewId: 42 }), /Timezone filter failed/);
});
