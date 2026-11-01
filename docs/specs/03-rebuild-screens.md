# 03 — Rebuild the nine screens

Phase 3 of [`docs/BETA_PLAN.md`](../BETA_PLAN.md). Written 1 Nov 2026 from the owner-confirmed cut in
[`00-cut.md`](00-cut.md), the Phase 2 decisions in [`02-cut-and-merge.md`](02-cut-and-merge.md), the plan's
section 4 (interface direction) and section 5 (the standards bar), and four read-only surveys of main
`045978b` (design system, creation paths, tests and the eleven screens). Gate, exactly as the Phase 3
section of `BETA_PLAN.md` writes it:

> Per screen: build at 390 px first; one primary action; dark mode; `prefers-reduced-motion`; run
> `impeccable` audit, `design-is` audit, axe, Lighthouse; screenshot into `tests/e2e/__screenshots__/`
> for the visual regression baseline.
>
> Gate per screen: axe 0 serious; Lighthouse ≥ 90 mobile; e2e for that screen green;
> `recolor.py --check` clean; owner sign-off on the screenshot pair (before/after).

The phase table in section 6 gives it two weeks and the gate "per screen: axe 0 serious · Lighthouse
≥ 90". The owner's rules on top: every screen is built at 390 px first, in light and dark, with one
primary action; the `impeccable` and `design-is` audits run on it; the owner signs off its before/after
pair **before the next screen starts**; its baseline goes into `tests/e2e/__screenshots__/` in a commit
whose message starts with `visual:`.

## Problem

Phase 2 cut the product to six places and a gear, but every screen still looks and behaves like the
desktop admin panel it was. On a 390 px phone, starting a post takes three taps (More → New → item);
Approvals shows each destination as text in a box behind a *Details* toggle; Calendar opens on a
seven-column month squeezed into the screen; body text is 14 px and 623 template uses (151 files)
are smaller than 13 px; cards have *less* padding on a phone (16 px) than on a desktop (20 px); and
there is no dark mode at all (no `prefers-color-scheme`, no `data-theme`, no `dark:` class anywhere).
The beta's buyer is a 22–35-year-old social media manager who judges the tool on a phone in 30
seconds. Phase 3 rebuilds what survived the
cut so that it reads as obvious there, without touching the approval gate, isolation or anything else
the nine invariants protect.

## Goals

1. **Eleven screens rebuilt, each gated.** In the plan's order: 1 New post sheet · 2 Home · 3 Approvals
   (swipe stack) · 4 Calendar · 5 Post page · 6 Inbox · 7 Analytics · 8 Activity · 9 Settings, the
   onboarding wizard and Go to search · 10 Client portal · 11 Marketing. Each passes its gate and has
   a signed-off pair.
2. **One way to start a post.** A Pine **New post** button on Home and Calendar opens one sheet (phone)
   or drawer (desktop) with *Ask the team* and *Write it myself*; one tap on a phone.
3. **Light and dark.** Dark mode follows the device by default on every rebuilt screen; contrast is
   checked by machine for both themes.
4. **Readable on a phone.** No text under 13 px; body text 16 px on phones and 15 px on desktops; an
   8 px spacing grid; cards 20 px / 24 px; one primary action per view, in the place D5 sets (its two
   departures from "always in the same place" are put to the owner).
5. **Nothing behind the screens changes.** The nine invariants, the URL contract, the golden e2e specs
   and the invariant tests are exactly as they were, and green.

## Non-goals

- **No change to the approval gate, fingerprints, publishing, isolation, budgets, Telegram or the
  untrusted-text wrappers.** `apps/approvals/gate.py`, `actor.py`, `apps/publisher/engine.py` and
  `apps/studio/services.approve` are not edited. A screen may only *show* what they decide.
- **No new URL parts and, by default, no new URLs** (D12). No new model fields.
- **No edits to the golden e2e specs or to any test that enforces a `CLAUDE.md` invariant.** If a
  rebuild breaks one, the rebuild is wrong.
- **Pages outside the nine screens are not redesigned**: blog, media library, templates, categories,
  queues, posting schedule, organisation pages, sign-in and account pages, Telegram settings, emails.
  They get the shared foundation changes (type floor, card padding, the dark-mode codemod) and stay
  light until each passes a dark axe run (D2); R3 schedules that run before the phase gate, subject to
  the owner's answer in the open questions.
- **No new web font host** and no font that `font-src 'self'` would refuse.
- **No Phase 4 work** (2FA, i18n sweep, privacy pages); golden path 12 stays pending.

## Who it is for

| Person | What changes for them |
|---|---|
| Manager / approver on a phone | Approvals as a stack: one post at a time, real-size preview, *Approve & schedule* within thumb reach; a 16 px body |
| Staff who make posts | One **New post** button on Home and Calendar; *Ask the team* or *Write it myself*; Calendar opens on an agenda |
| Agency owner | A four-step start for a fresh workspace; Settings → Advanced → *Features* writes the switches |
| Plain client | The portal in three parts: what waits for them, what went live, a chat with the team |
| Viewer | Reads as before; no longer sees a New menu whose every link answers 403 |
| Someone signed out | A dark-hero marketing Home with an inline invite form |

## Decisions

These resolve the conflicts the surveys found between `BETA_PLAN.md` section 4 and tests that must
not be edited. Each has a default so nothing blocks; the open questions below list the ones the owner
may overrule.

**D1. Order and gating.** Foundations (F, below) come first and have their own gate (a pair of the
shell on Home, Approvals and Calendar). Then the eleven screens in the plan's order. A screen is *done*
when every item of its gate passes and the owner has signed off its pair; the next screen's
implementation starts only after that. One phase branch and one draft PR; each screen ends with a
`visual:` commit and an entry in `docs/specs/CHANGELOG.md` recording the tested commit, the commands,
the audit findings and their fixes, the Lighthouse medians and the link to the sign-off. Nothing is
merged or released until the owner authorises it (`CLAUDE.md`). The per-screen gate checklist is:

1. built at 390 px (the `iphone-13` project) first, then widened to 1440 px;
2. light and dark both pass (D2);
3. at most one solid Pine primary per view (D5, a test);
4. every new motion has its reduced-motion equivalent (D7);
5. `impeccable` audit and `design-is` audit run; must-fix findings fixed before the pair is taken;
6. axe: 0 serious or critical findings (WCAG 2.2 AA tags), light and dark, three devices;
7. Lighthouse mobile ≥ 90 on the screen's target, with every other budget in `.lighthouserc.json` (D10);
8. e2e for that screen green on three devices in CI (`CI=1`, WebKit for iPhone 13), zero retries;
9. `python tools/recolor.py --check` says "nothing left to do" (extended by F1);
10. full pytest green with every protected invariant test unchanged, compared test by test (D11);
    ruff, mypy and the migration check clean;
11. baseline committed in a `visual:` commit;
12. the owner's sign-off on the before/after pair.

**D2. Dark mode.**
- *How it is chosen.* It follows the device (`prefers-color-scheme`) by default. A person can choose
  **System**, **Light** or **Dark** under *Appearance* in the account menu; the choice is kept on that
  device (local storage), so no new column. A short nonce'd script in `<head>` sets `data-theme` on
  `<html>` before the first paint (the CSP still allows no `'unsafe-inline'` script); without
  JavaScript the media query still applies.
- *Mechanism.* Layer 1 (the raw `ink`, `brand` and status scales) and Layer 2 (surfaces, borders,
  text, primary, focus, overlay, shadows, `color-scheme`) are redefined under the dark theme in
  `theme/static_src/src/styles.css`. Giving Layer 2 alone dark values would change almost nothing,
  because templates use colour utilities 3,761 times, 3,424 of them on the raw `ink`, `brand` and
  status scales (`text-ink-*` alone 2,075). Because the utilities are declared `@theme inline`, every
  `bg-ink-*`, `text-brand-*` and `ring-success-*` reads its variable where it is used, so those 3,424
  uses follow without edits. Each step keeps its role in both themes: `ink-50` is the canvas and
  `ink-950` the strongest text; `brand-700` is the primary fill and link; status 50 is the soft fill
  and 600 the chip text.
- *What does not follow, and is changed in F1 by a codemod:* `bg-white` (208, plus 34 with opacity)
  → `bg-surface`; `text-white` (99 uses; 54 class strings pair it with a dark fill) → a new on-fill
  token where it sits on a fill; the elements that stay dark in both themes (toast, tooltip, chart
  tip, selected filter chip, logo mark, `.hour-bar.is-now`, `.timeline-now`) → new inverse tokens;
  the literal colours in `styles.css` (`#fff` rules, `rgb(14 17 20 / …)` fills, shadows,
  `--surface-sticky`, `--overlay`, `--primary-halo`, `--text-inverse`, the pulse keyframes, the
  data-URI chevrons); and the Chart.js colours in
  `base.html` and `static/js/live_board.js`, which read CSS variables when they draw and redraw when
  the theme changes. The primary in dark is a lighter Pine fill with dark text through the on-fill
  token, as `DESIGN_SYSTEM.md` §21 planned (links brand-300, fill brand-500 with ink-950 text).
- *Dark surfaces inside light pages are decided one by one.* Templates use `bg-ink-800`, `-900` and
  `-950` as a solid fill 39 times in 25 files, against the seven elements named above. Because each
  step keeps its role, those fills turn light in dark, while white text, `bg-white/NN` dividers and
  `hover:bg-white/10` written on their children do not follow. The two selection bars show the
  failure: `calendar-bulk-bar` (`calendar.html:314-325`, "a dark surface, so white focus rings") and
  `approvals-bulk-bar` (`calendar/partials/publish_approvals.html:60-69`) would become light bars with
  white labels and invisible dividers. F1 inventories all 39 and records, for each, whether it is
  inverse (stays dark: both selection bars are) or flips; the codemod and `recolor.py --check` read the
  nearest ancestor's fill, not only the element's own class string, so `text-white`, `bg-white/NN` and
  `hover:bg-white/NN` under a fill that flips are rewritten or flagged.
