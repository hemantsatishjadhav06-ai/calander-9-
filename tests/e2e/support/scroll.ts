import type { Locator } from '@playwright/test';

/** Send one native scroll key and wait for that scroll to finish before the next action. */
export async function scrollWithKey(region: Locator, key: 'PageDown' | 'ArrowRight'): Promise<void> {
  // Returning a handle acknowledges listener installation before sending the key.
  const pending = await region.evaluateHandle((element) => {
    let cleanup = () => {};
    const completed = new Promise<void>((resolve, reject) => {
      const onEnd = (event: Event) => {
        if (event.target !== element) return;
        cleanup();
        resolve();
      };
      const timeout = window.setTimeout(() => {
        cleanup();
        reject(new Error('The keyboard scroll did not emit scrollend within 5 seconds.'));
      }, 5_000);
      cleanup = () => {
        window.clearTimeout(timeout);
        element.removeEventListener('scrollend', onEnd);
      };
      element.addEventListener('scrollend', onEnd);
    });
    // Keep an early rejection handled; awaiting the original promise below still fails the test.
    completed.catch(() => undefined);
    return { completed, dispose: () => cleanup() };
  });
  try {
    await region.press(key);
    await pending.evaluate(({ completed }) => completed);
  } finally {
    await pending.evaluate(({ dispose }) => dispose());
    await pending.dispose();
  }
}
