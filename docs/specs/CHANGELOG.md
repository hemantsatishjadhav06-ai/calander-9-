# Beta changelog

One entry per phase of [`docs/BETA_PLAN.md`](../BETA_PLAN.md): the date, what changed, and what the
phase gate (section 6) said. Newest first.

## 5 Nov 2026 — Phase 3 · Screen 1 — New post sheet

Spec [`03-rebuild-screens.md`](03-rebuild-screens.md) ("P0 — Screen 1"), plan [`phase-3.md`](phase-3.md)
(Part B, T14–T25), shaping notes [`screen-1-new-post-notes.md`](screen-1-new-post-notes.md). PR #26.
Gate evidence, waiting for the owner's sign-off on the pair.

**What changed.** One way to start a post, on Home and Calendar.

- *The button (T16).* **New post** (`components/primary_action.html`, `new-post-open`) on Home and
  Calendar for whoever may start posts (`create_posts` and not a plain client:
  `apps/studio/views.can_start_posts`, the rule `studio:create` already enforced). A viewer and a plain
  client see none, where the old New menu showed them links that answered 403. Below 1024 px it floats
  16 px from the right above the phone bar; from 1024 px it sits at the right of the page header.
  `n` (from 1024 px) and `#new-post` open the sheet too.
- *The sheet (T15–T18).* A bottom sheet on a phone and a 480 px drawer from 1024 px: one labelled,
  trapped dialog with **Ask the team** (the default: the idea, the channels and, under *More*, goal,
  direction, picture and *Keep the brand look*), **Write it myself** (**Open the editor**, carrying a
  Calendar cell's date, time and account) and **Save it as an idea instead** (the old idea dialog's
  form; tags only with the `templates` switch), and foot links to Ideas, Drafts, Import from CSV, and
  Templates and Categories with their switch. *Send* posts to `studio:create`, whose guards are
  unchanged; from the sheet it answers 204 with `HX-Redirect` to the idea's thread, or 400 (429 past
  the rate limit) with the refusal's sentence alone, written into the sheet's error line with the
  words kept. Nothing is made before *Go ahead*. Over budget the sheet says "This month's allowance for
  the team is used up. An owner can raise it in Settings → Autopilot."; `budget.over_budget_message`
  is unchanged for its other callers. Without HTMX the view behaves as before.
- *The New menu left the shell (T19)*, with its idea and tag dialogs and their scripts; the two
  queries `sidebar_context` ran on every request for them moved to Home's and Calendar's context.
- *Keyboard (T20).* `n`, `/` (Go to) and `?` (the list) from 1024 px, ignored while typing, in a
  dialog or with a modifier; the list's switch, **Single-key shortcuts**, turns them off on this
  device; Ctrl/Cmd-/ opens the list from anywhere.
- *Dark (T22).* Home and Calendar are declared dark-ready: their raw colours became tokens with light
  unchanged, and the selected filter chip is ink-900 with on-fill words.
- *Measured, photographed, documented (T23–T25).* Lighthouse presses New post on Home and Calendar;
  the visual spec photographs the button and the sheet in each mode; `DESIGN_SYSTEM.md` §10.9 and §11,
  `PRODUCT_MAP.md`, `CLAUDE.md` and `tests/e2e/README.md` describe the sheet, the button and the keys
  (`ab8fd47`).
- *Gated (T25, `420c82e`).* `SCREENS["new_post"].gated` is true, so the spacing, one-primary,
  inline-confirm and motion guards read the sheet's tree. The spacing, inline-confirm and motion
  guards found nothing in it. The one-primary check runs within the screen's scope (below). No
  template changed at the gate, so nothing photographed moves.

**Decisions taken by default** (each the plan's or the notes' default; the owner may overrule):

- *One primary, option (a)* of the plan's "Open before T25" note. `apps/common/tests/test_one_primary.py`
  gains a per-screen scope: `LEFT_TO_LATER` names, once, what other screens own on a gated screen's
  pages, each with its page and the screen whose gate counts it: Home's `thread-composer-send`
  (screen 2 tints it), Calendar's *Add event* (calendar mode) and its `bulk-confirm` dialog (screen 4),
  and the shell's `create-ws` dialog (owners; its *Create* sits outside a decision bar). The check
  leaves exactly those out and counts everything else, so the sheet's three panels, its tag dialog,
  the button's place and anything new on the two pages are checked. Red first: with `gated = True`
  alone the test failed for the note's reasons for owner, manager and editor. New tests prove that on
  the real pages a second primary in the sheet's bar, the button out of the header slot, an unnamed
  primary, or `thread-composer-send` on Calendar still fail, and that every entry is owned by a screen
  not yet gated (or the shell) and still found on the pages. The shell's dialog has no screen of its
  own in the plan: it is set aside for screen 1 only, so the next gate meets it again unless it has
  moved into its place first. **Please confirm**, or choose option (b).