- *What stays light:* emails and the standalone pages that do not load the stylesheet (legal, error,
  unsubscribe, accept invite) keep their literal hex; platform previews and creatives render the way
  the platform shows them. Because the scale utilities flip everywhere, a preview needs a scope that
  flips them back: F1 adds a light content scope (`[data-theme-scope="light"]`) that re-declares the
  light Layer 1 and Layer 2 values and `color-scheme: light`, checked by the contrast test to equal the
  light `:root`. The composer's previews (`composer/partials/preview_panel.html`, whose `bg-white`
  canvases and `bg-white/90` carousel buttons are the platform's look), the shared
  `components/post_preview.html` (screen 3) and creatives sit inside it and are left out of the
  `bg-white` rewrite; each screen that shows a preview asserts in dark that its computed background is
  still white.
- *Readiness per page.* Dark applies only to a page that declares itself ready, which it may do once
  its e2e passes axe in dark on three devices. Home and Calendar are declared in screen 1 (the sheet
  lives on them); every other screen at its own gate. An undeclared page renders light whatever the
  preference, so nobody meets an unchecked dark page. The checks find a page's templates through an
  explicit page-to-root-template map that a test keeps true by rendering each page.
- *Verification:* the October contrast scripts were not kept, so F1 adds a checker that reads Layer 1
  and Layer 2 for both themes and checks every pair in `DESIGN_SYSTEM.md` §23 plus the new dark pairs
  (text 4.5:1, large text and UI 3:1), run as a pytest. §21 ("Dark mode later") becomes the dark-mode
  section with its tables.

**D3. Type.**
- *Floor: 13 px, everywhere a person reads, from F2.* `--text-caption` (12 px) and
  `--text-micro` (11 px) move to 13 px; Tailwind's `--text-xs` is redefined to 13/18 so its 425 uses
  follow without edits; the 55 arbitrary `text-[12px]`, `[11px]`, `[10px]` and `[9px]` uses (the
  phone bar's labels among them), the 26 inline sizes and the 17 sub-13 px rules in `styles.css`
  (sidebar label and badge, pills, chips, table headers, owner box, stage labels, chart axis,
  timeline) are changed. The standalone pages that do not load the stylesheet (accept invite, the
  magic-link pages, legal, error, unsubscribe) are under the floor too: their literal colours stay, but
  their `font-size` rules do not go under 13 px (`members/accept_invite.html:41, 54, 90` set 12 px
  today, on the first page an invited beta owner sees). Chart text drawn on canvas is under it as well:
  the vendored Chart.js 4.4.6 defaults to 12 px and `bbInitHeroChart` (`base.html`) sets no size, so the
  Analytics axis and tooltip text are set to 13 px there and pinned by
  `tests/lighthouse/chart-init.test.mjs`; the live board's hour chart is DOM text sized by `styles.css`,
  which the guard already reads. A guard test fails on any size under 13 px in templates, the
  standalone pages included, static JS class strings and `styles.css`. Emails are the one exception,
  recorded as an owner question below. `marketing.css`'s 19 sub-13 px rules move in screen 11.
  `DESIGN_SYSTEM.md` §5 ("never smaller than 12px") changes to 13.
- *Body.* A responsive body token: 16/24 below 1024 px, 15/22 from 1024 px, set on `<body>`. Rebuilt
  screens use it for running text; `text-sm` (14 px) stays for dense desktop tables and meta and is
  not used for running text in a rebuilt screen. Inputs stay 16 px below 1024 px. Because running text
  sets its own size (thread messages are `text-body-lg`, 15 px, at `thread_messages.html:39, 75, 80, 86`;
  draft captions `text-sm` at `thread_draft.html:11`), measuring `<body>` proves nothing on its own:
  each screen's spec names its running-text elements (thread message body, row titles, captions, the
  Inbox message, the portal caption) and asserts their computed size, 16 px at 390 px and 15 px at
  1440 px.
- *Display face: the system font's display cut, 0 KB.* Headings use `system-ui` (which switches to the
  display optical size on Apple platforms from 20 px) with `"Segoe UI Variable Display"` ahead of
  `"Segoe UI"` for Windows; page titles 700 with −0.02 em tracking, the display size −0.03 em; h2 700;
  h3 700, all three in the display stack. 800 is not used: Segoe UI Variable and the one font file in
  the repository (`static/fonts/inter-latin-normal.woff2`, Inter, OFL, variable 400–700, 48,432 bytes,
  unreferenced) both stop at 700, and a synthesised heavier weight is worse than none. CSP
  `font-src 'self'` is unchanged.

**D4. Spacing.** Rebuilt templates space on 8 px steps (Tailwind 2, 4, 6, 8, 10, 12, 16, 20); 4 px
and 12 px (1 and 3) only inside a control or between an icon and its label; no `.5` steps and no `px`
spacing. `.ui-card` becomes 20 px below 1024 px and 24 px from 1024 px (today 16 px below 640 px and
20 px above, the reverse of the target); nested cards 16 px; 32 px between a screen's sections; page
padding unchanged (16 / 24 / 40). A guard test checks each rebuilt screen's templates for exactly this
rule: it flags odd integer steps (1, 3, 5, 7, 9, 11) outside a control or an icon-and-label pair,
`.5` steps, `px` spacing, and arbitrary values that are not multiples of 8 px. The 20 px card padding
is set in CSS (`.ui-card`), not by a utility, so it is not an exception the guard needs. Its list
grows by one screen at each gate.

