// The shell pair (spec D9, plan T12): Home, Approvals and Calendar month, light, at 390 x 844 and
// 1440 x 900, for the owner's sign-off. Nothing is compared and nothing is committed: the images go
// to test-results/pairs/00-shell/<side>/ and are attached to the pull request.
//
//   # before: a server started in a worktree of main (tests/e2e/README.md, Pairs)
//   E2E_PORT=<main's port> PAIR_SIDE=before npm run pairs -- tests/e2e/pairs/00-shell.pair.ts
//   # after: this branch's server (started for you on E2E_PORT when none is running)
//   E2E_PORT=<this branch's port> npm run pairs -- tests/e2e/pairs/00-shell.pair.ts
import { test } from '../support/test';
import { ensurePairData, pairSide, shootState, type PairState } from './support';

const PAIR = '00-shell';
const side = pairSide();

if (side === 'before') {
  // Main (045978b): only hooks that exist there, the session and publishing fixtures and these test ids.
  test.describe('before: main', () => {
    const states: PairState[] = [
      { name: 'home', path: (ws) => `/workspace/${ws}/studio/`, hook: 'home-today' },
      { name: 'approvals', path: (ws) => `/workspace/${ws}/approvals/`, hook: 'approvals-list' },
      { name: 'calendar-month', path: (ws) => `/workspace/${ws}/calendar/?mode=calendar&view=month`, hook: 'calendar-shell' },
    ];
    for (const state of states) {
      test(state.name, async ({ page, as, harness }, testInfo) => {
        await as('owner');
        await ensurePairData(page, harness);
        await shootState(page, testInfo, { pair: PAIR, side, state, workspace: harness.ids.workspace_a });
      });
    }
  });
} else {
  // This branch. A screen that changes one of these states names its own hook here; until that
  // hook is on the page the state fails instead of writing an image of the wrong screen.
  test.describe('after: this branch', () => {
    const states: PairState[] = [
      { name: 'home', path: (ws) => `/workspace/${ws}/studio/`, hook: 'home-today' },
      { name: 'approvals', path: (ws) => `/workspace/${ws}/approvals/`, hook: 'approvals-list' },
      { name: 'calendar-month', path: (ws) => `/workspace/${ws}/calendar/?mode=calendar&view=month`, hook: 'calendar-shell' },
    ];
    for (const state of states) {
      test(state.name, async ({ page, as, harness }, testInfo) => {
        await as('owner');
        await ensurePairData(page, harness);
        await shootState(page, testInfo, { pair: PAIR, side, state, workspace: harness.ids.workspace_a });
      });
    }
  });
}