- *The help line under the fields* ("Your manager replies with what we're making. Nothing is made
  until you go ahead."; notes, open decision 10). On a phone it is below the fold until the person
  scrolls.
- *The selected filter chip ink-900 with on-fill words* (T22): 14.6:1 on a dark card, light unchanged.
- Still the owner's, defaults standing: the grabber as a cue without a drag (notes 1), *Ask the team*
  with no connected account can only fail (4), `92vh` rather than `dvh` with the iOS keyboard (7).

**D5's toast rule.** D5 asks that the button and a toast never cover each other. The shell lifts the
toast host above the button with a body class (`has-fab`: `calc(9rem + env(safe-area-inset-bottom))`
on phones), as it already lifted toasts above the selection bars, so the toast rises above the button
rather than the reverse, with no script measuring heights; the button hides under a selection bar.
The outcome is the one D5 requires. **F4's browser case is done:** `tests/e2e/self/phone-bar-overlap.spec.ts`
(T21) holds the button above the phone bar on phones and in the header on desktop, on Home and
Calendar, an error toast and an approval toast above it, and the button hidden while posts are
selected in Calendar's list; green on three projects below.

**Audits** (T25a: `impeccable` audit and critique, `design-is`; 390 and 1440 px, both schemes; one
context, since this workflow step had no sub-agents, which the report says). Scores: `impeccable`
audit 13/20 before the fixes and 14/20 after, critique 29/40, `design-is` 21/30 (verdict REFINE: the
bones are right; fix the phone geometry, the slot sentence and the rough states). The detector found
nothing (in its degraded regex mode). Must-fix, both fixed red first:

- M1 (`e295ffd`). After a refused *Send* or *Save idea* the keyboard focus fell to `<body>`, outside the
  modal dialog (WCAG 2.4.3). The focus now goes back to the button that was pressed. Red: the new case
  in `screens/new-post.spec.ts` failed on all three projects ("the focus is back on Send … Received:
  inactive").
- M2 (`1574d80`). Tab moved the focus to controls hidden under the sheet's sticky header or decision
  bar (*Goal* and *Keep the brand look* at 390 × 664, *Direction* on Pixel 7, *Picture* in the drawer
  at 1280 × 720, the channels and foot links at 844 × 390; WCAG 2.2 SC 2.4.11). The sheet keeps its
  scroll padding equal to the two sticky parts and scrolls a focused control clear of them; no class
  or visual change. Red: the new case failed on all three projects.

Should and nits, for the owner and later screens (none fixed: each changes visuals, copy or shared
parts): S1 the phone sheet's height follows the mode, so *Write it myself* moves the mode switch 145 px
under the finger; S2 the sticky header and bar take 45 % of a phone sheet (71 % held sideways); S3
from a Calendar cell, *Write it myself* does not say which slot the editor will carry; S4 the dark
phone sheet has no top hairline; S5 the emoji picker's first opening is the slowest input on Home and
Calendar (within noise of main locally, under budget in CI); S6 two sentences at 14 px where running
text takes the body token; S7 "Security token missing" and a reasonless save error; S8 no count near
the 2,000-character limit; S9 Tab reaches the bar before the foot links above it; S10 (shared) the
selected segment reads pressed in dark; S11 (shell) axe's moderate `region` and `landmark-unique`.
Nits N1–N6: the bar's ghost buttons start 12 px in, *Ideas* and *Drafts* under 44 px wide on touch,
the drawer's foot links far below the help line, the idea title's browser bubble, two ways to create a
tag, *Send* could name whom it goes to.

**CI failures found and fixed on the way.**

- `e613d4a`: CI's pytest failed `test_reset_rate_limits_clears_a_views_counter`: django-ratelimit counts
  in fixed one-minute windows, so a burst straddling a window's end let the eleventh post through. The
  test holds the window still. The full suite met the same cause locally at this gate in
  `apps/blog/tests/test_seo_pages.py::test_the_check_up_button_is_rate_limited` (302 where 403 was due),
  fixed the same way, red first (`e7f130f`).
- `8f04b4f`, `10b1976`: CI's desktop shard failed two shortcut cases. Alpine's focus plugin starts
  `x-trap`'s trap 15 ms after the list opens and the list relied on it for its focus, so a key pressed
  in that window was lost; worse, a list closed inside it let go of a trap not yet started, the plugin
  then started it on the closed list and Tab moved nowhere on the page (a keyboard trap, WCAG 2.1.2).
  The list places its own focus and holds the trap until the plugin has started it, behind Alpine's
  flush (the second commit, after an independent review found an ordering the first missed).
- `f176792`: CI's iPhone 13 (WebKit) shard put the focus on *Close* after a switch of mode: Alpine
  shows a panel on the next animation frame and WebKit runs the focus timer first. The sheet waits a
  frame at a time until the mode's panel shows; `self/sheet-late-frames.spec.ts` reproduces WebKit's
  order on Chromium. `ea83b3b`'s hold, which answered a cause that was not there, was removed.

**Gate G** (code at `e7f130f`; the browser run on `420c82e`, whose application code is the same: the
commits after it change only the by-hand pairs runner, `tests/e2e/README.md` and one pytest).

1. *390 px first.* Shaped at 390 px first (T14's notes), then the 480 px drawer at 1440 px; the pair
   is at 390 and 1440.
2. *Light and dark.* Home and Calendar are in `screens.DARK_READY`; the screen's axe and visual cases
   run in both schemes; the dark after pair is attached.
3. *One primary.* `test_one_primary.py` passes with screen 1 gated (option (a), above).
4. *Reduced motion.* `self/reduced-motion.spec.ts`'s sheet case passes (C8).
5. *Audits.* Run; both must-fix findings fixed before the pair.
6. *axe.* 0 serious or critical in every axe case of the specs below, light and dark, three local
   projects (Chromium, so the iPhone 13 project is not Safari coverage). CI with WebKit: `<CI: to fill>`.
7. *Lighthouse.* Local C9 below; C12 medians: `<CI: to fill>`.
8. *E2E.* C8 locally, `screens/new-post`, `screens/dark-shell`, `self/shortcuts`,
   `self/sheet-late-frames`, `self/phone-bar-overlap`, `self/reduced-motion`, `self/emoji-picker` and
   goldens 02, 03, 04 and 07 on three projects: **139 passed, 0 failed, 26 skipped** (the declared
   desktop-only and phone-only cases), 10.6 min. CI run `<CI: to fill>`; the E2E shards' wall times
   (desktop-chrome `<CI: to fill>`, iPhone 13 `<CI: to fill>`, Pixel 7 `<CI: to fill>`, against the
   35-minute limit) and the Visual job's `<CI: to fill>`. Goldens unedited.
9. *Palette.* C6: "recolor: nothing left to do".
10. *Suite.* C10 (full pytest, `DB_NAME=p3_t25b_full`): on `420c82e` **7,055 passed, 1 failed, 1 skipped**
    in 18 min 11 s, the failure the rate-limit window above; on `e7f130f` **7,056 passed, 1 skipped** (the
    Redis-only one) in 18 min 2 s, with `tests/test_protected_tests.py` green: no protected test touched.
    On `e7f130f` too: C2 ruff and format clean (919 files), C3 mypy clean (1,011 files), C4 no missing
    migration, C6 clean. On `420c82e`: C5 the CSS builds (identical to a fresh build), C7 129 UI state
    tests and 37 Lighthouse tests pass, C11 154 pairs in each theme, 0 problems. (Run alone,
    `test_backup_restore_round_trip_preserves_application_rows` failed here twice on `information_schema`,
    the known issue `STATUS.md` lists; it passed in both full runs and is untouched.)
11. *Baseline.* `bf8f6f9`, `visual: baselines for tests/e2e/visual (run 41533712883)`: 24 new images for
    the sheet (the button at rest and the sheet in *Ask the team*, *Write it myself* and the idea form,
    light and dark, three projects) and the shell's three refreshed because its date mask's width
    follows the real date (76 to 100 pixels, 0.01 to 0.03 % of the image; nothing else moved). Every
    image was looked at. The shell's earlier refreshes in this screen: `477056e` (the button arrives on
    Home) and `b94ed9e` (the New menu leaves the desktop sidebar).
12. *Sign-off.* Not yet: the pair is with the owner.

**Lighthouse, locally** (C9; budgets as configured; three alternating rounds against main `045978b`,
each on its own manifest-static server, database and port, main measured by its own runner, which
still presses the New menu). Median of the rounds' medians, this branch against main:

| Page | Performance | LCP | CLS | Lab INP (round medians) | gzip JS |
|---|---|---|---|---|---|
| Home | 0.96 / 0.96 | 2,174 / 1,972 ms | 0.061 / 0.078 | 200 (160–240) / 160 (152–216) ms | 82,573 / 70,520 B |
| Approvals | 0.97 / 0.96 | 1,513 / 1,765 ms | 0.011 / 0.011 | 80 (64–104) / 176 (152–176) ms | 64,986 / 62,623 B |
| Calendar | 0.92 / 0.94 | 2,276 / 2,030 ms | 0.007 / 0.007 | 216 (144–224) / 192 (144–200) ms | 92,260 / 80,347 B |

Every interaction completed in every run. Only lab INP missed a budget: on this branch once in each
round (Home 240 ms in the first, Calendar 224 and 216 ms in the others), on main once (Home 216 ms).
This machine misses that budget on main too, so the local numbers are judged against main's:
performance, CLS and Approvals are level or better; Home's and Calendar's lab INP sit
24–40 ms above main's at the median with overlapping ranges, and their LCP 200–250 ms later, within
the 2,500 ms budget. The scripts the screen adds (the sheet's and the shortcuts') add about 12 KB of
gzip JavaScript on Home and Calendar, far under 150 KB. The slowest input on both sides is the emoji
picker's first opening (T25a's replays, S5); one Calendar run of round 2 read performance 0.77 with
753 ms of blocking time, an outlier its round's median absorbs. T23's earlier three rounds on a busier
machine read the same direction (Home 0.92 / 0.91, Calendar 0.89 / 0.88). The gate's numbers are C12's:
`<CI: to fill>` (Home, Approvals and Calendar, budgets unchanged). CI's Lighthouse job on `352295a`
read Home 0.95, Approvals 0.98, Calendar 0.94, lab INP 136–168 ms.

**The pair** (`tests/e2e/pairs/01-new-post.pair.ts`, `npm run pairs`): before from main `045978b` on its
own server, database and port (Home, the New menu open, the New idea dialog, Calendar month; light);
after from this branch (Home with the button, the sheet in *Ask the team* and *Write it myself*, the
idea form, Calendar month), light and dark; 390 × 844 and 1440 × 900. 8 and 20 images, sent to the
owner in the session, never committed. The dark after side is new in the pairs runner (`32f9004`: a
state may carry `scheme: 'dark'` and its name ends in `-dark`). Local Chromium with the local
`system-ui`, so not a typeface sign-off; WebKit's are the baseline run's.

**Follow-ups.**

- Go to, and possibly the sheet, may leave the same plugin trap behind when closed within 15 ms of
  opening (the race `8f04b4f` and `10b1976` closed for the shortcut list); not yet probed.
- The shell spec's date mask sits near the 0.1 % limit on some dates (its width follows the date).
- The audit's S1–S11 and N1–N6 above; the shell's `create-ws` dialog (set aside, above).
- Other tests that burst a per-minute rate limit (`apps/studio/tests/test_routines.py`,
  `apps/studio/tests/test_new_post_sheet.py`, `tests/test_e2e_server.py`'s sign-in burst,
  `apps/marketing/tests/test_request_invite.py`) may meet the same window edge; not audited here.

**Working days.** Commits for screen 1 since the owner's foundations sign-off (`ce3f427`, 2 Nov 07:27
UTC): 2 Nov (07:50–22:07 UTC, T14–T24 and the baselines) and 5 Nov (T25); none on 3 and 4 Nov. Two
working days against the spec's estimate of 1.5–2 for screen 1 (size L): within it, at its upper end.

Stop: screen 2 starts after the owner signs off this pair.

## 2 Nov 2026 — Phase 3 · Foundations: gate evidence, waiting for the owner's sign-off on the shell

Spec [`03-rebuild-screens.md`](03-rebuild-screens.md), plan [`phase-3.md`](phase-3.md) (Part A, T1–T13).
PR #26. Screen 1 starts only after the owner signs off the shell pair.

**What changed.** The groundwork every rebuilt screen stands on; no page is dark yet and no screen
is rebuilt yet.

- *Registry and guard rails.* `apps/common/screens.py` lists the dark-ready pages (none yet), each
  page's templates and each screen's parts; the guards read it: the 8 px grid, one primary action per
  breakpoint and in its place, no `hx-confirm`, motion only from the tokens, raw colours, and the
  protected-test guard, which fails if a test that enforces a `CLAUDE.md` invariant is edited, skipped
  or dropped (T1).
