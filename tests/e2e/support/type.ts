// The running-text size (Phase 3, spec D3): 16 px below 1024 px and 15 px from 1024 px, the body token
// (`--read-size` in styles.css, on <body> and as `text-read`). Running text sets its own size (a thread
// message, a caption, a row title), so <body> alone proves nothing: each screen's spec calls this on
// the running-text elements it names.
import type { Locator } from '@playwright/test';

import { expect } from './test';

/** The body token for a viewport this wide: what running text must compute. */
export function readSize(viewportWidth: number): number {
  return viewportWidth < 1024 ? 16 : 15;
}

/** Every element *locator* matches computes the body token's size for the page's current width. */
export async function expectReadSize(locator: Locator, what = 'running text'): Promise<void> {
  const width = await locator.page().evaluate(() => window.innerWidth);
  const expected = readSize(width);
  const count = await locator.count();
  expect(count, `${what}: at least one element to measure`).toBeGreaterThan(0);
  for (let index = 0; index < count; index += 1) {
    const size = await locator.nth(index).evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
    expect(size, `${what} (${index + 1} of ${count}) reads at ${expected}px at ${width}px wide`).toBe(expected);
  }
}
