// The pages the Lighthouse runner measures (spec D10, plan T11). Each target is
// { name, path, testId, interact(page, ctx) }: the page in the seeded workspace, the test id that says
// it is ready, and the real inputs measured on it at 4x CPU slowdown (`ctx` is { origin, reviewId }:
// the server's origin and the review fixture's post id). Reports are written under the target's name.
//
// The first three are CI's targets and are paired with .lighthouserc.json's URLs by path; with no
// selection the runner measures them in that file's order. A screen adds its targets here at its gate
// and names them with --targets=a,b or LIGHTHOUSE_TARGETS. This module imports neither Lighthouse nor
// a browser, so its tests run in Node alone.
import { SEEDED_WORKSPACE, validateTarget } from './budgets.mjs';

async function timezoneFilter(page, selectTestId, origin) {
  // Closed filters defer their option bindings. Measure the first opening,
  // a real selection and reopening at the same CPU slowdown as other inputs.
  const timezone = page.getByTestId(selectTestId);
  const toggle = timezone.getByTestId('ui-select-toggle');
  await toggle.click();
  await timezone.getByTestId('ui-select-option-UTC').waitFor({ state: 'visible' });
  const filtered = page.waitForResponse((response) => response.url().startsWith(origin) && new URL(response.url()).searchParams.get('tz') === 'UTC');
  await timezone.getByTestId('ui-select-option-UTC').click();
  if (!(await filtered).ok()) throw new Error('Timezone filter failed.');
  await toggle.click();
  await timezone.getByTestId('ui-select-option-UTC').waitFor({ state: 'visible' });
  await toggle.press('Escape');
}

async function newIdeaEmoji(page) {
  // The picker now initializes only when opened. Include that first opening in
  // the interaction budget so load-time work cannot simply be moved out of sight.
  if (await page.getByTestId('mobile-menu-toggle').isVisible()) await page.getByTestId('mobile-menu-toggle').click();
  await page.getByTestId('sidebar-new-toggle').click();
  await page.getByTestId('sidebar-new-idea').click();
  await page.getByTestId('idea-emoji-toggle').click();
  await page.getByTestId('idea-emoji-option').first().waitFor();
  await page.getByTestId('idea-emoji-search').pressSequentially('sparkles', { delay: 40 });
  await page.getByTestId('idea-emoji-option').click();
  await page.getByTestId('idea-close').click();
}

export const TARGETS = Object.freeze([
  {
    name: 'home',
    path: `${SEEDED_WORKSPACE}studio/`,
    testId: 'home-today',
    async interact(page) {
      const composer = page.getByTestId('thread-composer-body');
      await composer.click();
      await composer.pressSequentially('Plan next week', { delay: 40 });
      await composer.press('ControlOrMeta+A');
      await composer.press('Backspace');
      await newIdeaEmoji(page);
    },
  },
  {
    name: 'approvals',
    path: `${SEEDED_WORKSPACE}approvals/`,
    testId: 'approvals-list',
    async interact(page, { origin, reviewId }) {
      await timezoneFilter(page, 'ui-select-displayTimezone', origin);
      const details = page.getByTestId(`approvals-row-${reviewId}`).getByTestId('approvals-row-details');
      await details.click();
      await details.click();
      await newIdeaEmoji(page);
    },
  },
  {
    name: 'calendar',
    path: `${SEEDED_WORKSPACE}calendar/?mode=calendar&view=month`,
    testId: 'calendar-shell',
    async interact(page, { origin }) {
      await timezoneFilter(page, 'ui-select-calendarFilters.tz', origin);
      const listResponse = page.waitForResponse((response) => response.url().includes('_switch_mode=1'));
      await page.getByTestId('calendar-mode-list').click();
      if (!(await listResponse).ok()) throw new Error('Calendar list switch failed.');
      const calendarResponse = page.waitForResponse((response) => response.url().includes('_switch_mode=1'));
      await page.getByTestId('calendar-mode-calendar').click();
      if (!(await calendarResponse).ok()) throw new Error('Calendar mode switch failed.');
      await page.getByTestId('calendar-shell').waitFor();
      await newIdeaEmoji(page);
    },
  },
].map((target) => Object.freeze(target)));

// CI's targets: one registered target per .lighthouserc.json URL, in that file's order.
function ciTargets(config, registry) {
  return config.ci.collect.url.map((path) => {
    const target = registry.find((candidate) => candidate.path === path);
    if (!target) throw new Error(`CI measures ${path}, but no Lighthouse target has that path.`);
    return validateTarget(target.name, registry);
  });
}

// The targets to measure: CI's three when nothing is named (or the name list is empty), otherwise
// each named target once, in the order given. Anything unknown is refused before a page is opened.
export function selectTargets(value, config, registry = TARGETS) {
  if (value === undefined || !value.trim()) return ciTargets(config, registry);
  const names = value.split(',').map((name) => name.trim());
  if (names.some((name) => !name)) throw new Error('Name each Lighthouse target, separated by commas.');
  if (new Set(names).size !== names.length) throw new Error('Name each Lighthouse target once.');
  return names.map((name) => validateTarget(name, registry));
}

// --targets=a,b on the command line wins; otherwise LIGHTHOUSE_TARGETS. Any other argument is refused,
// so a mistyped option never silently measures the defaults.
export function targetOption(argv, env) {
  let value;
  for (const argument of argv) {
    if (!argument.startsWith('--targets=')) {
      throw new Error(`Unknown argument ${JSON.stringify(argument.slice(0, 60))}; name targets with --targets=a,b.`);
    }
    if (value !== undefined) throw new Error('Give --targets once.');
    value = argument.slice('--targets='.length);
  }
  return value ?? env.LIGHTHOUSE_TARGETS;
}