- *Dark mode, built but switched off.* A dark token layer and a codemod pass that moved every
  utility that would read wrong in dark onto tokens whose light value is the one it replaced (T3);
  `tools/contrast.py` checks 150 pairs in each theme (T2); charts read the theme (T4); an
  **Appearance** choice (System, Light, Dark) in the account menu, which says "This page stays light
  for now." until a screen's gate declares its pages (T5).
- *Type, spacing, components, motion.* Nothing under 13 px, running text at 16 px on phones and 15 px
  on desktop, bolder headings (T6); cards at 20 px padding on phones and 24 px from 1024 px, 32 px
  between a screen's sections, and the 8 px guard (T7); the shared primary action, empty state,
  inline confirm and status tones (T8); one 200 ms motion token and a reduced-motion check (T9).
- *Harness.* Visual baselines compared in CI with a frozen clock, the browser job split into one
  shard per device (T10); Lighthouse per-screen targets and a by-hand CI run for them (T11);
  before/after pairs and the light diff (T12).
- *The shell (T13).* The sidebar, header, phone bar, menus, drawer, Go to and toasts are on the 8 px
  grid, under an `impeccable` audit at 390 and 1440 px.

**Light rendering moved, on purpose.** `pairs:diff` between main (`045978b`) and the end of T12
(`6f171ee`), light, same data, pixels differing per page: at 390 px calendar 5.91 %, compose 1.11 %,
create 0.54 %, categories 0.52 %, inbox 0.52 %, saved replies 0.52 %, media 1.19 %, members 1.68 %,
Home 45.55 %, Activity 28.74 %, Brand 16.62 %, Approvals 2.96 %, Calendar month 5.91 %; at 1440 px
2.87, 1.57, 0.24, 0.18, 0.18, 0.18, 0.41, 0.54, 13.18, 21.63, 5.92, 0.46 and 2.87 %. Every pair
was looked at: the movements are F2's type (12 px small text to 13 px, body 16/15 px, the display
stack and weights, so long pages grow taller: Home 1,813 → 1,917 px at 390) and F3's card padding
(16 → 20 px on phones). T3 moved light by design in two places no listed page shows (the composer's
tooltip from ink-800 to the inverse surface, ink-900; the analytics drawer's media-kind badge from
`bg-ink-900/80` to `bg-scrim/80`, ink-950 at 80 %). The shell's own changes are in the shell pair.

**The shell audit** (`impeccable`, scoped to `base.html`, its includes and the shell's classes; 16/20
before, 18–20 after on the states audited). Must-fix, all fixed (`288d366`, `364fc61`):

- M1. 98 spacing utilities off the 8 px grid, all in `base.html`; red first
  (`test_the_shell_spaces_on_the_8px_grid`). Controls (the skip link, switchers, the account button,
  the phone bar's tabs, the idea dialog's pills, tag menu and emoji search) carry `data-control` and
  keep 4 and 12 px where they make the control right; layout moved to even steps; nudges (`mt-px`,
  `mt-0.5`) became geometry. Phone-bar targets stay 56 px tall; nothing overflows at 390.
- M2. The sidebar had three left edges: the workspace mark, every nav icon and the avatar now start
  at 20 px at 1440 and in the phone drawer; section labels on the same column (red first).
- M3. Go to: the field's words and the result rows' words line up.
- M4. Account menu: four insets became one (16 px for every line of words).
- M5. Collapsed sidebar at 1440: the account and New menus opened under the page (only their first
  50 px showed and took clicks); the sidebar now stacks above the page (`lg:z-30`), the workspace
  menu opens at 220 px, and the collapsed rail no longer jumps on load.

Should, recorded for the screens that own them: the notifications drawer's close button sits on a row
of its own (S1); the phone bell's count touches the top edge (S2); `.ui-toast` pads 12/14 px (S3);
the collapsed rail's items are 43 × 34 beside 36 px buttons (S4). Later: L1–L5 in the audit notes
(copy in title case in the idea dialog, which screen 1 replaces, among them). Seen while measuring,
not the shell's: on the media page at 390 px the page's own Folders button draws over the open
drawer.

**Departures, for the owner** (each with its reason):

- T3 (a) `bg-black/NN` stays and is not rewritten to `bg-scrim/NN`: black is the palette lock and
  does not flip, and the rewrite would move light from `#000` to ink-950 `#0E1114`
  (`composer/partials/media_list.html:11`, `media_list_pending.html:11`). (b) The select chevrons are
  a per-theme `--select-chevron` data URI drawn in each theme's tertiary text colour, not a CSS mask.
  (c) `.hour-bar.is-now` and `.timeline-now` keep ink-900, which flips (14.6:1 on a dark card),
  instead of the inverse surface (1.32:1 on a dark card). DESIGN_SYSTEM.md §21 explains all three.
- One contrast pair is accepted under its bar in light: the success-500 icon on the sidebar's
  ink-100, 2.93:1 against 3:1, the same on main. Light does not move (D2), so it is excepted in light
  only and passes in dark (`tools/contrast.py` `LIGHT_EXCEPTIONS`). **Please acknowledge.**
- The four menu panels (workspace, New, the idea dialog's tag menu, account) are marked as controls,
  so their 4 px padding and separators pass the grid guard, as the select's panel already does. The
  account panel is the weakest case (an info header and the Appearance group); the alternative is
  8 px separators and insets inside every panel.
- Menu rows moved from 10 to 12 px inset in every menu of the app, not only the shell's (2 px; no
  header was aligned to the old inset, so nothing misaligns).
- F4's browser acceptance (the floating button never covers the phone bar or a toast) completes at
  T21 with the first page that has the button.
- `frontend-design` is not installed; `impeccable`'s shape and audit steps stood in.
- **Open decision before T22 (Home and Calendar dark):** the selected filter chip. T3 made it the
  inverse surface, which in dark sits 1.32:1 on a card, so its selected state would rest on weight
  alone. Keep it, or move it to ink-900 with on-fill text (14.6:1 in dark; light does not move).
  Recommended: ink-900.

**Code review of Part A** (`engineering:code-review` in three slices: Python and tools, templates
and front end, CI and harnesses; `requesting-code-review` against the plan's T1–T12; every finding
then tried by an independent agent instructed to refute it). Nine findings survived, all fixed red
first and verified independently:

- The protected-test guard hashed only each test's own lines, so a protected test could be turned off
  without an edit: a skip on its class or module, a rebinding or `del` of its name, a conftest that
  ignores or deselects it, a changed class fixture or setup method, or one parametrized case dropped.
  It now also hashes each test's class and module context (`tests/fixtures/protected_context.json`),
  collects the protected files and refuses a skip, xfail, rebinding or missing item, and pins the 299
  node ids collected on main (`tests/fixtures/protected_collected.json`), all written once from
  `045978b` (`da4b145`, `4ff1e35`, `235905e`, `be200db`). The hashes in `protected_tests.json` are
  unchanged.
- The template tree did not follow inclusion tags, so a gated Calendar would not have been read
  where `{% ui_select %}` and `{% status_badge %}` render (off-grid spacing in `ui_select.html` among
  them); it does now, and a drift check renders Home and Calendar with posts in every state and fails
  on any template the guards would not read, by the same rule the guards use (`ba53ecc`, `87232f4`,
  `f41ff89`, `c2b8a09`).
- In dark, the collapsed sidebar's account button would have hovered at 1.49:1; it now uses the hover
  border token (4.99:1 in dark, light unchanged), the pair is in the contrast check, and recolor now
  flags ink-300 fills and white text on a flipping fill in scripts and Python class strings
  (`4b03611`).
- The baselines workflow ran the whole suite in writing mode on a blank specs input; CI's Visual job
  would have skipped (not failed) if every baseline were deleted; a label added to the pull request
  could replace a pending Lighthouse targets run. All three closed (`77a6853`).
- The light exception above was not in the plan's list of departures (`0df7a09`).

Refuted (each traced and found not to happen, or deferred by the plan): recolor's scrim threshold,
white text on 500/600 fills, the frozen clock and `date.today()`, raw colours in the shell's style
block (T22 clears them), the Lighthouse parser test's comment, the visual write switch keyed on `CI`,
a missing page-header slot (T16 adds it), and the Visual job's skip before the first baseline.

**Gate evidence.** Code at `c2b8a09ca8d7d9a1f8c15a855a079986ee31210d`; the baseline commit
`b3cd9ca` and this record's plan line (`0df7a09`) change no code.

- C10, full pytest. [CI run 41375204991](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41375204991)
  on `c2b8a09`: **6,874 passed, 1 Redis-only skip**, 227 subtests; coverage **42,209/48,272
  statements (87.44 %)**, above Phase 2's 87.38 %. Locally on `0df7a09` (the same code): **6,874 passed, 1 skip**, in 23 min 21 s.
