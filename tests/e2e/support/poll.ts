// Waiting for the worker: read a probe until a condition holds, then assert on what was read last.
//
//   const asked = await until(read, (s) => s.ask?.status === 'done' || s.ask?.status === 'failed', 'the manager answers');
//   expect(asked.ask?.status).toBe('done');
//
// Stop on the failure states too, so a failed job ends the wait at once and the assertion after it
// names the state, instead of the timeout naming only what was awaited.
import { expect } from '@playwright/test';

/** Read until `ready` holds (or `timeout` ends the test with `message`), and return what was read last. */
export async function until<T>(
  read: () => Promise<T>,
  ready: (value: T) => boolean,
  message: string,
  timeout = 60_000,
): Promise<T> {
  let value: T | undefined;
  await expect
    .poll(
      async () => {
        value = await read();
        return ready(value);
      },
      { message, timeout, intervals: [250, 500, 1_000] },
    )
    .toBe(true);
  return value as T;
}
