// Wait until a part of the page has finished appearing: the element and every ancestor fully
// opaque, and no finite animation or transition still running in the document.
//
// axe measures colour contrast with the computed opacity, so a check that starts while a swapped-in
// list fades in (the Publish tabs' and the calendar grid's slide-in, a toast's entrance, a dialog's
// fade) can report a contrast failure that does not exist at rest. Playwright counts an element at
// opacity 0 as visible, so toBeVisible() does not wait for it. Infinite animations (spinners) never
// end and are left out.
//
//   await settled(page.getByTestId('approvals-list'), 'the reloaded Approvals list');
//   await axe(page, 'Approvals list');
import { type Locator, expect } from '@playwright/test';

export async function settled(locator: Locator, what: string): Promise<void> {
  // A missing element fails here with Playwright's own "element(s) not found", not as a poll timeout.
  await expect(locator, `${what} is on the page`).toBeAttached();
  await expect
    .poll(
      () =>
        locator.evaluate((element) => {
          let opacity = 1;
          for (let node: Element | null = element; node; node = node.parentElement) {
            opacity *= Number(getComputedStyle(node).opacity);
          }
          const moving = document
            .getAnimations()
            .filter((animation) => animation.playState === 'running')
            .filter((animation) => Number.isFinite(Number(animation.effect?.getComputedTiming().endTime))).length;
          return { opacity, moving };
        }),
      { message: `${what} finished appearing (fully opaque, nothing still animating)`, timeout: 10_000 },
    )
    .toEqual({ opacity: 1, moving: 0 });
}