- C2 ruff and format clean (912 files); C3 mypy clean (1,006 files); C4 no missing migration; C5 the
  CSS builds; C6 "recolor: nothing left to do"; C7 68 UI state tests and 36 Lighthouse parser tests
  pass; C11 150 pairs in each theme, 0 problems (the one light exception above). The protected-test
  guard: hashes unchanged, context unchanged, every protected test collected as written.
- C8, every browser spec, locally on `c2b8a09` (Chromium for all three projects, no `CI`, so iPhone
  13 is Chromium's emulation here, not Safari): **279 passed, 0 failed, 0 flaky, 6 skipped** (golden
  path 12, TOTP, pending until Phase 4, on each device; and the visual spec, compared in CI only), in
  28.3 minutes. In CI with `CI=1`, WebKit for iPhone 13, zero retries: every shard green; wall times
  against the 35-minute limit: desktop-chrome 5 min 58 s, iPhone 13 9 min 1 s, Pixel 7 6 min 16 s
  (the largest is 26 % of the limit).
- Baseline: the `visual-baselines` label ran
  [run 41376000718](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41376000718),
  which committed `visual: baselines for tests/e2e/visual (run 41376000718)` (`b3cd9ca`: Home, light,
  on the three projects; each image looked at). The next push's
  [CI run 41377189571](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41377189571)
  compared them: **Visual (Playwright) 3 passed**, job 2 min 40 s against its 20-minute limit.
- Lighthouse, budgets unchanged, every reading inside every budget. CI's Lighthouse job: on
  `c2b8a09` Home 0.98 / LCP 1,509 ms / CLS 0.073 / lab INP 80 ms, Approvals 0.99 / 1,582 / 0.012 /
  72, Calendar 0.97 / 1,776 / 0.007 / 88; on `0df7a09` 0.97 / 1,837 / 0.073 / 104, 0.99 / 1,361 /
  0.012 / 96, 0.96 / 2,098 / 0.007 / 96. C12 (`lighthouse-targets`, the same three):
  [run 41376147878](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41376147878)
  Home 0.96 / 1,698 / 0.073 / 152, Approvals 0.97 / 1,544 / 0.012 / 144, Calendar 0.92 / 2,211 /
  0.007 / 160; [run 41377280052](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41377280052)
  0.97 / 1,385 / 0.073 / 136, 0.98 / 1,329 / 0.012 / 128, 0.94 / 1,657 / 0.007 / 128. LCP and CLS
  match CI's within its spread; performance reads 1–5 points lower and lab INP 30–70 ms higher on the
  targets runs, with blocking time 1.5–2× CI's on byte-identical JavaScript (72,351, 64,215 and
  81,937 gzip bytes in all four), so the difference is the runner, not the pages: the two steps are
  the same commands on the same image. gzip JavaScript 64–82 KB against 150 KB. Locally (C9, this
  machine, two alternating rounds against main `045978b` on its own server): this machine misses the
  INP budget on main too (main's lab INP 224–296 ms, performance 0.85–0.93), so local numbers are
  compared with main, not with the budgets. Branch against main, medians: Home 0.92 / 0.92 against
  0.92 / 0.93, LCP 2,171 / 2,099 against 2,061 / 2,064 ms; Approvals 0.91 / 0.93 against 0.90 /
  0.85, LCP 2,038 / 2,035 against 2,056 / 2,208 ms; Calendar 0.88 / 0.89 against 0.90 / 0.88, LCP
  1,564 / 1,534 against 1,377 / 1,401 ms; lab INP 224–336 ms against 224–296 ms. Equal within noise
  except Calendar's LCP, about 150 ms later than main's in both rounds (gzip JavaScript 81,937
  against 80,347 bytes; the type floor and card padding make its page taller); in CI it is 1,776–2,098
  ms against 2,500. Screen 4 rebuilds Calendar and measures it at its own gate.
- `pairs:diff`: the result above (by design, F2 and F3).
- Working days: Phase 3's spec and plan landed on 1 Nov at 07:57 UTC; this evidence is from 2 Nov.
  About two days against F's estimate of about three.

**Owner's sign-off, needed now.** The shell pair (Home, Approvals and Calendar month, light, at 390
and 1440 px; main on the left, this branch on the right) went to the owner in the session (this
environment cannot upload images to the pull request; they are never committed). Local Chromium with the local `system-ui`, so not a typeface sign-off: the WebKit type
pair is in the baseline run's
[`visual-baselines` artifact](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41376000718/artifacts/13110784375)
(kept until 16 Nov). Also asked: acknowledge the light contrast exception, and choose the selected
filter chip before T22.

**Result: foundations complete. The owner signed off on 2 Nov 2026** ("approved, go ahead with screen 1", on
the shell pair taken from `364fc61` and the gate recorded at `cfaacb0`; the approval covers the light contrast
exception listed above). The selected filter chip takes the recommended default, ink-900 with on-fill text,
at T22. Screen 1 starts.

## 1 Nov 2026 — Phase 2: cut and merge, gate passed

Spec [`02-cut-and-merge.md`](02-cut-and-merge.md), plan [`phase-2.md`](phase-2.md), code map
[`phase-2-code-map.md`](phase-2-code-map.md). PR #23.

**What changed.** The sidebar is six places and the Settings gear (Home, Approvals, Calendar,
Inbox, Analytics, Activity; Blog with its switch); *More* is gone. Phones get a bottom bar (Home,
Approvals with its count, Calendar, Inbox, More), the notifications bell and a Go to palette
(Ctrl/Cmd-K or its button) that offers only the places and Settings tabs a person may open.
Approvals has its own screen at `/workspace/<id>/approvals/` (`approvals:index`), Activity is at
`/studio/activity/` with the routines, and Settings is one screen at `/workspace/<id>/settings/`
with seven tabs. Old pages answer 301 to their new home after their own checks; the URL contract
routes, POST targets and HTMX fragments keep rendering. The per-workspace switches hide Blog,
Queues, Templates, the extra providers and the advanced settings from navigation and creation only.
Intelligence and API keys left the navigation (their URLs work). The public site links Home, How
it works and a new Request invite form (CSRF, honeypot, per-network and site-wide rate limits, one
notification per platform operator in the daily digest); `/pricing/` answers 301 to it. Nothing was
restyled or deleted; the approval gate, isolation, budgets and Telegram are untouched.

**Fixed on the way to green** (each with a failing test first):

- Go to on WebKit (iPhone 13): the field did not keep the focus after opening, so typed letters
  were lost and Enter opened Home instead of the match. The palette now keeps the focus in its
  field for as long as it is open, and Enter and the arrows choose by the typed words, not by
  layout (`16337e5`). An independent review of that fix found that opening Go to over another
  dialog (the notifications drawer, New idea, the phone menu) made the palette's guard and that
  dialog's focus trap recurse until the stack overflowed; the focus now goes back on the next
  turn, at most 20 times per opening (`17db9eb`), with a browser case that opens Go to over the
  drawer.
- The e2e harness runs a fixture again when Postgres ends it as one side of a deadlock with the
  harness's worker, and logs each retry with the fixture's name and what Postgres said
  (`760c376`, `f54d6ea`). The application-level risk behind it (a person approving while the
  worker holds a `FOR UPDATE` lock on the workspace row) is [issue #24](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/24).
- `REQUEST_INVITE_HOURLY_LIMIT` pinned in the e2e settings; the browser job's limit raised to 35
  minutes for the larger suite (about 225 cases).
- A latent flaky test outside this phase: the client-safe report test looks for a planted "4.2" in
  the report's words, and on the gate-record commit the report's own "observed" time
  (`05:47:14.271625`) contained it (about a 1-in-100 chance). The test is unedited; the report now
  records that time to the second (`operations_as_of`), with a test of its own.

**Gate evidence on `ff90678923b74281d9f4ad9239480948088a155f`:**

- [CI run 41275707640](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41275707640):
  all nine jobs passed. Full pytest **6,081 passed, 1 Redis-only skip**, 227 subtests; coverage
  **42,084/48,162 statements (87.3801%)**, above Phase 1's 86.8357%. Browsers (WebKit for iPhone
  13, zero retries): **225 passed, 3 skipped**, the three golden path 12 (TOTP) cases, pending
  until Phase 4. Lighthouse mobile medians, budgets unchanged and all met: Home 98 / LCP 1,433 ms /
  CLS 0.078 / lab INP 80 ms; Approvals (now `/approvals/`) 99 / 1,587 ms / 0.012 / 80 ms; Calendar
  97 / 1,928 ms / 0.007 / 80 ms; gzip JavaScript 62–80 KB.
- A complete local browser run on the same commit (`npx playwright test`, Chromium for all three
  projects; WebKit cannot be downloaded here): **225 passed, 3 skipped (TOTP), 0 failed** (22.9 min).

