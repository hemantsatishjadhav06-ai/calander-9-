// Axe on every screen a test reaches (and on each dialog it opens): WCAG 2.2 AA, failing on any
// serious or critical violation with the rule, the impact, the elements and the help page. It waits
// for transitions to finish first, so a menu that fades in is read at its final colours.
import AxeBuilder from '@axe-core/playwright';
import type { Page, TestInfo } from '@playwright/test';

export const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const BLOCKING = new Set(['serious', 'critical']);
/** How long to wait for running transitions and animations before checking anyway. */
const SETTLE_TIMEOUT_MS = 3_000;

export type AxeResults = Awaited<ReturnType<AxeBuilder['analyze']>>;
type Violation = AxeResults['violations'][number];

export type AxeOptions = {
  /** Check only this part of the page, for example an open dialog: '[role="dialog"]'. */
  include?: string;
  /** Leave these parts out (content the product does not own, such as a client's embedded page). */
  exclude?: string[];
};

export class AxeViolationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AxeViolationError';
  }
}

export function formatViolations(label: string, url: string, violations: Violation[]): string {
  const lines = [`axe: ${violations.length} serious or critical violation(s) on "${label}" (${url})`];
  for (const violation of violations) {
    lines.push(`- ${violation.id} (${violation.impact}): ${violation.help}`);
    lines.push(`  help: ${violation.helpUrl}`);
    for (const node of violation.nodes.slice(0, 10)) {
      lines.push(`  target: ${node.target.join(' ')}`);
    }
    if (violation.nodes.length > 10) {
      lines.push(`  ... and ${violation.nodes.length - 10} more element(s)`);
    }
  }
  return lines.join('\n');
}

/**
 * Wait until no finite transition or animation is running: two frames first, so a transition a click
 * has just asked for (Alpine starts one on the next frame) has begun. Endless ones (a spinner) are
 * left alone; after SETTLE_TIMEOUT_MS the check runs anyway.
 */
async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
  );
  await page
    .waitForFunction(
      () =>
        document.getAnimations().every((animation) => {
          const endless = animation.effect?.getComputedTiming().endTime === Infinity;
          return endless || (animation.playState !== 'running' && !animation.pending);
        }),
      undefined,
      { timeout: SETTLE_TIMEOUT_MS },
    )
    .catch(() => undefined);
}

export async function checkAccessibility(
  page: Page,
  label: string,
  testInfo?: TestInfo,
  options: AxeOptions = {},
): Promise<AxeResults> {
  await settle(page);
  let builder = new AxeBuilder({ page }).withTags(AXE_TAGS);
  if (options.include) {
    builder = builder.include(options.include);
  }
  for (const selector of options.exclude ?? []) {
    builder = builder.exclude(selector);
  }
  const results = await builder.analyze();
  if (testInfo) {
    await testInfo.attach(`axe ${label}`, {
      body: JSON.stringify({ url: results.url, violations: results.violations }, null, 2),
      contentType: 'application/json',
    });
  }
  const blocking = results.violations.filter((violation) => BLOCKING.has(violation.impact ?? ''));
  if (blocking.length > 0) {
    throw new AxeViolationError(formatViolations(label, page.url(), blocking));
  }
  return results;
}