**D5. One primary action, one place.** A shared `components/primary_action.html` renders the view's
single solid Pine button. Screen-level actions (New post) float bottom-right on a phone (56 px tall,
icon and label, 16 px from the edge, above the phone bar) and sit top-right in the page header from
1024 px. A decision about one item (the post page, an Approvals card, a portal card, the Inbox reply)
sits in a bottom bar within thumb reach on a phone, primary on the right, and at the end of the item
on a desktop; a Settings panel's Save sits at the end of its form. The floating button never covers a
toast, the selection bars or a sticky composer, and is never covered by them (WCAG 2.2, 2.4.11): it
hides while a selection bar shows and rises above a visible toast. Repeated row and card actions
(*Approve & schedule* in a list, *Go ahead* in the thread) are tinted. A watch-only screen (Activity,
Analytics) has no primary.
Two of these choices depart from `BETA_PLAN.md` section 4 ("always in the same place: bottom-right
floating on phone, top-right on desktop"): item and form decisions sit at the end of the item or form
on a desktop rather than top-right, and Activity and Analytics have no primary. Both are owner
questions below; until answered, they are the default. A test renders each rebuilt screen for each
role and checks the resting view: never more than one solid primary per breakpoint (a dialog or sheet
counts as its own view), and the primary in its place: a screen-level primary carries `.ui-fab` with
the `ABOVE_THE_BAR` placement below 1024 px and sits in the page header's primary slot from 1024 px;
an item decision sits inside its `data-decision-bar` on a phone.

**D6. The 2 px status border.** List rows take a `data-tone` from the one status mapping that
`studio/partials/status_badge.html` and `approvals/partials/_status_badge.html` already own, and draw a
2 px left border in that tone's 500 step. The row keeps its status pill (icon and word); the border
is an extra cue for scanning 20 rows, never the only one. Used in the Approvals list, the Calendar
list tabs and agenda, Inbox, Activity, the portal's decided list and the Analytics rows on phones.

**D7. Motion.** Micro-interactions take 160–200 ms (`--dur-fast`, and a new 200 ms token
`--dur-snap`): the approve fill, a message arriving (opacity and a 6 px rise, 200 ms instead of §8's
240 ms), the calendar chip's snap with its new time, a count stepping, a status cross-fade. Sheets and
drawers enter in 200 ms (`--dur-snap`, not §8's 320 ms) and leave at 70 % (140 ms). New motion in a
rebuilt screen uses only `--dur-fast` or `--dur-snap`; `--dur-base` (220 ms) and `--dur-slow` (320 ms)
stay for the pages that are not rebuilt. `DESIGN_SYSTEM.md` §12.3's approve sequence is rewritten to
match: the spinner shows while the request is in flight (its 300 ms minimum is a display time that
stops a flash, not motion, and stays); the button fills with the server's words in 200 ms; the 1.2 s
hold stays as reading time before the list reload replaces the row or card; the row collapse or the
card's exit takes 200 ms, not 220 ms; under reduced motion the fill and the exit are instant and the
words still show. Nothing decorative; no new loop. The global reduced-motion
rule (`styles.css`, reduced-motion block) stays; each screen's requirement names the reduced
equivalent of its new motion (instant swap or a text change); the baselines run with
`reducedMotion: 'reduce'`; a self spec checks that no transform transition runs on the sheet, the
approve fill or a new message under `reduce`. The seven template-local `@keyframes` and six local
reduced-motion blocks in rebuilt templates move into `styles.css`.

**D8. Empty states and inline confirms.** A shared `components/empty_state.html`: a 32 px line icon,
one sentence and one button (tinted or secondary; primary only when it is the screen's primary). The
empty states without a button today get one (Home's "Nothing yet", Approvals, Activity's routines,
the portal's lists). Every destructive or paid action on the eleven screens confirms inline, not in a
modal (no `hx-confirm`, no `confirm()`), and says what it removes or starts. A guard flags
`hx-confirm` and `confirm(` in each gated screen's templates. The actions, by screen (each screen's
Start task re-reads its tree and adds any it finds):

| Screen | Destructive | Paid (starts the team's work) |
|---|---|---|
| 1 New post | — | *Ask the team*'s Send (exempt, below) |
| 2 Home | — | thread *Send* and *Go ahead* (exempt, below) |
| 3 Approvals | bulk reject (today a modal) | — |
| 4 Calendar | bulk delete (today a modal from `calendar-bulk-bar`), event delete (`calendar/partials/event_form.html:71`, `confirm()`), the confirm modals | — |
| 5 Post page | *Stop and discard* and *Discard* (`studio/detail.html:33, 56, 357`, no confirm at all today) | *Retry* (`:51`), choosing an angle (`studio:use_angle`, `:175`), *Start over with three new angles* (`:343`), *Request changes* (`studio-revise-send`, exempt, below) |
| 6 Inbox | discard a draft reply (`inbox/partials/_draft_reply_item.html:40`, `hx-confirm`) | *Draft replies with the team* |
| 8 Activity | delete a routine (`studio/partials/routine_rows.html:47`, `confirm()`) | *Run now* (`routine_rows.html:36-39`), a job's retry and resume controls |
| 9 Settings | remove a member (`members/partials/member_row.html:75`), revoke an invitation (`invitation_row.html:35`, `client_portal/admin/partials/pending_invites_section.html:38`), revoke a portal link and remove a client (`client_portal/admin/partials/client_row.html:39, 49`), all `hx-confirm` today; the danger zone (its typed confirmation stays) | — |

*Exempt until the owner answers:* the goldens click *Go ahead* (02:156, 03:127), the thread's *Send*
(02:143, 03:101) and the post page's *Request changes* (06:197) and expect the work to start; an
inline confirm there would need a golden edit. These acts are already the person's deliberate step
(the manager's reply says what will be made before *Go ahead*), so they carry the line "This starts
the team's work and counts toward this month's allowance." beside the button instead of a confirm; the
open questions ask the owner to allow the golden edit or confirm the exemption.
*What a paid confirm says:* what work starts and that it counts toward the team's monthly allowance.
`BETA_PLAN.md` asks that it "says what it costs"; showing a money estimate there is an owner question
(invariant 9 bans token counts, model and vendor names in copy, not money). Default until answered: no
amount in the confirm; owners read amounts on Settings → Autopilot.
`test_a11y_sweep.py` keeps passing unedited: each remaining overlay is a labelled, trapped dialog,
and its "more than 10 dialogs" count does not hang on the modals that go, because the shell's own
dialogs (the notifications drawer and Go to, `base.html:959` and `:988`) render on the
swept pages; screen 1 re-runs the sweep to confirm once the idea dialogs leave `base.html`.

**D9. Visual baselines and the sign-off pair are two things.**
- *The pair* is for the owner: *before* (main, taken when the screen starts) and *after*, at 390 × 844
  and 1440 × 900, light (and dark for *after*), in the states listed per screen. It is attached to the
  PR; the sign-off is recorded in `CHANGELOG.md`.
- *The baseline* is for CI: `toHaveScreenshot` in new files under `tests/e2e/visual/`, three projects ×
  light and dark × the listed states, committed under `tests/e2e/__screenshots__/` in a `visual:`
  commit. The threshold already configured (`maxDiffPixelRatio: 0.001`) is the plan's 0.1 %; a larger
  diff fails until a new `visual:` commit with its pair replaces the baseline. A screen's baseline
  snaps the screen's own region (a locator screenshot, the shared shell masked) where it can, so a
  later screen's change to shared chrome does not invalidate it; where a later screen changes a page an
  earlier baseline shows (screen 1 removes the New menu the shell baseline shows; screen 2 rebuilds the
  Home behind screen 1's sheet), that screen's `visual:` commit refreshes the earlier files too, with
  their pairs.
- *Stable by construction.* Each visual spec builds its own workspace with fixed content (a fixture
  that refuses the shared A and B, like `workspace_switches`), masks time-dependent text (Home's
  greeting and `{% now "D j M" %}`, every `timesince` and printed date in a snapped tree, such as
  `studio/index.html:215` and the thread's message times) by a `data-visual-dynamic` marker, waits with
  `support/settled.ts`, and runs with reduced motion and the external network blocked. Fixed content
  is not enough on its own: the harness has no clock control and the e2e worker keeps the publish loop,
  so "today" in the calendar and Today, and posts falling due, would follow the real date. Visual runs
  therefore freeze the server's clock (request threads and the worker alike) at a fixed instant before
  the fixture's week, and the browser's with `page.clock`; the fixture sets `created_at` and
  `finished_at` itself, and nothing in it falls due. A self spec moves the clock 90 days on and expects
  the same masked screenshots.
- *Made where CI runs.* The path template has no platform segment and `iphone-13` is WebKit only with
  `CI=1`, so baselines are produced in CI by a baseline workflow, started by hand on the branch
  (`workflow_dispatch`, not by re-labelling the PR), that runs the E2E job's setup with
  `--update-snapshots` and uploads the images; a local run never writes them. Comparison is switched on
  by a variable only CI's jobs set (`E2E_VISUAL=1`), not by `CI`: `CLAUDE.md` documents local `CI=1` runs, and a local machine's
  fonts differ from the runner's, so a local `CI=1` run skips the visual specs with that reason instead
  of failing them. Golden specs never gain a screenshot.
- *Typeface.* Local pairs use Chromium's iPhone emulation and the local `system-ui` (Inter in this
  container), so they are not a sign-off of D3's face; the type pair is taken on WebKit in CI (the
  baseline run uploads it) or on a real iPhone.

**D10. Measuring each screen.**
- *axe:* each screen's own spec runs axe in light and dark (`colorScheme`) on three devices. The
  golden specs stay as they are (light).
- *Lighthouse:* CI keeps the three section-5 targets (Home, Approvals, Calendar month) and their
  budgets unchanged; `validateConfig` keeps requiring them. The runner gains named per-screen targets,
  each with a URL, a ready test id and one real interaction, measured three times with the same
  budgets (Performance ≥ 0.9, LCP ≤ 2,500 ms, CLS ≤ 0.1, lab INP ≤ 200 ms, gzip JavaScript ≤ 150 KB)
  at the screen's gate, medians into `CHANGELOG.md`. Analytics targets the account page (the index
  redirects, which the runner refuses); the portal and marketing need public targets and the portal its
  own session. Each screen's Start task reads its new target on main first (median and machine), so a
  target that cannot reach 90 is known before the work, not at the gate (the composer carries
  60,984 characters of inline script, 16.8 KB gzip, and has never been measured). Local and CI runners
  have disagreed before (Phase 2: Home's LCP failed at 2,580 ms in CI), so before a gate is signed the
  screen's targets also run once in CI through a manual Lighthouse run with `--targets=`, and the gate
  records that number.
- *The Calendar budget after screen 4.* CI measures `/calendar/?mode=calendar&view=month`; after
  screen 4 a phone opens `/calendar/` on the agenda, which CI would not measure. At screen 4 the owner
  is asked to move CI's Calendar URL to `/calendar/` or add it as a fourth CI URL (open questions).
- *Browser-job time.* The E2E job's limit is 35 minutes (`ci.yml:289`), raised from 20 in Phase 2
  for about 225 cases on one worker (`playwright.config.ts`: one server, one database); a local run
  already takes 22.9 minutes. The dark scheme runs for axe and the visual snaps, not for whole
  behavioural flows; the visual specs run in their own CI job; the E2E job is sharded by project as a
  matrix, each shard with its own `DB_NAME` and `E2E_PORT` (the one-worker rule holds per server).
  Every gate records the E2E job's wall time, which stays under 70 % of its limit; the limit is raised
  only with a measured reason.

**D11. Tests: what stays and what moves.**
- *Never edited:* the golden specs (01–12, 05-06, 11-inputs) and every test that enforces an invariant,
  including `apps/common/tests/test_a11y_sweep.py`,
  `apps/studio/tests/test_setup.py::test_readiness_speaks_plainly_and_points_at_set_up`,
  `apps/studio/tests/test_setup.py::TestToday::test_private_telegram_jobs_stay_out_of_the_card`
  (invariant 4),
  `apps/studio/tests/test_setup.py::TestSetupPage::test_owners_see_the_exact_names_and_others_are_told_to_ask`
  (owner-only names), `apps/studio/tests/test_chat_provider_readiness.py`,
  `apps/telegram/tests/test_web_privacy.py`, the gate and publisher tests and `live_verify`'s isolation
  check. The protection is per test, not per file: `test_setup.py` also holds ordinary tests that
  screens 1, 2, 4 and 9 move (TestHome, TestToday's class strings, the eleven-row regex). Each
  protected test's source is compared with its source on `045978b` (by `ast`, test by test), so an
  edit beside it is allowed and an edit to it fails the gate.
- *Kept exactly:* every test id and accessible name a golden spec uses (per screen in the
  requirements), plus the visible text they read: the "Today" region, "Revision 2", "Continue to
  portal", "What should change?", "Brand name", the "Media library" dialog, "Toggle menu", the
  account button named by the person, and the channel names in the brief card.
- *Moved deliberately:* ordinary tests that pin class strings, copy or markup order
  (`test_navigation_render`, `test_shell_a11y`, `test_compose_layout`, `test_review_a11y`,
  `apps/approvals/tests/test_index.py`, the settings, activity, portal and marketing tests, the self
  specs, the Lighthouse runner, the Node tests). They change in the same commit as the markup, red
  first: the new assertion is seen failing against the old markup, and every behaviour the old one
  protected (focus order, labels, Escape, above-the-bar placement, CSP nonces) keeps an assertion.
  No assertion is removed without a replacement that says what it protects.

**D12. No new URL parts; no new URLs by default.** The sheet and the wizard render inside existing
pages; deep entry uses an anchor (`#new-post`), never a new path. If a screen does need a fragment
URL, it takes only `workspace_id`, refuses like its page, and gets its `docs/PRODUCT_MAP.md` line and
its `tests/fixtures/product_map_urls.txt` line; golden 11 then sweeps it on its own.

**D13. The Approvals stack is a scroll-snap list; no gesture approves.** Below 1024 px the same
`approvals-list`, with the same `approvals-row-<id>` rows, is laid out as a horizontal scroll-snap
list: one card per screen width, a real-size preview edge to edge, *Approve & schedule* and *Request
changes* in a bottom bar, "3 of 7" and Previous/Next buttons for keyboard and switch users. Each card
has its own bar: the decision buttons stay descendants of their `approvals-row-<id>` with today's
row-scoped test ids (`approvals-row-approve-schedule`, `approvals-row-approve`,
`approvals-row-request-changes` and the rest carry no post id; golden 05 clicks
`row.getByTestId('approvals-row-approve-schedule')`), and only the card in view has an interactive bar
(the others are `inert`); there is no shared bar outside the rows. Swiping and scrolling only move
between posts; approving, rejecting and asking for changes always need a deliberate act on one named
post: a press on its named button, or on a desktop the `a` or `r` key on the card that has focus,
under D16's guards (invariant 1: a person, deliberately). Because every row stays in the DOM, Calendar's
list tab (the same partial), `test_index`'s equal row hooks, the reload that replaces
`approvals-list`, and goldens 05, 05-06 and 06 work unchanged (Playwright scrolls a card into view
before it clicks). From 1024 px the list stays a list.
*The approve fill shows what the server decided.* The approve endpoint still answers 204 and calls the
gate as today; its existing `HX-Trigger` toast carries the fill's words, built on the server, and the
browser never computes them. `approvals.views.approve` has four outcomes that move a post, and each
gets its own words; a time shown is the stamped `approved_publish_at` (or, once scheduled, the
channel's scheduled time; with several channels, the earliest and "and N more"), in the workspace's
time zone, or the list's `tz` filter when the row was rendered with one:

| Outcome (`apps/approvals/views.py`) | Fill | Toast |
|---|---|---|
| Two-stage: the post moved to client review | "Sent for client sign-off · approved for Mon 26 Oct, 10:10" ("Sent for client sign-off" when no time is stamped) | "Approved internally" / "Sent for client sign-off" |
| `schedule=1`, channels scheduled | "Scheduled · Mon 26 Oct, 10:10" | "Approved and scheduled" / the time |
| `schedule=1`, no future time | "Approved · not scheduled" | "Approved" / "No future time to schedule — pick one in the composer" |
| Plain *Approve* | "Approved for Mon 26 Oct, 10:10 · not scheduled" ("Approved · not scheduled" when no time is stamped) | "Approved" / "Ready to schedule" |

The refusals ("Couldn't approve", "Not approved", "Nothing to update") fill nothing: the button
returns to rest and the toast says why. Only the scheduled outcome says "Scheduled". A pytest per
outcome, two-stage and no-future-time included, pins the words and the time zone.

**D14. The onboarding wizard lives on Home.** For an owner or manager of a workspace whose four steps
are not done, Home's onboarding card (`id="onboarding-checklist"`) becomes four steps: brand →
connect one account → choose who approves → first post, with the readiness line underneath. Each
step's state is read from data, the same way Set up's rows are, so there is no new model and no new
URL; each step uses an existing handler (`studio:brand`, the connect page, `studio:use_me_as_lead`,
the New post sheet). Nothing redirects at sign-in, so golden 01 still lands on Home's "Today"; the
provider callback still lands on Calendar, so golden 02 keeps passing on today's pages, and a toast
there links back to the next step. `studio:setup` keeps rendering; owners keep Health under
Settings → Advanced. This is a guided checklist, not the guided four-step flow in one place that
`BETA_PLAN.md` section 3 describes: each step leaves Home for its page, and the connect step returns
on Calendar. Golden 02's header calls today's page-by-page walk the "equivalent" and promises a
rewrite "against the wizard in Phase 3". Whether the checklist counts as the wizard is an owner
question; if the owner wants the in-place flow, screen 9 builds the steps inside the card (brand and
approver forms in place, the connect step returning to Home), `screens/onboarding.spec.ts` covers
the in-place steps, and golden 02 is rewritten with the owner's leave.

**D15. Copy.** `CLAUDE.md`'s naming rules apply to every quoted string. In rebuilt screens, "brief"
becomes "what we're making" and "pipeline" becomes "progress"; "revision" becomes "version" except on
the post page's `studio-detail-revision` line, which goldens 06 and 05-06 read as "Revision 2" and
which stays until the owner allows a golden edit. The sheet's photo choice says the team makes the
picture (`apps/studio/forms.py:104` reads "Generate a picture with AI" today).

**D16. Keyboard shortcuts (desktop, from 1024 px).** `n` opens New post on Home and Calendar and goes
to Home's `#new-post` elsewhere; `a` and `r` press *Approve & schedule* and *Request changes* on the
focused Approvals card or row (the same POST as a click, one post only); `/` opens Go to; `?` lists
them with a switch that turns single-key shortcuts off, kept on the device (WCAG 2.1.4). They are
ignored while a text field, select or editable region has focus, while another dialog is open, and
with a modifier key. Because `a` approves and schedules a post the gate then stamps as a dashboard
approval, it has guards of its own: it acts only on the focused card or row whose *Approve & schedule*
button is present (a row without a proposed time shows only a plain *Approve*, and `a` does nothing
there); it ignores auto-repeat (`event.repeat`); after an approve it is disarmed until the person
moves focus again themselves; after the reload that replaces `approvals-list`, focus goes to the
list's heading (the toast announces the outcome), never to the next row. `r` opens the request-changes
form, as a click does, and never sends. Go to keeps its Phase 2 list (places, Settings and its tabs,
pinned by `test_navigation_render`) until screen 9 adds search (D17).

**D17. Go to searches posts, clients, settings and actions (screen 9).** `BETA_PLAN.md` section 4
asks for a command palette that "searches posts, clients, settings and actions" and for `/` search;
Phase 2 built the stub that filters destinations, and Phase 4 has no palette item, so it is built in
Phase 3, with screen 9. Typing in Go to keeps filtering the Phase 2 list (places, Settings and its
tabs) and adds: actions the person may take (New post, Approvals waiting, Appearance, the shortcut
list), posts of this workspace they may open (by caption or title, newest first, at most eight), and,
for someone who may manage clients, the workspace's portal clients by name. The posts and clients come
from one new fragment URL that takes only `workspace_id` and a query, refuses like the pages it links
to, reads only through the workspace-scoped managers, never returns a private Telegram conversation or
anything a plain client may not see, and goes through D12's checklist (its `PRODUCT_MAP.md` line, its
fixture line, golden 11 sweeping it). It carries `@ratelimit`, answers in under 200 ms on the seeded
workspace, and is debounced in the browser. `/` and Ctrl/Cmd-K both open it.

## Requirements

Every screen below also keeps, without repeating it each time: workspace isolation (golden 11 and
`11-isolation-inputs` sweep every workspace URL and refuse B's rows), the URL contract
(`studio:detail`, `studio:job`, `calendar:calendar`, `client_portal:*`, `telegram:settings` keep
rendering; every URL in `tests/fixtures/product_map_urls.txt` answers without a 404 or 500), the
invariant tests (D11), the CSP nonce on every inline script, and `CLAUDE.md`'s naming rules. Sizes:
S ≤ half a day, M about a day, L one and a half to two days.

### P0 — Foundations (F, before screen 1; about three days)

**F1. Dark mode.** As D2: dark Layer 1 and Layer 2, the on-fill and inverse tokens, the light
content scope for previews and creatives, the inventory of the 39 dark fills (inverse or flips), the
codemod over templates, static JS and Python class strings, the literal colours in `styles.css`, chart
colours from variables, per-page readiness with its page-to-template map, *Appearance* in the account
menu, the head script, the contrast checker. `tools/recolor.py --check` also fails on `bg-white`
outside the light scope, on `text-white`, `bg-white/NN` or `hover:bg-white/NN` under a fill that
flips, and on raw colour values in a page declared ready (emails, standalone pages, platform glyphs
and `recolor: keep` lines exempt). Acceptance: the contrast pytest passes for both themes and the
light scope equals the light `:root`; no page is dark until declared; switching *Appearance* repaints
without a reload; `recolor.py --check` clean; light rendering is unchanged by machine, not by eye: a
fixed page list (the a11y sweep's eleven pages and the three Lighthouse pages) at 390 and 1440 px on
main and on the branch, with the same data, differs by at most 0.1 % per screenshot.

**F2. Type.** As D3. Acceptance: the sub-13 px guard reports nothing, the standalone pages included;
the Analytics chart's text is 13 px; the body token is 16 px at 390 px and 15 px at 1440 px; no layout
overflows on Home, Approvals and Calendar at 390 px (the foundation pair). Running-text sizes are
asserted per screen (D3), from screen 1 on.

**F3. Spacing and cards.** As D4. Acceptance: `.ui-card` measures 20 px at 390 px and 24 px at
1440 px; the spacing guard exists with an empty screen list and flags odd steps, `.5`, `px` and
off-grid arbitrary values on fixture strings.

**F4. Shared components.** `components/primary_action.html` (D5), the status border (D6),
`components/empty_state.html` and an inline-confirm pattern (D8), each in light and dark, documented in
`DESIGN_SYSTEM.md` §10–§11. Acceptance: the one-primary test (count and place) and the above-the-bar
rules (`test_navigation_render`'s `ABOVE_THE_BAR`, `self/phone-bar-overlap.spec.ts` with a new
floating-button case) pass; the guard against `hx-confirm` and `confirm(` in gated trees exists.

**F5. Motion tokens.** As D7. Acceptance: the reduced-motion self spec exists and passes; no new
motion class runs longer than 200 ms.

**F6. Harness.** `tests/e2e/visual/` with its fixture and frozen clock, the baseline-update run (its
own workflow, started by hand on the branch), the `E2E_VISUAL` compare switch, the `colorScheme` option
for screen specs, the E2E job sharded by project with the visual specs in their own job (D10), the
manual Lighthouse run for per-screen targets, Lighthouse per-screen targets (D10), the per-test guard
on protected invariant tests (D11), and the guards above. Acceptance: the harness's own tests
(`node --test tests/lighthouse/*.test.mjs`, the e2e server's pytest) pass; CI's three Lighthouse
targets are unchanged; the E2E job's wall time is recorded.

**F7. Gate.** Full pytest, all browser specs on three devices, Lighthouse budgets,
`recolor.py --check`, and the owner's sign-off on the shell pair (Home, Approvals and Calendar at 390
and 1440 px, light), because the type floor and card padding change every page.

### P0 — Screen 1 · New post sheet (size L)

**What it unifies.**

| Today | Where | In the sheet |
|---|---|---|
| Sidebar New → *Post* | `base.html:478` → `composer:compose` | *Write it myself* → **Open the editor** |
| Sidebar New → *Idea* modal | `base.html:488`, `:521-731` → `composer:idea_create` | **Save it as an idea instead** (the same form) |
| Sidebar New → *Ideas*, *Import from CSV*, *Templates*, *Categories* | `composer:create_landing`, `csv_upload`, `template_list`, `category_list` | links at the foot (Templates and Categories with the `templates` switch) |
| Calendar header *Drafts* | `calendar.html:17` → `composer:drafts_list` | *Drafts* → Calendar's Drafts list tab |
| Calendar cell "+" (hover only) | month, week and day grids → `composer:compose?scheduled_date&scheduled_time[&account]` | opens the sheet in *Write it myself* with that time (touch- and keyboard-reachable in screen 4) |
| `studio:create` (no form renders it today) | `apps/studio/views.py:240-293` | *Ask the team* posts here |
| Home's thread composer | `studio/partials/thread.html` → `studio:thread_start` | **stays on Home**: talking to the team, driven by goldens 02 and 03 |

**Trigger.** `components/primary_action.html` labelled **New post**, on Home and Calendar only
(floating on a phone, top-right from 1024 px), `aria-haspopup="dialog"`, `aria-expanded`,
`aria-controls`; also `n` and `#new-post` on those pages. Shown only to a member with `create_posts`
who is not a plain client (`apps/studio/views.is_plain_client`), the rule `studio:create` already
enforces. Today the New menu shows to anyone in a workspace (`base.html:456` checks only
`request.workspace`), so viewers and clients see links that answer 403; they now see no trigger.
The sidebar New menu and the idea and tag dialogs leave `base.html`; the IdeaGroup and Tag queries
that `sidebar_context` runs on every request (`apps/common/context_processors.py:115-123`) move to
Home's and Calendar's context.

**The sheet.** A bottom sheet below 1024 px (`rounded-t-2xl`, `max-h-[92vh]`, grabber) and a
right-hand drawer (480 px) from 1024 px. `role="dialog"`, `aria-modal="true"`, labelled "New post"
(or "New idea" while the idea form shows), `x-trap.noscroll`; Escape closes; focus returns to the
trigger; the first field takes focus. Opening it closes the phone drawer first (the focus fix in
`CHANGELOG.md`, issue #18); Ctrl/Cmd-K does nothing while it is open; what was typed survives closing
and reopening on the same page. At the top, a segmented control: **Ask the team** (default) ·
**Write it myself** (preselected when opened from a Calendar cell).

- **Ask the team.** "Your idea" (required, up to 2,000 characters); channels from `BriefForm`'s own
  list (`STUDIO_PLATFORMS`, `forms.py:15-25`, optional: the brief defaults to the usual accounts); under
  *More*: goal, notes, a photo from the library or the team makes one, and *Keep the brand look*. One
  line under the button: "Your manager replies with what we're making. Nothing is made until you go
  ahead." It posts to `studio:create` with its guards unchanged: login, `create_posts`,
  `@ratelimit` 10/m, `llm.is_configured()`, `budget.can_spend()`, then `customer_workflow.save_idea`
  and `start_idea` (which re-check membership under a lock and call `chat.reply_refusal`), then the
  engine's `automatic_work_blocker` at every stage. On success the person goes, as today, to the idea's
  own thread (`chat.staff_thread_url`), where the reply and the *what we're making* card arrive; nothing
  is made before *Go ahead* (or creation mode "auto", unchanged). Today a form or chat error re-renders
  `studio/index.html` with status 400 and the page never shows the form, so the error is invisible
  (`views.py:270-271`, `288-290`); for a request from the sheet (`HX-Request`) the view answers 400 with
  the error's words alone, which the sheet writes into its error line (`data-inline-error`, without
  `data-no-error-toast`, which would stop the handler before it writes), and the not-ready and
  over-budget refusals appear in the sheet too. The over-budget refusal in the sheet has its own
  sentence, "This month's allowance
  for the team is used up. An owner can raise it in Settings → Autopilot.": the shared
  `budget.over_budget_message` says "AI budget", shows the amount and names the old "Agency →
  Autopilot", and it stays unchanged for its other callers (`apps/blog/tests/test_team_views.py:121`
  pins it). There is a third outcome after the guards: `start_idea` saves the idea and then may start
  no job, because `chat.reply_refusal` refuses at the daily reply cap (`customer_workflow.py:229-231`,
  `chat.py:842`); today's view then shows `started.note` instead of "is with your manager". The sheet
  keeps that: when no job started, the person still goes to the idea's thread, the message is
  `started.note`, and nothing says the idea is with the manager. Requests without HTMX behave as today.
  Home already builds this form on every GET and never renders it (`views.py:237`); the sheet renders
  it.
- **Write it myself.** One sentence and **Open the editor** (`composer:compose`, carrying
  `scheduled_date`, `scheduled_time` and `account` from a Calendar cell or slot; with the `templates`
  switch, *Start from a template*). The composer page, its test ids, its action bar and `save_post`'s
  conversions (no channel → refused; `_needs_dashboard_approval` and a missing `publish_directly` →
  *Submit for approval*, `apps/composer/views.py:1193-1231`) do not change in screen 1. This opens the
  full editor page rather than composing inside the sheet, a departure from `BETA_PLAN.md`'s "two modes
  on one screen" that the open questions put to the owner.
- **Save it as an idea instead.** The existing idea form: POST `composer:idea_create`; media through
  `composer:idea_upload_media` as asset ids (never the session's pending media, which the composer
  clears on load); tags through `composer:tag_create`, and shown only with the `templates` switch, to
  match Phase 2's D6 (the sidebar modal shows them today; the Ideas page does not). Title autofocus,
  the emoji picker's 95 options rendered only when opened, `ideaChanged` fired on success.
- **Foot links:** Ideas, Drafts, Import from CSV, and Templates and Categories with their switch.

**It never** approves, schedules, publishes, queues or picks a time; it adds no endpoint and nothing
in it skips `@ratelimit` or the invariant 6 checks; paid work starts only after `studio:create`'s
checks pass.

**Test ids.** New: `new-post-open`, `new-post-sheet`, `new-post-mode-team`, `new-post-mode-self`,
`new-post-team-idea`, `new-post-team-channels`, `new-post-team-send`, `new-post-team-error`,
`new-post-self-open`, `new-post-save-idea`, `new-post-link-ideas|drafts|csv|templates|categories`.
Kept: every `idea-*` id, every `compose-*` id, `home-thread` and the `thread-*` ids. Retired with the
menu: `sidebar-new-toggle`, `-idea`, `-ideas`, `-csv`, `-templates`, `-categories`; no golden spec uses
them; `self/emoji-picker`, `self/phone-menu-focus`, the Lighthouse interaction (`run.mjs:134-142`),
`test_shell_a11y`, `test_navigation_render`, `test_setup.py:410-414` and `test_channelless_drafts`
move to the new ids in the same commit (D11).

**Acceptance.** One tap opens the sheet on a phone from Home or Calendar. An editor and an owner see
the trigger; a viewer and a plain client do not, and a client's direct POST to `studio:create` still
answers 403. *Ask the team* creates one conversation, one message of kind `create` and one `chat`
job unless the daily cap refuses (then the idea is saved, no job exists and `started.note` is shown),
and no `StudioBrief` before *Go ahead*; when over budget or not set up, the refusal shows in the
sheet and nothing is made. *Write it myself* from a Calendar cell opens `/compose/` with the date and
time; golden 04 passes unedited. *Save it as an idea* creates the idea; with `templates` off there
are no tags. axe is clean with the sheet open in each mode, light and dark, on three devices.
Lighthouse on Home and Calendar measures the sheet's opening as the interaction.
*Pair states:* Home with the trigger; the sheet in each mode; the idea form.
*Reduced motion:* the sheet appears without sliding.

### P0 — Screen 2 · Home (size M)

*Changes.* Greeting and one status line; **New post** as the primary; Today first on a phone when
something waits, one line otherwise (`DESIGN_SYSTEM.md` §13); the thread behaves like a chat: the
composer sticks to the bottom of the thread card on a phone (and the floating button hides while the
composer is on screen), messages from one sender group under one avatar, a new message rises in
over 200 ms, "The team is working" shows while a job runs, and the brief, draft and receipt cards
render inline. *Send* and *Go ahead* become tinted (the view's primary is New post) and carry D8's
allowance line instead of a confirm. The duplicated agency tabs leave Home. Running text uses the body
token, asserted on the thread's message body, a draft's caption and Today's row titles (D3). "Nothing
yet" gets one sentence and a button that opens the sheet.
*Must not change.* Today's *Approve & schedule* posts `studio:approve` with `mode=proposed` into
`studio/services.approve`, only for `approve_posts` (`home-today-approve-schedule` absent for an
editor); `home-today`, `home-today-waiting`, `home-today-post-<id>`, `home-today-review`,
`home-thread`, `thread-composer-body`, `thread-composer-send`, `thread-message-<id>`,
`thread-brief-card`, `-channels`, `-key-message`, `-go-ahead`; the "Today" region; the section order
anchors (`data-home-today` < `data-live-strip` < `data-home-thread` < `data-home-routines` <
`data-home-recent`); the thread's JavaScript contract (`static/js/agency-thread.js`, `tests/js`);
polling only while the tab is visible; private Telegram threads never in a web list (invariant 4);
clients get 403. *Watch:* Home's CLS median is 0.078 against 0.1 (CI on `ff90678`), so the floating
button and the sticky composer reserve their space. *Pair states:* waiting items; nothing waiting; a
brief card in the thread. *Reduced motion:* messages appear without rising.

### P0 — Screen 3 · Approvals (size L)

*Changes.* The stack below 1024 px (D13) and a restyled list from 1024 px with the status border and
`a` / `r`; a shared real-size preview component (`components/post_preview.html`: Instagram 1:1 and
4:5, LinkedIn, Facebook, X, each as the platform shows it, in the platform's light look in both
themes, inside the light content scope of D2, with a dark-scheme assertion that its computed
background stays white), reused by screen 5 and the composer; the approve fill with its four outcomes
(D13); each card's decision buttons inside its own row (D13); `a` and `r` with D16's guards; bulk
reject confirms inline; the empty state gets a button; filters keep scrolling sideways; the bulk bar
stays above the phone bar and stays dark in both themes (D2).
*Closed here, red test first:* a plain client sees Calendar's Approvals tab (the open questions keep
it), and today that tab offers them *Approve & schedule*: the built-in client role grants
`approve_posts` (`apps/members/models.py`), `calendar_view` derives `can_approve` from it alone
(`apps/calendar/views.py:625`), `_approval_row.html:136-142` renders the button for any actionable
row (`pending_client` counts), `approvals:approve` checks only membership and `approve_posts`,
`gate._stamp_on_approve` keeps the internal stamp for a client's sign-off, and
`_schedule_at_approved_time` then schedules every approved channel with a future
`approved_publish_at`. A client's sign-off would schedule the post, against invariant 3. From this
screen a plain client in that tab sees only the client sign-off (*Approve*), never *Approve &
schedule*, and `approvals:approve` ignores `schedule=1` from anyone who is not an internal approver
(`is_internal_approver`). The red test: a plain client POSTs `schedule=1` on a `pending_client` post
in an enforced two-stage workspace, and the post ends `approved`, not `scheduled`.
`apps/approvals/views.py` is not on the do-not-edit list; the gate is not touched.
*Must not change.* *Approve & schedule* posts with `schedule=1` for an internal approver; plain
*Approve* never schedules and its copy never says it did; `gate.enforced` with `is_internal_approver`
(`apps/approvals/views.py:66`) and the fingerprint stamp (`gate._stamp_on_approve`); `POST …/approve/`
answers 204; the list reloads from `publish/approvals/` and replaces `approvals-list`;
`calendar?mode=list&tab=approvals` renders the same partial with the same row hooks; the out-of-band
tab-count targets; `approvals-list`, `approvals-row-<id>`, and inside each row the row-scoped
`approvals-row-approve-schedule`, `approvals-row-approve`, `approvals-row-review`,
`approvals-row-request-changes`, `approvals-row-review-comment`, `approvals-row-send-back`,
`approvals-row-select`, `approvals-row-details`; `approvals-bulk-bar`; viewers get no controls
and editors no approve or review controls; plain clients 403 on `/approvals/`; status words through
the status partials; Lighthouse's timezone-filter and details interaction. *Pair states:* the stack on
a phone, the list on a desktop, a card after *Approve & schedule*, the request-changes form, empty.
*Reduced motion:* the fill swaps instantly; the card leaves without sliding.

### P0 — Screen 4 · Calendar (size L)

*Changes.* The heading says "Calendar" (today "Publish", `calendar.html:13`); **New post** as the
primary; with no `view` in the address, an agenda below 1024 px and the week from 1024 px (today month
everywhere, `apps/calendar/views.py:700`); an explicit `view=` always wins and month stays available.
The agenda lists posts by day with an *Add a post* control per day; grid cells show "+" on focus and
on touch, not only on hover; both open the sheet with that time. Dragging a chip snaps it to the cell
and shows the new time; after the drop the time shown is the server's. List-tab rows get the status
border. The header's ghost links go: Drafts is the list tab, Posting schedule and Media library move to
an overflow menu that keeps `calendar-link-*`. The bulk delete, the event delete
(`event_form.html:71`) and the confirm modals become inline confirms (D8); the bulk bar stays dark in
both themes (D2). The owner is asked whether CI's Calendar URL moves to `/calendar/` (D10).
*Must not change.* Dropping a draft or failed chip (an implicit schedule) needs `publish_directly`
(`_IMPLICIT_SCHEDULE_STATUSES`, `apps/calendar/views.py:58` and `:1210-1215`); moving a scheduled post
needs edit rights (own post or `edit_others_posts`), and the gate withdraws its approval unless an
internal approver moves it, whose drag approves the new time (golden 07); the `calendar:calendar` URL
contract; the Approvals list tab, which goldens 05, 05-06 and
06, `test_index` and a plain client's Approvals link (`navigation.py:142`) use; `calendar-shell` with
`rescheduleChip`, `calendar-week-grid`, `calendar-week-cell-<date>-<HHMM>` with `data-date` and
`data-time`, `calendar-chip-<id>` (one per page), `calendar-select-<id>`, `calendar-bulk-bar`,
`calendar-mode-list|calendar`, `ui-select-calendarFilters.*`, `publish-tab-*`; the "Calendar week"
region and its keyboard scrolling (issue #21, `self/calendar-keyboard`); filter options absent while
closed; a client's `/` and the X callback land on `/calendar/`; SortableJS loads only where it does
today. *Pair states:* agenda on a phone, week on a desktop, a chip mid-drag, the list tabs.
*Reduced motion:* the chip moves without the snap animation; the time label still shows.

### P0 — Screen 5 · Post page and the composer page (size L)

*Changes.* The post page shows each destination in the preview component from screen 3 (today one
LinkedIn-style card with a hard-coded `#0A66C2` fallback); the phone decision bar stays (this page has
no phone bar) with *Approve & schedule* on the right and the approve fill; the breadcrumb names the lit
place (Home); "what we're making" for the brief. The composer page (3,175 lines) is restyled here
because it shares the preview: header, the action bar at 390 px, the preview drawer, and one primary,
the act `save_post` will honour for this person (*Submit for approval* when a schedule would be
converted, otherwise the publish button with its modes). The post page's destructive and paid actions
confirm inline as D8 lists them (*Discard* today has no confirm at all); the previews stay light in
dark (D2), asserted.
*Must not change.* `studio/services.approve` stays the one place a brief's time becomes a schedule;
`mode=proposed` against the schedule form; the post page's *Request changes* keeps passing the staff
member's words as the team's own feedback (`services.request_changes` without `requested_by`,
`apps/studio/views.py:520-536`); words from clients and the thread stay wrapped by `untrusted()`
(invariant 5; `services.py:329-330`), and passing `requested_by` here would change what staff may
choose (`_revision_context(..., staff_only=...)`); the `studio:detail` URL; `studio-detail-revision`
("Revision N"), `studio-detail-notes`,
`studio-detail-progress`, `studio-revise-form` with "What should change?", `studio-revise-send`;
`data-decision-bar`; no phone bar on the post page or the composer (`navigation.py:118`). For the
composer: golden 04's ids and behaviour (a direct GET of `/compose/` answers 200, 403 for a client,
`/compose/<uuid>/` after submit); `save_post`'s conversions; editing approved content withdraws the
approval (`gate.check_write`, `_clear`); `live_verify`'s `dashboard.composer` answers 200 without a
redirect. *Pair states:* waiting for approval, the team at work, *Revision 2*, the composer at 390 px.

### P0 — Screen 6 · Inbox (size M)

*Changes.* The open conversation reads like a chat (their messages left, our replies right, internal
notes dashed with a lock as in `DESIGN_SYSTEM.md` §12) with the reply composer at the bottom and *Send
reply* as the primary; rows get the status border (waiting for a reply: warning; replied or resolved:
success; reply failed: danger); sentiment and the SLA countdown leave the rows and appear when their
filter is on; *Draft replies with the team* confirms inline and labels what comes back as drafts a
person reads and sends; discarding a draft reply confirms inline (today `hx-confirm`,
`_draft_reply_item.html:40`); the open message's text is running text at the body token (D3).
*Must not change.* `inbox-row-<id>` (a click opens it; no `role="button"` or `tabindex` on the row, the
stretched button keeps its label), `inbox-detail-panel`, `inbox-message-<id>`, `inbox-assign-toggle`,
`inbox-assignee-<id>`, `-current`, `inbox-reply-body`, `inbox-reply-send`, `inbox-thread-reply-<id>`,
`inbox-status-toggle`, `inbox-status-resolved`, `-current`; nothing is sent without a person's press;
clients get 403 on every Inbox URL; "Reply not sent", "Reconnect the account", "does not support
replies". *Pair states:* the list, an open conversation, a failed reply.

### P0 — Screen 7 · Analytics (size M)

*Changes.* The four cards the page already computes (the three metrics of
`apps/analytics/services.hero_cards` and the engagement card), one trend, and the posts table, which
becomes list rows below 640 px as `DESIGN_SYSTEM.md` §10.7 already says; chart colours from the
theme and chart text at 13 px (F2); the empty state's *Create a post* goes to Home's `#new-post` (today
`composer:create_landing`).
No primary (D5); *Reconnect* stays the primary when an account needs it.
*Must not change.* Numbers come from each platform's data; *Reconnect* posts
`social_accounts:reconnect`; the drawer stays a trapped dialog; `chart.umd` loads only on
`analytics:account`; the chart initialiser stays in `base.html` (pinned by
`tests/lighthouse/chart-init.test.mjs`). A new `screens/analytics.spec.ts` covers the screen (no golden
does). *Pair states:* with data, empty, needs reconnecting.

### P0 — Screen 8 · Activity (size M)

*Changes.* The board, the job timeline (`studio:job`) and the routines restyled; status borders on
job rows; the agency tabs leave the page; the heading keeps "Your team"; no primary (an owner question,
D5); the presets stay one-tap tinted cards and serve as the empty state's action; deleting a routine
(today `confirm()`, `routine_rows.html:47`), *Run now* and a job's retry and resume confirm inline (D8).
*Must not change.* The board refreshes only while visible and announces only meaningful changes
(`team-live-announce`, polite, before `#routines`); routines stay for `create_posts`; job controls act
with the person's current authority under the job lock; the `studio:job` URL; `activity-board`,
`activity-routines`, `routine-preset-morning|monday|replies`; the pinned board copy and the words the
board must never contain (vendor names, worker, token, assistant, operator). *Pair states:* the team
at work, idle, a job page.

### P0 — Screen 9 · Settings, the onboarding wizard and Go to search (size L, plus Go to search M)

*Changes.* The seven tabs as a rail beside the panel from 1024 px and as the sideways strip below; one
primary per panel (each form's Save at the end of its form, an owner question in D5; in Advanced, only
Health's first unfinished step); the danger zone confirms inline (the typed confirmation stays); Team &
clients' five `hx-confirm` dialogs (remove a member, revoke an invitation in two places, revoke a
portal link, remove a client; D8) become inline confirms. **Advanced → Features** for owners: the five
switches, each with one sentence saying what it hides and that nothing already scheduled stops; saving
writes only that field (`select_for_update`, `update_fields=["features"]`), with a test that saving the
autopilot form a moment later does not undo a switch (the `00-cut.md` open question). **The wizard**
as D14 (its form depends on the owner's answer). **Go to search** as D17: its fragment URL through
D12's checklist, `@ratelimit`, workspace-scoped reads, no private Telegram rows, nothing a plain client
may not see; golden 11 sweeps the URL.
*Must not change.* Each tab's own permission check and the 403 for a tab a person may not use; old
pages answer 301 after their checks and keep accepting POST; forms post to their old handlers with
`next` (`settings_links.returning_to`); `require_dashboard_approval`; Health's exact names for owners
only ("Ask your owner." for everyone else); the readiness invariant test; the brand colour inputs are
exactly the form's `type="color"` widget; `settings-tab-*` (visible to the owner on phones),
`settings-panel-*`, `brand-primary-color`, `brand-accent-color`, `brand-save`,
`brand-sample-image-<layout>`, `setup-row-<key>` with `data-setup-state`, `setup-action-accounts`,
`setup-action-approvers`, `connect-platform-<p>`, `connect-later-<p>`, `connect-unavailable`,
`org-settings-timezone`, `-save`; `telegram:settings` and Telegram pairing untouched; Go to's Phase 2
list and every string `test_navigation_render` pins. A new `screens/onboarding.spec.ts` walks the
wizard; a new `screens/go-to.spec.ts` searches a post, a client and a setting and refuses workspace B's
rows; goldens 01, 02 and 10 pass unedited (02 rewritten only with the owner's leave, D14). *Pair
states:* Brand on a phone, Advanced with Features, each wizard step, Go to with results.

### P0 — Screen 10 · Client portal (size L)

*Changes.* Three parts and nothing else (`BETA_PLAN.md` section 4: "The client sees three things …
Nothing else."): **Waiting** (the stack of D13 with the portal's own cards and endpoints; one solid
*Approve* per card in view), **Live** (a grid of what went live, creatives as tiles and text posts as
text tiles), **Chat** (Talk to the team). The header keeps the logo and client name and the three
parts as tabs; today's Home, Reports, Activity and Telegram tabs (`portal_base.html:47-57`) leave the
navigation. `client_portal:dashboard` (`/portal/`, where the magic link and golden 08 land) has no tab
of its own and no summary: it shows Waiting with the Waiting tab lit, and golden 08 still clicks
`portal-nav-approvals` to `/portal/approvals/`. Reports and Activity keep rendering at their URLs
(the URL contract) with no link to them; the client's Telegram pairing is reached from one line inside
Chat ("Get these messages on Telegram"). The Chat tab's unread count reads only
`chat.portal_unread_total` and `chat.recent_messages(..., for_client=True)` on `audience=CLIENT`
conversations (`views_team.py:71, 198`), and a test proves an internal note and a private
conversation's message never appear on `/portal/`, Waiting, Live or the count.
*White-labelled with the workspace's colour* (`BETA_PLAN.md` section 4, `DESIGN_SYSTEM.md` §15): the
portal's accent comes from `BrandProfile.primary_color` (`apps/studio/models.py:94`, default
`#081D4A`) through a guard built to `DESIGN_SYSTEM.md` §22 (no such code exists today; it uses
T2's contrast method): the 700 step darkened until white on it is ≥ 4.5:1, the 600 step ≥ 3:1 on
white, ink-50 and ink-100, and the dark theme's fill and link steps checked the same way. When the
guard refuses a colour, the portal falls back to Pine. No opt-in. Acceptance: contrast passes in both
themes for the default colour, a pale colour (refused, Pine shown) and a dark one; the fallback is
tested. Body 16/26 (`DESIGN_SYSTEM.md` §15), asserted on the card caption (D3); dark mode like the app.
*Must not change.* Every `client_portal:*` URL keeps rendering; only external comments reach the client
(`apps/client_portal/views.py:186`, `:198`); internal notes never reach a client thread
(`apps/studio/chat.py`); a client's sign-off completes the client stage only, and the copy says so
("Your agency team schedules it next."); the magic-link GET never consumes the link; the client's own
Telegram pairing; the Focus plugin loads before Alpine in `portal_base.html`; `portal-continue`
("Continue to portal"), `portal-nav-approvals` (two copies, one visible), `portal-approvals-pending`
(one `portal-card` per pending post, gone when empty), `portal-approvals-decided`,
`portal-card-approve`, `portal-card-request-changes`, `-comment`, `portal-card-send-changes`; golden 11's
portal sweep. No gesture approves. *Pair states:* Waiting on a phone, Live, Chat, each with the default
colour and a workspace colour.

### P0 — Screen 11 · Marketing (size L)

*Changes.* Home: a dark hero (ink-950) with one line of promise; an animated product screen built from
real UI (the default; see open questions); three outcomes with numbers the owner confirms (nothing
invented, nothing the product does not do); the invite form inline, posting to
`marketing:request_invite`. The scrolling strip of network names, the ~21 feature cards and the
scheduler copy go. How it works: the idea → team → approve → publish flow drawn once. Request invite
restyled. Dark values for the `--mk-*` tokens (the public site follows the device only); the sub-13 px
rules in `marketing.css` fixed. The AGPL *Source code* link stays as a text link in the footer; there
is no GitHub button or badge. `DESIGN_SYSTEM.md` §17, which still describes a white hero, three-up
features, pricing cards and a "Get started" primary, is rewritten to match at this screen's gate (R1).
*Must not change.* The invite form's CSRF, honeypot, per-address limit, site-wide cap and one
notification per operator (`apps/marketing/views.py:261-338`); robots.txt and the sitemap; Privacy and
Terms in the footer; the header and footer link set; `marketing-nav-*`, `request-invite-*` (the honeypot
stays `hidden`); the hidden pages stay unlinked and `noindex`; no vendor names; the marketing screenshots
pass the orange check. The animated screen is not the LCP element and shows a still under reduced
motion. *Pair states:* Home, How it works, Request invite, each at 390 and 1440 px.

### P0 — Cross-cutting

**R1. Docs.** `DESIGN_SYSTEM.md` (§5 type, §8 motion, §10–§11 components, §12.3 the approve sequence
as D7 and D13 rewrite it, §15 the portal's three parts and its white-label colour, §17 the marketing
site as screen 11 builds it (dark hero, no feature grid, Request invite instead of pricing and "Get
started"), §21 becomes dark mode with its tables), `docs/PRODUCT_MAP.md` (the sheet, the wizard, the
Calendar default, Go to search and its URL, the portal's three parts, and the drifted line that says
Home's typing goes through `studio:create` when it posts to `studio:thread_start`), `CLAUDE.md` (the
design-system rules; the browser-test section's `E2E_VISUAL` switch), `tests/e2e/README.md` (visual
specs, the frozen clock and baselines). Each screen updates the sections it changes at its own gate
(screen 10: §15; screen 11: §17); the phase gate checks they are current.

**R2. The phase gate.** All screens done; full pytest green with every protected invariant test
unchanged (D11); CI green on the final commit; one complete local browser run; TOTP still pending and
reported separately; the tested SHA and CI run in `CHANGELOG.md`; stop for the owner.

**R3. Dark for the remaining pages** (default, subject to the owner's answer below; size M). The pages a
beta member reaches from the eleven screens and that stay light after them (sign-in and account pages,
media library, posting schedule, Ideas and Drafts, notifications, Telegram settings, the Set up page)
each pass a dark axe run on three devices and are declared ready, after screen 11 and before the phase
gate. A page that fails stays light and is listed in `CHANGELOG.md` for the owner.

### P1 (if time allows in Phase 3, else Phase 4)

- *Appearance* kept per person on the server (a column with `db_default`) instead of per device.
- *Write it myself* starts in the sheet (caption and channels), saves a draft and continues in the
  editor (an owner question below).
- Lighthouse in CI on every pull request for Inbox and the portal's Waiting, if the job stays within
  its time (each screen's targets already run once in CI before its gate, D10).

### P2 (designed for, not built)

- The sheet's two channel lists made one (today *Ask the team* offers `STUDIO_PLATFORMS` without a
  connection filter and the composer every connected account; joining them changes behaviour).
- Rewriting golden 02 against the wizard, and "Revision" → "Version", once the owner allows golden edits.

## Success metrics

- **Leading (Phase 3 gate):** 12 gates passed (F and 11 screens), each with a signed pair; 0 serious or
  critical axe findings in light and dark on three devices on every rebuilt screen; Lighthouse ≥ 90
  mobile on each screen's target and every budget met, in CI as well as locally; 0 sizes under 13 px,
  standalone pages and chart text included (emails as the owner decides); at most one solid primary
  per view, in its place; one tap to start a post on a phone (from three); golden specs and protected
  invariant tests unedited and green; a baseline for every screen in CI; `recolor.py --check` clean;
  the E2E job under 70 % of its time limit.
- **Lagging (beta):** a new agency owner goes from invite to a client-approved, published post on a
  phone without reading anything (`BETA_PLAN.md` section 8); no report of a post approved by mistake
  (swiping never approves; the `a` key has its guards); fewer than one "how do I…?" question per agency
  per week.

## Open questions

None block Phase 3; each has a default above. Questions marked *at screen N* are put to the owner
when that screen starts.

- *(owner)* **Dark mode choice and its place.** Default: follows the device; *Appearance* (System,
  Light, Dark) in the account menu, kept per device.
- *(owner)* **Display face.** Default: the system font's display cut at 700 (0 KB) for page titles,
  h2 and h3 alike (h3 was 600; `BETA_PLAN.md` asks for 700–800 on headings, and h3 is 16 px, below
  where Apple's display cut switches in). Alternatives: h3 stays 600 as the one exception; the
  committed Inter at 700 (48 KB, Latin only, on the critical path); a new self-hosted OFL face.
- *(owner)* **Where the primary sits.** `BETA_PLAN.md` section 4 says "always in the same place:
  bottom-right floating on phone, top-right on desktop". Two departures: (1) a decision about one item
  (the post page, an Approvals card, a portal card, the Inbox reply) and a Settings panel's Save sit at
  the end of the item or form on a desktop, not top-right; (2) Activity and Analytics, which only show
  work, have no primary. Default: both departures (D5). Otherwise the desktop decisions and Save move to
  the top-right of the page or panel header, and the two watch-only screens get a primary (New post).
- *(owner)* **Write it myself opens the full editor page rather than composing inside the sheet.**
  `BETA_PLAN.md` section 3 puts both modes "on one screen"; in screen 1, *Write it myself* is one
  sentence and an **Open the editor** link to `composer:compose`, and composing in the sheet (caption,
  channels, per-platform overrides) is P1. Default: the link out; the composer page is restyled in
  screen 5 with the post page because both use the preview component. Otherwise the sheet gains the
  compose mode in screen 5, with golden 04 still passing through `/compose/`.
- *(owner)* **Home keeps two ways in** (the thread and New post), because goldens 02 and 03 drive the
  thread. Default: yes; the thread is for talking to the team, the sheet for starting a post.
- *(owner)* **Is a checklist the onboarding wizard?** `BETA_PLAN.md` section 3 asks for "a four-step
  wizard"; D14 turns Home's existing "First steps" card into four linked steps, each leaving Home for
  its page, the connect step returning on Calendar, so golden 02 keeps walking today's pages, which its
  own header calls the "equivalent" of a wizard. Default: the checklist card. Otherwise screen 9
  builds a guided flow in one place, `screens/onboarding.spec.ts` covers its in-place steps, and golden
  02 is rewritten against it, as its header promises, with the owner's leave.
- *(owner)* **Golden edits.** Golden 02's header says it is "rewritten against the wizard in Phase 3",
  and the plan renames "revision" to "version"; both need golden edits. Default: no golden edits;
  a new wizard spec; "Revision" stays on the post page.
- *(owner)* **Inline confirms on the acts the goldens click.** `BETA_PLAN.md` asks that every paid
  action confirm inline. *Go ahead* (goldens 02 and 03), the thread's *Send* (02 and 03) and the post
  page's *Request changes* (06) start paid work, and the goldens expect the work to start on the click.
  Default: exempt, with the allowance line beside the button instead (D8), because each is already the
  person's deliberate second step. Otherwise the owner allows the golden edits that add the confirm
  step.
- *(owner)* **What a paid confirm says it costs.** Default: "counts toward this month's allowance",
  no amount; owners see amounts on Settings → Autopilot. Invariant 9 bans token counts and model or
  vendor names, not money, so a money estimate (from `budget.py`) is allowed if the owner wants it.
- *(owner)* **Emails under 13 px.** Emails do not load the stylesheet and keep literal values; the
  type floor (D3) leaves them out. Default: emails are the one exception, recorded here. Otherwise
  their sub-13 px sizes move to 13 px in a named task.
- *(owner)* **Dark mode outside the eleven screens.** `BETA_PLAN.md` calls dark mode a beta
  requirement; sign-in, account, media library, posting schedule, Telegram settings and similar pages
  are not rebuilt. Default: yes for the beta, as R3, a named Phase 3 step after screen 11 with a dark
  axe run per page. Otherwise those pages stay light for the beta, or R3 moves to Phase 4 as an
  addition to its checklist.
- *(owner)* **Calendar's Approvals tab.** Phase 2 kept it "until Phase 3 rebuilds Calendar"; goldens
  05, 05-06 and 06 and a plain client's Approvals link use it. Default: it stays; from screen 3 a
  plain client there sees only the client sign-off, never *Approve & schedule*.
- *(owner, at screen 4)* **CI's Calendar budget.** CI measures `/calendar/?mode=calendar&view=month`;
  after screen 4 a phone opens `/calendar/` on the agenda. Default: ask at screen 4 to add `/calendar/`
  as a fourth CI URL (the three section-5 targets stay); until answered, the agenda is measured in CI
  by the manual per-screen run before screen 4's gate. Otherwise CI's Calendar URL moves to
  `/calendar/`.
- *(owner)* **Marketing proof.** Default: an animated screen made from real UI, no video file; the
  three numbers come from the owner, or are product facts that can be checked.
- *(owner)* **Phase length.** Estimated build: F about 3 days (the frozen clock, the sharded browser
  job, the protected-test guard, the light scope and the dark-fill inventory added a day); screens 1,
  3, 4, 5, 9, 10 and 11 about 1.5–2 days each, with Go to search and the portal's colour guard
  adding about 1.5 days; screens 2, 6, 7 and 8 about 1 day each; R3 about 1 day: about 19–24 working days before review time, against
  two weeks (ten working days). Default: keep the order and scope. Each gate records the days used
  against the estimate; when the estimate is exceeded, **stop**: the owner chooses what moves out.
  Nothing the owner asked for (the portal's Live grid and colour, the marketing animation, Go to
  search, R3) leaves P0 unless the owner releases it.
- *(engineering)* **The Calendar default view without device sniffing.** Default: the server renders
  the agenda and the desktop fetches the week through the existing shell refresh when the 1024 px media
  query matches; the plan may choose another way that adds no URL and keeps the Calendar budget.

## Phasing inside Phase 3

1. **F: foundations**: dark tokens and codemod, type floor, spacing, shared components, motion,
   harness and guards; the shell pair signed off.
2. **Screen 1**: New post sheet (Home and Calendar declared dark-ready).
3. **Screens 2–4**: Home, Approvals (with the preview component), Calendar.
4. **Screens 5–8**: post page and composer, Inbox, Analytics, Activity.
5. **Screen 9**: Settings, Features, the wizard and Go to search.
6. **Screens 10–11**: client portal (with its colour), marketing.
7. **R3**: dark for the remaining pages.
8. **Phase gate** (R2), docs (R1), and stop for the owner.

Each step is one or more screens, each closed by its own gate and sign-off before the next begins.