**Gate, exactly as written in `BETA_PLAN.md` section 6:**

> full pytest suite green (the invariants' tests untouched); 12 e2e tests updated to the new
> routes and green; no 404 for any URL listed in `PRODUCT_MAP.md`.

- *Full pytest green, invariants' tests untouched.* Green in the run above. The tests `CLAUDE.md`
  names for the invariants keep their checks unchanged (readiness copy in `test_setup.py`,
  `test_chat_provider_readiness.py`, the accessibility and isolation sweeps). Tests of the old
  navigation in the same files were rewritten for the new one (the sidebar, *More*, the Routines
  page). One isolation check, `test_routines.py::TestIsolation::test_another_workspaces_routine_is_not_found_from_here`,
  is unedited but now reads the Routines page's 301 (empty body), so its page half passes without
  testing anything; its POST half still does. `test_activity.py::test_activity_never_shows_another_workspaces_routine`
  makes the same check where the routines are now shown.
- *12 e2e tests updated to the new routes and green.* By the spec's decision D10 the golden specs
  stay unedited (no file under `tests/e2e/golden/` changed) and pass because every route they use
  still answers; the new routes are covered by `tests/e2e/screens/` (navigation, Approvals,
  Settings, Activity, switches, the public site) on all three devices, and Lighthouse measures
  Approvals at `/approvals/`. Eleven golden paths pass on all three devices; path 12 stays pending.
- *No 404 for any URL in `PRODUCT_MAP.md`.* `tests/test_product_map_urls.py` checks every URL in the
  frozen pre-Phase 2 list and in today's map, as the owner, with every switch off and on: 200,
  301/302 to a working page, or 403/405 by design. Green.

**Performance: HTML is now compressed.** CI's Lighthouse numbers on this branch read lower than
main's (Home 98 → 94, Calendar 99 → 95, blocking time and lab INP up). A same-machine comparison of
main `1b6172f` and `16337e5` (two alternating rounds, three runs each) put blocking time and lab
INP equal within noise, so most of that gap was CI runner speed. What was real: every page's HTML
grew by about 11 KB (the new navigation), and pages other than Calendar and Approvals were sent
**uncompressed** (those two gzip their own: the Calendar since Phase 1, Approvals since its new
screen in this phase). On `f54d6ea` CI measured Home's LCP at 2,580 ms
against the 2,500 ms budget and the Lighthouse job failed. Home's largest element is
server-rendered text, so under slow-4G simulation it waits on the bytes before it, and the page
itself was 135 KB of them. `HtmlGZipMiddleware` (`ff90678`) gzips HTML pages and HTMX fragments
for browsers that ask, with Django's BREACH padding, and leaves file downloads, streams and JSON
as they were ([issue #25](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/25)).
Same machine, two alternating rounds: Home's document went from 136,860 to 29,732 bytes on the
wire and its LCP from about 2.75 s to 2.09 s (medians); Approvals and Calendar unchanged. In CI
on `ff90678` Home's LCP median is 1,433 ms and its score 98, back to main's level.

**Result: passed.** The owner authorized merge and release. Production has been offline since
31 Oct, so the release waits for it; "make CI required on `main`" is still a setting only the
owner can change.

## 31 Oct 2026 — Phase 1: quarantines removed, gate passed

Resumed PR #17 at `d197897` (all nine CI jobs green, four harness races and the
emoji scenario still quarantined). No merge, release or Phase 2 work had happened.

**Quarantines removed** (`3e12c00`): the emoji picker (#18), WebKit onboarding
(#19), the owner/editor draft handoff (#20), Calendar filter accessibility (#21)
and Pixel 7 keyboard scroll completion (#22) run in every suite again. CI on
`3e12c00` passed all nine jobs.

**A real defect the restored cases found** (`5e242dc`, `0d9f7a9`): the first full
local run on `3e12c00` failed the emoji picker on the iPhone 13 viewport. On a
phone the sidebar is a modal drawer with its own focus trap; opening New idea from
it left the drawer open behind the dialog, and the drawer's trap pulled focus back
from the dialog's title (in 2 of 4 Pixel 7 probes focus ended on the dialog's
Close button). Red first: `tests/e2e/self/phone-menu-focus.spec.ts` failed on
iPhone 13 and Pixel 7. The fix closes the drawer before the dialog opens and gives
the title `autofocus`, which the dialog's trap uses as its initial focus. A first
attempt (`5e242dc`) also replaced the drawer's own focus hand-back; CI showed that
hand-back did not land in WebKit, so `0d9f7a9` restores the drawer's original close
behaviour exactly (as `test_shell_a11y` pins it) and keeps only the fix.

**Gate evidence on `0d9f7a9fe2b086fb6f705515cc1f3e1122d018fa`:**

- [CI run 41196779114](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41196779114):
  all nine jobs passed. Full pytest **5,551 passed, 1 Redis-only skip**, 209
  subtests; coverage **41,174/47,416 statements (86.8357%)**, above main's
  41,054/47,301 (86.7931%). Browsers (WebKit for iPhone 13, zero retries): **150
  passed, 3 skipped** — the three golden path 12 (TOTP) cases, declared pending
  until Phase 4. Lighthouse mobile medians, budgets unchanged: Home 98 / LCP
  1,789 ms / lab INP 96 ms; Approvals 99 / 1,396 ms / 72 ms; Calendar 99 /
  1,547 ms / 64 ms; CLS ≤ 0.07; gzip JavaScript 69–79 KB.
- Three consecutive complete local browser runs on the same commit (`npx playwright
  test`, Chromium for all three projects; WebKit cannot be downloaded in this
  environment, so iPhone 13 ran on Chromium's iPhone emulation and is not Safari
  evidence): **run 1** 150 passed, 3 skipped (TOTP), 0 failed (1,202 s);
  **run 2** 150 passed, 3 skipped, 0 failed (1,202 s); **run 3** 150 passed, 3
  skipped, 0 failed (1,252 s). Zero retries, nothing quarantined.
- Re-running the CI workflow from this session is refused (403), so the WebKit
  evidence is the CI run above plus the CI run on the commit that records this gate
  (same application and test tree).

**Gate, exactly as written in `BETA_PLAN.md` section 6:**

> CI green with all new jobs; 12 e2e tests pass on the old UI.

**Result: passed**, with golden path 12 pending under the owner's exception until
Phase 4 (TOTP), reported separately and never counted as passing. "Make CI required
on `main`" is a repository setting only the owner can change. The owner authorized
merge and release on 31 Oct.

## 30 Oct 2026 — Phase 1: atomic review handoff and final verification (in progress)

Resumed the existing draft PR #17 at
`52892bca85347521166453a61e36025066cc6e30`; both the remote branch and main
were unchanged. The interrupted turn left only a new, uncommitted transaction
regression file, which was preserved. No merge, release or Phase 2 is authorized.

**Starting evidence:** [CI run 40667942809](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/40667942809)
passed eight jobs, including 5,541 Python cases with one Redis-only skip
(209 subtests reported separately), coverage 41,162/47,406 statements
(86.828671%, above main's 86.793091%), and all mobile performance budgets.
Its browser job failed: 139 passed, seven explicitly deferred/quarantined,
one failure, zero retries. Golden path 3 observed a READY/DONE brief while
both platform posts were still drafts. The producer committed readiness before
submitting those posts for review. [Issue #20](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/20)
tracks this application race and its temporary quarantine; its invariant test
will remain unchanged.

One local full run on that commit passed 144 cases with only three deferred
TOTP cases (863.65 seconds). The sequence was intentionally paused before
run two because of the CI failure; this is not three consecutive passes or a
completed gate. Fresh evidence is required after the handoff repair.

**Repair:** handoff now locks the brief, post and platform posts in the same
order as revision/discard, then commits the draft, review submission and READY
state together. A failed or unmoved channel rolls the whole handoff back.
Reviewer notifications run after that transaction exits in the autocommit
background step; ordinary callers retain the approval service's synchronous
default. No broad notification or approval policy changed. No final READY write
can overwrite a human decision made when the notification arrives.

New transaction tests first exposed three failures (visibility and two rollback
cases), then two additional failures for skipped channel transitions. They use
an independent database connection to observe committed state, and cover stale
revisions, discard, review trust and immediate human approval. The new retry
assertion was corrected to respect the existing revision-bound review guard:
an old review cannot authorize a new revision; request changes and re-review
before submitting again. The original invariant tests remain untouched.

The focused Python run passed 129 cases, including all nine new transaction
regressions and the existing pipeline, verified-claim, retry/scheduling and
approval-workflow cases (61.72 seconds). Full mypy passed 955 files, Ruff
passed, all 40 UI state tests and all 17 Lighthouse enforcement tests passed.
The focused browser paths and final full gate are still pending.

**CI runner compatibility:** [run 41078517196](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41078517196)
on `a3197ec4eb3ba2f99113473d89bec9a5c0b3a214` exposed an infrastructure change:
`ubuntu-latest` now selects Ubuntu 26.04, which locked Playwright 1.56.1 does
not support. E2E and Lighthouse failed during browser installation, before
measuring anything. Those two jobs now explicitly use supported Ubuntu 24.04;
browser versions, dependency validation, zero retries and budgets are unchanged.
This is a workflow-only repair; it does not change the browser-tested app.

**Focused browser verification:** original paths 3, 6 and 8 passed all 18
cases on Desktop Chrome, real WebKit and Pixel 7 (236.02 seconds), with no
skips, failures or retries. Their assertions are unchanged.

**Accessibility blocker retained:** the first full stability attempt at
`e1a62a4e715812180024a973fa0a6ebb05e736e7` found a serious axe
`scrollable-region-focusable` violation in the Calendar week grid, through
the existing filter self-test. The capped scroll region lacked keyboard access
when its content provided no focusable controls. [Issue #21](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/21)
tracks the scoped repair and quarantine. The failed attempt was stopped:
61 actual passes, one genuine failure, one interrupted case, one executed
TOTP skip and 83 unrun cases. It is not a complete run or a gate pass.
The parallel local pytest attempt was also stopped before changing the
template; its partial coverage/results are not used as final gate evidence.
Source remained unchanged throughout those interrupted attempts.

**Keyboard repair:** a new isolated past-week browser regression reproduced
the serious axe finding before the template change. The week grid now has
`tabindex="0"`, a region role and the accessible name "Calendar week". Its
layout, posts and actions are unchanged. The regression verifies Tab entry,
PageDown, horizontal arrow scrolling where needed, and axe before/after.
It and the unchanged filter test plus original paths 6 and 8 passed all 12
focused cases across the three real browser projects (179.61 seconds; no
skips, flaky cases or retries). The template accessibility sweep, CSP header
and response-compression tests passed all 11 cases. The complete browser
inventory is now 150 cases: 147 implemented cases and three deferred TOTP cases.
All four quarantine scenarios must be included in fresh stability runs.

**Full verification at `ac164ef3815ba3c3b18f3baa725b9466e50be81d`:**
[CI run 41081319505](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/41081319505)
passed eight jobs. Full pytest passed 5,550 cases with one Redis-only skip
and 209 subtests reported separately; exact coverage was 41,176/47,416
statements (86.839885%), above main. All Lighthouse budgets passed: Home
Performance 96 / LCP 2,145 ms / measured lab INP 136 ms; Approvals
96 / 1,348 ms / 128 ms; Calendar 96 / 1,317 ms / 112 ms. CLS and gzip
JavaScript also passed. The complete artifacts were digest-verified.

The CI browser job failed only the new Pixel 7 keyboard test: 133 passed,
16 explicitly skipped, one failure, zero retries. Its horizontal movement
assertion found `scrollLeft` still zero. The trace shows PageDown's vertical
scroll still moving (489 → 529 → 541) around the ArrowRight keypress.
Waiting for movement to start did not wait for it to finish.
[Issue #22](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/22)
tracks this harness synchronization repair and its temporary quarantine.

Two complete local suites on the same unchanged source each passed 147
cases with only three TOTP cases pending, zero failures/flaky outcomes/retries
(983.15 and 990.10 seconds). The third attempt was stopped for the repair:
40 passed, one interrupted, one executed TOTP skip and 108 unrun cases.
Those two passes remain historical evidence; a fresh three-run sequence is
required after correcting the keyboard synchronization. No invariant assertion
or performance budget is relaxed.

**Native-scroll synchronization:** a controlled check reproduced the ordering
defect before the repair: PageDown and ArrowRight were sent without an intervening
`scrollend`. That local probe did not always reproduce zero horizontal movement;
CI provides the actual failing movement assertion. The new test helper installs
and acknowledges a native listener before sending one key, waits for completion
with a five-second failure bound, and cleans up its listener/timer. The repaired
controlled checks pass on Chromium and WebKit with the order key → end → key →
end and exactly one keypress per axis. Both movement assertions remain intact;
there are no sleeps, input retries or application changes for this repair.
Focused verification then passed all 12 cases across the three projects
(175.36 seconds), including Pixel 7's unchanged horizontal assertion,
the existing filter checks and original golden paths 6 and 8. Five explicit
verification flags now include every quarantined scenario in the fresh
150-case stability sequence; no quarantine skip counts as a pass.

**Gate, exactly as written in `BETA_PLAN.md` section 6:**

> CI green with all new jobs; 12 e2e tests pass on the old UI.

**Result: pending.** The handoff repair, final-source full pytest and three
complete consecutive browser runs with every quarantined case enabled,
quarantine removal and normal CI remain required. Golden path 12 stays
pending until Phase 4 under the owner's explicit exception.

## 28 Oct 2026 — Phase 1: finish the performance and stability gate (in progress)

Resumed the same open PR #17 from `d1dcb1463ed37dd0f99a94b0c5774adbc4d3cd7b`.
[Its CI run](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/40292861255)
finished with eight jobs passing and Lighthouse failing: Calendar Performance
89 against 90. Pytest passed 5,536 with one Redis-only skip; browser tests
passed 135 with six skips (three TOTP, three emoji quarantine). Coverage was
41,069/47,313 statements, 86.802781%, above main's 41,054/47,301, 86.793091%;
both reports display 87%.

**Change.** Closed shared filters now mount their option controls only when
opened. The new browser regression first failed with 35 mounted controls
where zero were expected, before changing the panel wrapper. Existing
selection models and handlers are retained. The regression exercises keyboard
opening/selection, single and multiple selections, clearing, reopening and
axe. First timezone-filter opening, selection and reopening are also included
in the Lighthouse real-input measurement so deferred work stays under the
200 ms lab interaction budget. No thresholds or invariant tests changed.

CI now retains Python coverage/JUnit results, browser reports/failure traces,
and all Lighthouse reports as seven-day artifacts, including failed runs.

**Fresh local measurements** (three mobile audits per page; configured median):

| Page | Performance | LCP (ms) | Lab INP upper bound (ms) | CLS | JavaScript gzip (bytes) |
|---|---:|---:|---:|---:|---:|
| Home | 96 | 1,886 | 120 | 0.07843 | 68,862 |
| Approvals | 95 | 2,197 | 120 | 0.00628 | 78,689 |
| Calendar | 92 | 2,431 | 120 | 0.00672 | 78,688 |

All configured medians pass. Calendar's individual LCP samples were 2,342,
2,431 and 2,592 ms; the third sample exceeds 2.5 seconds and is retained in
the report. This local pass does not replace fresh CI. Lab INP is not field
p75 INP. The 17 Lighthouse enforcement/lifecycle tests and 21 focused Python
rendering, CSP, accessibility and analytics tests pass. The focused browser run
passed all 18 cases on Desktop Chrome, actual WebKit and Pixel 7, including
golden paths 6, 7 and 8, the repaired emoji picker and the new filter regression;
zero skips or flaky cases (197.2 seconds).

**Independent CI after the filter change:** commit
`59a2c9cb4eb1de5ad23a004f8fd6cbd79dd09e38`,
[run 40660336344](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/40660336344),
failed Calendar again: Performance 89 and median LCP 2,889 ms. Home and
Approvals passed. All nine reports were retained and independently checked;
no sample or threshold was discarded. Calendar sent 203,197 bytes of
uncompressed HTML, with 132 KiB of estimated compression savings. The next
scoped fix targets response transport, not a relaxed gate. The three-run
browser stability sequence is paused after its current first run until that
fix is tested; earlier measurements remain historical evidence.

**Response transport fix.** Calendar now uses Django's `gzip_page` beneath
`login_required`. Both Calendar and its Approvals list retain the same markup,
permissions, security headers, nonce and CSRF handling; clients without gzip
receive plain HTML and HTMX requests retain fragments. Django's randomized
compression padding remains enabled; no shared response cache is added.
The five new response regressions produced four expected failures and one
boundary pass before the decorator, then five passes after it. No existing
invariant test was edited.

Before this change, CI on `59a2c9c` completed the full pytest suite with
5,536 passes, one Redis-only skip and 86.807009% coverage. Its complete local
browser run passed 141 cases with only three deferred TOTP cases and no
flaky outcomes, including the repaired emoji test on all three devices
(895.3 seconds). Because CI had verified the same full Python suite, the
duplicate local run was stopped after 3,998 passes; its interrupted receipt
is explicitly partial and is not used as gate evidence. All these results
predate compression. Final-source CI and three consecutive browser runs
remain required after the transport fix.

**Compression measurements:** the fresh local nine-audit run on
`2aba8b5402a93fecc5e97952f158c83e51a27463` passed all budgets, with Calendar
Performance 98 and median LCP 1,441 ms. Independent
[CI run 40662855077](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/40662855077)
also passed Lighthouse: Home 95 / LCP 2,349 ms / lab INP 128 ms;
Approvals 97 / 1,359 ms / 120 ms; Calendar 96 / 1,654 ms / 104 ms.
Calendar's HTML transfer fell to approximately 39 KB, from 203 KB.
All nine CI reports were verified, including mobile/CPU settings, gzip bytes,
CLS, real inputs and artifact integrity. The application change has margin
under the unchanged budgets.

That CI run found a typing defect in the new test's import of a private Django
CSRF helper. The test now exercises the public `CsrfViewMiddleware` contract:
the actual decoded token/cookie pair is accepted and an invalid token gets 403,
without invoking application actions. Five response tests and full mypy
(954 files) pass. No application code changed for this test correction.
Final CI after this correction and the three full browser stability runs are
still pending; the interrupted or superseded runs are not counted as passes.

**Stability failure retained:** CI run
[40663804886](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/40663804886)
on `b5a04f05fa75ddf340306cd99f5f1485e3c2afcc` passed all nine jobs. However,
the first local stability run failed with 140 passed, three TOTP skips and
one WebKit onboarding navigation failure (831.5 seconds). The sequence
stopped before runs two and three; no failed test was retried. The mocked
OAuth POST response arrived before WebKit committed that document, so its
late commit interrupted the synthetic callback navigation. The same path
had passed the preceding full run. This flake is tracked in
[issue #19](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/19).
The original golden-path file and its invariant assertions remain unchanged.
A bounded harness synchronization repair and fresh full stability evidence
are required; green CI alone is not recorded as the completed Phase 1 gate.

**Mocked-navigation repair:** the shared browser fixture now waits for a
local mocked HTML POST document to commit before starting a subsequent explicit
navigation. It preserves route-handler identity and propagates failed/missing
commits and ordinary navigation errors; it never retries a callback. Real form
submissions, GET and AJAX navigation behavior are unchanged, and intentional
cancellation tests can opt out. Original golden path 2 is byte-for-byte intact.
Ten Node checks cover ordering, failure/timeout/cleanup and API compatibility;
the initial no-op implementation produced four expected failures before repair.
The controlled real-browser ordering/error check and original onboarding path
passed all six focused cases across Desktop Chrome, WebKit and Pixel 7.

Issue #19 remains visibly quarantined through the shared fixture while its
explicit verification opt-in includes it in stability runs. Issue #18's emoji
case likewise remains enabled in those runs. Normal CI must include both after
three consecutive complete suites; neither quarantine is a gate pass.
CI now applies to every pull request, retaining the existing main-push trigger.

**Gate, exactly as written in `BETA_PLAN.md` section 6:**

> CI green with all new jobs; 12 e2e tests pass on the old UI.

**Result: pending.** Fresh final-source pytest, three consecutive full browser
runs including the repaired emoji case, normal CI after quarantine removal,
and final gate documentation remain. Golden path 12 stays pending until
Phase 4 under the owner's explicit exception. No merge, release or Phase 2.

## 26 Oct 2026 — Phase 1: complete and verify the harness (in progress)

**Scope.** Finish PR #17 and run its gate. The owner explicitly reserved merging,
releasing and Phase 2 for a later instruction. Owner-managed branch rules,
provider apps, production credentials and beta invitations are not prerequisites
for the local harness work. Golden path 12 remains pending until Phase 4.

**Starting point.** PR head `4b697579d25a5ddf71d1dc015ab28f2a26e7620b` has the
same tree as GitHub's test merge `9582e28226b0fdd23f9fa51f11e2a219fa45bbc5`
with main `6d9cf1d450282e295a779dcdbdea5252d7e8c3d2`. The preceding session's
partial pytest and browser runs are not full-suite verification. The later
documentation-only commit `35f30cd` records the preceding session's final
paths 6 and 8 review as passed. Commit `2f14e96` adds that session's full
pytest and browser self-check receipt. Those historical results are preserved
below; this continuation's fresh verification is recorded separately.

**Changed so far.** `CLAUDE.md` and `CONTRIBUTING.md` describe the Postgres,
Node, browser/axe, template, Lighthouse and security layers, their commands,
the actual browser engines and the no-retry rule. The pre-commit guidance now
makes clear that hooks cover only a subset of CI. The nine `CLAUDE.md`
invariants are unchanged. `STATUS.md` records the stop after the Phase 1 gate.
The Lighthouse runner and config add strict mobile budgets for Home,
Approvals and Calendar; its separate lab Event Timing check measures real
inputs at 4× CPU slowdown rather than relabelling navigation TBT as INP.
Field p75 INP remains outside what this synthetic measurement proves.
The CI workflow now includes **E2E (Playwright)** and **Lighthouse CI** on PRs,
with browser retries fixed at zero. The three remaining small tests are
present: the enforced CSP response header, a manager approving and scheduling,
and a client requesting changes through the portal. The role variants use
new `data-testid` hooks; existing approval and workspace-isolation assertions
are retained.

**Verification in this continuation (not the final gate)**

| Check | Result | Scope |
|---|---|---|
| Full baseline pytest | 5,530 passed, 1 skipped; 37 warnings; 856.32 seconds (14m 16s); exit 0 | Original PR application/test tree, before this continuation's behaviour fixes |
| Original 126-case browser suite | 120 passed, 3 failed, 3 pending; 13.4 minutes | All three projects, including actual WebKit on iPhone 13; failures were the redirect self-check, one per device |
| Golden paths 1–11 in that baseline | Passed on all three projects | Includes the original paths 6 and 8 |
| Focused follow-up | 21 passed, 0 failed, 0 flaky; 3.5 minutes | Original paths 6, 7 and 8, the manager/client variants and corrected redirect self-check, on all three projects |
| CSP header regression | 1 passed; 2 warnings; exit 0 | Enforced response header, nonce present and no `unsafe-inline` script permission |
| Translation compilation | Exit 0 with GNU gettext 0.23.1 | No project `.po` catalogue exists yet; Phase 4 owns translation rollout |

The pytest skip is
`apps.media_library.tests.test_storage_helpers.FilmstripCacheAliasTest.test_location_is_a_real_server_url_when_the_backend_is_redis`:
`not a Redis-backed deployment`. It is distinct from the three Playwright
TOTP cases pending until Phase 4. The existing main CI coverage baseline is
87% (run `40097544761`); final coverage must not fall below it.

The initial Home measurement found 153,406 gzip JavaScript bytes against the
150,000-byte budget. Loading Chart.js and SortableJS only on the pages that
use them removes that failure without restyling. Ordered deferred loading
and rendering emoji choices only while their picker is open reduce startup
work; regression checks cover the affected initialization and picker actions.

**Mobile performance measurements after those changes** (median of three
audits per page):

| Page | Performance | LCP (ms) | Lab INP upper bound (ms) | CLS | JavaScript gzip (bytes) | TBT diagnostic (ms) |
|---|---:|---:|---:|---:|---:|---:|
| Home | 96 | 1,885 | 168 | 0.078 | 68,862 | 101 |
| Approvals | 93 | 2,308 | 120 | 0.006 | 78,689 | 202 |
| Calendar | 90 | 2,450 | 128 | 0.007 | 78,688 | 249 |

These measurements meet all section 5 targets. The earlier R9 configuration
also gated TBT at 200 ms as a substitute for INP, so that run correctly
reported failure for Approvals and Calendar under that extra proxy check.
The runner now measures real-input lab INP and uses its 200 ms threshold;
TBT remains a reported diagnostic. No section 5 threshold is relaxed or made
a warning. Re-evaluating all nine unchanged Lighthouse reports and their
recorded real-input measurements against the clarified section 5 contract
passes; the receipt hashes each source report and preserves the original
failed summary. This is a re-evaluation, not a fresh navigation run. Final
PR CI must collect fresh measurements before the overall gate can pass.
Synthetic lab INP does not prove field p75 Core Web Vitals.

The new emoji-picker browser regression exposed a modal-focus race in the
test setup. It was quarantined with
[issue #18](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/18)
while the explicit focus-readiness fix undergoes stability verification.
Quarantined cases are reported separately and never counted as passes;
CI retries remain zero.

**Gate, exactly as written in `BETA_PLAN.md` section 6:**

> CI green with all new jobs; 12 e2e tests pass on the old UI.

**Result: pending.** The final full pytest run after the fixes, three
consecutive complete browser runs, Lighthouse budgets and final PR CI must
finish before this record can say passed. The approved Phase 4 exception for
path 12 must be listed as pending in the final totals, not counted as passing.
No merge or release is part of this verification.

## In progress — Phase 1: the test harness

**Changed** (so far; the gate is recorded when the phase closes)

- Dependencies: Pillow's range moves to `>=13.0,<14.0`, and `requirements.lock` now pins Pillow
  13.0.0 and certifi 2026.10.23. That clears the 38 known vulnerabilities `pip-audit` found in the
  lock: 37 in Pillow 12.3.0 and one in certifi 2026.7.22 (PYSEC-2026-4320). Pillow 13.0.0 is eight
  days old; it is taken anyway because it is the only fixed version and several of the bugs are
  memory corruption in parsers that read uploaded files. No other pin, hash or annotation changed.
- The lock's header command no longer has `--no-index`. In pip-tools 7.6.2 that flag means "ignore
  the package index", so the recorded command could not resolve anything (it stops at
  `No matching distribution found for Django`); the new header command, run again, writes the
  committed lock byte for byte. The lock is still written without an index URL
  (`--no-emit-index-url`). This is the only line outside the Pillow and certifi blocks that
  differs.
- CI: a new **Dependency audit** job (`pip-audit` 2.10.1 on the hashed lock, nothing installed;
  `npm audit --audit-level=high` in the repository root and in `theme/static_src`), and
  `compilemessages` in the **Test (pytest)** job after `gettext` is installed.
- `LOCALE_PATHS = [BASE_DIR / "locale"]`, with `locale/.gitkeep` keeping the directory: Django reads
  the project's own catalogues (outside any app) only from `LOCALE_PATHS`.
- **The e2e server** (`python -m tests.e2e.server`, `config/settings/e2e.py`): the web app and the
  worker in one process on `127.0.0.1`, its own database (the name must end in `_e2e`; the server
  refuses any database host or libpq variable that is not this machine), the suite's `FakeTeam` and a
  rule-based account manager, an `httpx` mock transport for the few platform calls the paths make, a
  socket guard that refuses and records every other connection, a fixed seed (workspace A
  `…000a` with owner, manager, editor and client; workspace B `…000b` in another organisation),
  and named, typed fixtures and probes in `tests/e2e/server/steps/`. No endpoint runs code from a
  request; they answer loopback, same-origin, JSON only, and only under `config.settings.e2e`
  (`config/urls.py` never mounts them). Pytest: `tests/test_e2e_server.py` and the per-group step
  tests.
- **Playwright** (`@playwright/test` 1.56.1, `@axe-core/playwright` 4.13.0, `lighthouse` 13.5.0, all
  exact; `npm audit` 0), `playwright.config.ts` with Desktop Chrome, iPhone 13 (WebKit in CI;
  Chromium with the iPhone 13 device here, where WebKit cannot be downloaded) and Pixel 7, one worker,
  no retries; an axe helper (WCAG 2.2 AA tags, fails on serious or critical); a browser network guard
  (outside requests aborted; a redirect followed off the server fails the test); the harness's own
  self-checks in `tests/e2e/self/`; `tests/e2e/README.md`.
- **The 12 golden paths** in `tests/e2e/golden/`, written against today's UI as mapped in
  `01-harness.md`: 1 sign-in (email and a mocked Google), 2 today's onboarding steps (brand, connect
  X through a mocked OAuth, Use me as lead, first brief), 3 ask the team, 4 compose with an override
  and a library image, 5 Approve & schedule with the fingerprint, 6 request changes in a two-stage
  workspace, 7 calendar drag (real drag on desktop; the page's own drop handler on the touch
  projects), 8 client portal sign-off, 9 inbox from a signed webhook, 10 brand colour and the
  organisation timezone, 11 workspace isolation (every workspace-B URL refused, 403 or 404, never
  B's data), 12 TOTP as the one declared pending test (`test.fixme`; TOTP is Phase 4). `data-testid`
  hooks were added next to the existing attributes in the templates the paths touch.
- **Defects the paths found and fixed** (each with a red test first): in a two-stage workspace, a
  post sent back at the client stage left its brief "approved" with no way to send it to the team
  (`services.reopen_sent_back`, only when a channel was sent back or rejected and none still carries
  an approval; `apps/studio/tests/test_two_stage_send_back.py`); the brand page's colour inputs now
  render from the form's own widget; the composer's channel pills are toggle buttons with a pressed
  state; the open inbox message scrolls with the keyboard on a short screen (axe
  `scrollable-region-focusable`).
- **Date-dependent tests** (owner-approved, 25 Oct): five studio tests hard-coded the week of
  19 October and began failing on every branch, `main` included, once the date passed 24 October.
  Their dates are now computed from today in the workspace timezone; every assertion is unchanged.
  `test_insights.py::test_the_plan_queues_the_months_articles_for_the_seo_team` failed in the last
  week of every month because of query order; it now reads oldest first.

**Checked on the merged branch** (26 Oct): full pytest `5530 passed, 1 skipped` (17 min); CI on
PR #17 green on all seven checks; e2e on all three projects `120 passed, 3 skipped` (path 12, the
declared pending test) and 3 failed: the harness's own redirect self-check, broken by merging two
groups' versions of the browser network guard. It now asserts the `escaped` record the kept guard
makes; `tests/e2e/self` 36/36 on three projects.

**Not done yet in Phase 1** (left when the session's credits ran out, 26 Oct): Lighthouse with the
section 5 budgets (`.lighthouserc.json`, `tests/lighthouse/run.mjs`; the package is installed); the
**E2E (Playwright)** and **Lighthouse CI** jobs in `ci.yml`; the P1 items (CSP header test, the
client variant of path 6, the manager variant of path 5); `CLAUDE.md` and `CONTRIBUTING.md` (the e2e,
Lighthouse, audit and `compilemessages` commands, and the "CI runs exactly these" sentence); group
1's open review point (path 11 sweeps workspace-B ids in URL paths only, not in form bodies or query
strings, and leaves out the Agent API); the gate itself; and the owner's branch ruleset making CI
required on `main` (R11: needs GitHub admin rights).

## 24 Oct 2026 — Phase 0: agree the cut

**Changed**

- The owner confirmed every decision in section 2 and five resolutions: Blog on where a blog
  website already exists; TikTok hidden with Bluesky, Mastodon, DEV.to and Threads behind
  `extra_providers` (connected accounts keep working); the Agent API, API keys, MCP and OAuth
  leave the navigation only; Pricing redirects to Request invite; Routines live in Activity with
  the three presets and the free-form form under Settings → Advanced.
- `docs/BETA_PLAN.md` (the plan, sections numbered 1–8, decisions recorded), `docs/specs/00-cut.md`
  (the spec) and `docs/specs/phase-0.md` (the plan for this phase).
- `AgencySettings.features`: a JSON object with a database default of `{}` (migration
  `studio/0008_agencysettings_features`, one additive column), read only through
  `apps.common.features.feature_enabled(workspace, key)` with the keys `blog`, `queues`,
  `templates`, `extra_providers` and `advanced_settings`. An unknown key raises; a key left out takes
  its default (Blog on where an enabled blog website exists, everything else off); a workspace
  without settings gets the defaults and no row is created.
- `AgencySettings` in the Django admin (staff only) so switches can be set before Settings exists;
  the form refuses anything but known keys with true or false, an emptied box saves as empty, the
  workspace cannot be changed on an existing row, and no other organisation's accounts are listed.
- Nothing a person sees in the product changed; no template, view or URL reads the switch yet.

**Gate** (`spec approved; migration passes makemigrations --check`) — on commit `b54b6c1`:

- `python manage.py makemigrations --check --dry-run` → `No changes detected` (exit 0).
- `sqlmigrate studio 0008` → `ALTER TABLE "studio_agency_settings" ADD COLUMN "features" jsonb DEFAULT '{}'::jsonb NOT NULL;`
- Full suite (section 7 rule): `5415 passed, 1 skipped` in 14 min 8 s, 0 failed.
- ruff check and format, mypy (924 files), `test:ui` (30/30), `recolor.py --check`: clean.
- Reviews: three independent passes; every finding fixed with a failing test first, or recorded
  as a Phase 2/3 question in `00-cut.md`.
- Spec approval: **approved by the owner, 24 Oct 2026.** Phase 0 gate passed.

**Released** — 24 Oct 2026, main `6d9cf1d` (PR #15, squash) on both Railway services: web
deployment `431540ad`, worker `c33a6a5a`. The release step applied `studio.0008_agencysettings_features`
(`db.migrations: 0 unapplied` after it); the new worker took over the single-worker lock from the
old one and reported its schedules verified; no error about the new column in either service's
logs. `live_verify` in the release step: 48 passed, 1 failed (More Space's Instagram account is
`@morespace.ai`, not the expected brand account, as before this release), 5 blocked on the owner (no
X app, no LinkedIn company app, the Meta webhook token unset, X not connected for either brand),
11 info. `/health/` answered 200 to Railway's health check. Rollback: web `a483e2c6` and worker
`fcca5126` (`38f4eab`); the added column stays, since the previous code ignores it and its database
default covers that code's inserts.
