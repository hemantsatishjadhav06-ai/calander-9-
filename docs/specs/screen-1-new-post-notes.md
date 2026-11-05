# Screen 1 · New post sheet — shaping notes

Plan task T14 ([`phase-3.md`](phase-3.md), Part B), for the spec's screen 1
([`03-rebuild-screens.md`](03-rebuild-screens.md), "P0 — Screen 1"). Written 2 Nov 2026, after the
owner signed off the shell. Shaped at 390 px first, then at 1440 px. No code is written here; T15–T21
build it, and the points under "Open decisions" are not for a builder to settle alone.

## How it was shaped

- **Skill.** `frontend-design` is not installed in this environment, so `impeccable`'s shape step
  stands in for it (the plan's rule for each screen's Start task). Mode: *Operate*. The person is in
  the middle of a task, so familiar controls and quick, plain answers matter more than flourish.
- **Brief.** Screen 1 in the spec and T14–T25 in the plan, both approved by the owner, plus D5 (one
  primary, one place), D7 (motion), D8 (inline confirms and the paid-act line), D12 (`#new-post`, no
  new URL), D15 (copy) and D16 (keys). This run had no way to put questions to the owner (it is one
  step of the plan's runner), so the brief comes from those documents. Anything they do not settle is
  marked **Assumed** below or listed as an open decision.
- **Visual authority.** [`docs/DESIGN_SYSTEM.md`](../DESIGN_SYSTEM.md) ("Quiet graphite + Pine"):
  §10.1 (primary and `.ui-fab`), §10.3 (forms), §10.9 (sheet, inline confirm), §11 (shell, phone bar,
  `has-fab`), §8 (`--dur-snap`, `.motion-sheet-*`).
- **Evidence.** The *before* side of `tests/e2e/pairs/01-new-post.pair.ts`, taken from main
  (`045978b`) at 390 × 844 and 1440 × 900: Home, the New menu open (on a phone: the drawer first, then
  New), the New idea dialog, Calendar month. Also this branch's Home and Calendar at 390 px (the shell
  as signed off). The images go to the owner with the PR. They are not committed.

## What it costs today (the before pair)

- **Phone.** It takes three taps to reach either act: the menu button (or *More*), then *New*, then
  *Post* or *Idea*. The New menu sits inside the drawer, under the workspace switcher. *Post* leaves
  the page for the composer. *Idea* opens a full-screen dialog in which the heading wraps to
  "New / idea" because the column and tag pills crowd it, the button says "Save Idea" in title case,
  and half the screen is empty. No form anywhere reaches the team (`studio:create`): asking the team
  means scrolling Home down to the thread ("Create with the team" is below the fold at 390 px on this
  branch).
- **Desktop.** *New* is a secondary button at the top of the sidebar. Its menu mixes two acts (Post,
  Idea), each with a subtitle, and two links (Ideas, Import from CSV). It is shown to everyone in the
  workspace, so viewers and clients get links that answer 403.

## The idea in one line

**One button, one sheet, three ways to start.** The sheet is where the person picks how to start
a post. The default, *Ask the team*, is the product's own promise (your team makes it). *Write it
myself* is a one-sentence step to the editor. *Save it as an idea instead* lets the person park the
thought. The moment that matters: one tap opens the sheet with the keyboard up and the cursor in
"Your idea".

## 390 px (shaped first)

Top to bottom, with what each part is for:

1. **Trigger.** `components/primary_action.html`, labelled **New post**: a `.ui-fab` 56 px pill (plus
   icon and words), 16 px from the right, its bottom at `4.5rem + safe area` (above the phone bar, on
   the toasts' line), `z-20` (under the drawer and every dialog). The page sets `has-fab` on the body:
   toasts rise above the button, and it hides under `has-selection` and `has-approval-selection`, so
   it never covers a selection bar. The page's last line scrolls clear of it through the 8.5rem
   spacer. One tap opens the sheet. On Calendar month it floats over the grid's right-hand column
   while the page scrolls; the scroller's bottom padding keeps a focused cell clear of it
   (WCAG 2.4.11), and screen 4 owns the cells' touch controls.
2. **Scrim and sheet.** `.ui-overlay` (ink-950 at 35 %) behind a bottom sheet: `rounded-t-2xl`,
   `max-h-[92vh]`, white surface. The grabber (36 × 5, ink-300, §10.9) is decorative and
   `aria-hidden`. A tap on the scrim closes the sheet; what was typed stays for next time, so closing
   loses nothing. **Assumed:** the floating button hides while the sheet is open (the sheet covers
   it anyway; its `aria-expanded` reads `true`).
3. **Layout.** The sheet is a flex column with three parts: a header, a body that scrolls, and a
   footer that stays put (the `data-decision-bar`, within thumb reach).
   - *Header:* `<h2 id="new-post-title">` "New post" (`text-h2`) on the left, the close icon button
     (44 px) on the right. Below it, full width, the segmented control **Ask the team** ·
     **Write it myself**: two buttons with `aria-pressed` in a `role="group"` (the selected segment
     is ink, never Pine, §9). This matches the Approvals review control. **Assumed:** the group's
     label is "How to start".
   - *Body:* the panel for the mode (`data-view`), then the foot links.
   - *Footer:* the error line (shown only when there is one), the allowance line (Ask the team only),
     and one row: the panel's secondary act on the left and its one primary on the right.
4. **Ask the team** (`new-post-team`, the default).
   - **Your idea:** a textarea, `new-post-team-idea`, required, at most 2,000 characters. Its label is
     the form's own ("Your idea"). It shows 4 lines and grows to about 8. **Assumed:** a quiet count
     ("1,840 of 2,000") appears only past 1,800 characters.
   - **Post to:** the channels, `new-post-team-channels`, are checkboxes for `studio_accounts`, with
     the form's own preselection (the first LinkedIn account, or else the first account). The form
     refuses an empty choice ("Choose at least one connected account."), so the preselection stays
     visible rather than tucked under *More*.
   - **More** (a disclosure, closed by default): *Goal* ("Let the strategist decide" first),
     *Direction for the team (optional)*, *Picture* ("The team makes the picture", or one of the
     library's photos, D15), and the look checkbox (see open decision 6).
   - **Help line** under the fields: "Your manager replies with what we're making. Nothing is made
     until you go ahead."
   - **Footer:** the allowance line, "This starts the team's work and counts toward this month's
     allowance." (D8's exemption, beside *Send*). On the left, **Save it as an idea instead**
     (`new-post-save-idea`, a link-style ghost). On the right, **Send** (`new-post-team-send`, the
     sheet's one primary, `hx-disabled-elt` while in flight).
5. **Write it myself** (`new-post-self`). One sentence: **Assumed** "Write the post yourself in the
   editor: words, pictures, channels and a time." The footer holds **Open the editor**
   (`new-post-self-open`, this view's primary) → `composer:compose`. With the `templates` switch,
   *Start from a template* sits as a secondary link in the body. When the sheet was opened from a
   Calendar cell, the sentence is followed by the time in words, in the workspace's zone
   (**Assumed:** "The editor opens on Tue 3 Nov at 10:00."). That is not a proposal and not a
   schedule; it only fills the editor's fields.
6. **The idea form** (the third view, reached by *Save it as an idea instead*). The heading text
   becomes "New idea". Same `id`, so the dialog's static `aria-labelledby` names it either way.
   Column (`ui-select`), title (`idea-title`, focused), description (`idea-description`), the
   picture, the emoji picker (`idea-emoji-*`, its 95 options rendered only while open), and tags
   only with the `templates` switch. The footer holds **Save idea** (this view's primary; sentence
   case replaces "Save Idea", the shell audit's L1) and, on the left, **Back to New post**, which
   returns to Ask the team with the text untouched (**Assumed**: the spec gives no way back except
   closing; see open decision 2). On touch the drop zone reads as a button ("Add a picture");
   drag and drop is for desktop.
7. **Foot links**, at the end of the body above the footer: Ideas, Drafts (Calendar's Drafts tab),
   Import from CSV, and Templates and Categories with their switch. They are standalone links
   (§10.2), each 44 px tall on touch, in one wrapped row.
8. **A refusal.** Send answers 400 with one sentence, and the footer's error line
   (`new-post-team-error`, `role="alert"`, danger-500, with the 14 px alert icon, §10.3) shows it
   above the buttons, so the sentence is next to the button the person just pressed even when the
   body is scrolled. No toast appears, nothing is made, the text stays, and Send works again. The
   sentences: "This month's allowance for the team is used up. An owner can raise it in Settings →
   Autopilot."; "Your team isn't connected yet. Ask the workspace owner to finish Set up."; the
   form's own words for an invalid field ("Choose at least one connected account."); and, past the
   rate limit, 429 with "You've sent a lot in the last minute. Try again in a moment." (open
   decision 8, settled). At the daily reply cap there is no refusal: the idea is saved and the
   person lands on its thread with `started.note`. Nothing says "is with your manager" then.
9. **Focus and keys.** Opening the sheet closes the phone drawer first, then puts focus in the first
   field of the mode: Your idea, *Open the editor*, or the idea's title. Tab stays inside the sheet
   (`x-trap.noscroll`). Escape or close returns focus to whatever opened the sheet (the button, or
   later a Calendar cell).
10. **Motion.** The sheet rises (translateY 100 % → 0) in 200 ms (`--dur-snap`, `--ease-out`) and
    leaves in 140 ms (`--dur-exit`). The scrim fades over the same times. Switching mode swaps the
    panel at once, with no slide. The error line appears without motion. Under reduced motion the
    sheet appears in place with no transform (`.motion-sheet-*`'s reduced form).

## 1440 px (the drawer)

- **Trigger.** The same component, `lg:static`, in the page header's `data-primary-slot="header"`,
  at the right end of the title row: beside the greeting on Home, beside "Publish" on Calendar. It is
  an ordinary md primary there (36 px), the page's one solid button.
- **Drawer.** On the right, 480 px wide, full height, white, `shadow-xl`, a hairline on its left
  edge, over the same scrim. The page stays visible on the left, so a person who came from a
  Calendar cell still sees the week. It enters with translateX 100 % → 0 in 200 ms and leaves in
  140 ms. Padding is 24 px (the desktop card rhythm). The header, body and footer are the same
  parts as on the phone. The footer is the drawer's bottom edge (border-top): the secondary act on
  the left, the primary on the right, with the allowance and error lines above them.
- **Measure.** At 480 px the textarea is about 430 px wide, roughly 60 characters a line at 15 px:
  a comfortable measure for a short idea. *More* opens in place; nothing needs two columns.
- **From a Calendar cell** (T17, desktop first): the "+" sends `new-post:open` with the cell's date,
  time and account. The drawer opens in Write it myself with the time sentence. Without JavaScript,
  the "+" still goes straight to the composer.
- **Keys** (T20): `n` opens the sheet where the button is (otherwise it goes to Home's `#new-post`),
  Ctrl/Cmd-K does nothing while the sheet is open, and Escape closes it.

## States and ranges

| State | What shows |
|---|---|
| Owner, manager, editor | the button on Home and Calendar; the sheet |
| Viewer; plain client | no button and no sheet (Home stays 403 for a client; a direct POST answers 403) |
| No connected account | **Open decision 4**: Ask the team cannot succeed (the form needs one account) |
| Idea: 1–2,000 characters | grows to about 8 lines, then the body scrolls |
| Channels: 1 to about 8 accounts | checkboxes that wrap; the preselected one is visible |
| In flight | Send disabled (`hx-disabled-elt`) and busy; the sheet stays open |
| Success (job started) | lands on the idea's own thread; info message "Your idea is with your manager. What we're making appears here in a moment." |
| Saved, no job (daily cap) | lands on the idea's thread; the message is `started.note` |
| Refused before saving | the sentence in the footer's error line; nothing made; the text kept |
| Opened with `#new-post` | the sheet opens on load for someone who may start posts; nothing happens for anyone else |

## Re-grep for D8 (inline confirms)

Screen 1's own parts (the New menu, the idea and tag dialogs and their scripts in `base.html`, and
`studio:create`) hold no `hx-confirm` or `confirm(`, and no destructive act. The only paid act is
*Ask the team*'s Send, which is exempt, with the allowance line. Removing a picture from an idea
happens only in the browser. The idea dialog's missing-token path uses `window.alert`, a browser box
but not a confirm; T18 drops it with the dialog.

The sheet's two pages hold more than D8's Home row lists. Home includes the routine rows
(`studio/index.html:173` → `studio/partials/routine_rows.html`), so the routine *Delete* (`confirm()`,
`:47`) and the unconfirmed *Run now* (`:36-39`) show on Home as well as on Activity. Home's thread
and journeys hold two more acts that start the team's work without a confirm: a proposed routine's
*Turn on* (`studio/partials/thread_messages.html:56`) and *Continue* on an idea in progress
(`studio/partials/customer_workflow_journeys.html:25`, `studio:workflow_resume` → `start_idea`). The
spec's D8 table now lists these under Home. The morning briefing's one tap (`studio/index.html:179`)
is left out: that routine is built by code and needs no provider or budget. Calendar's row already
covers what the re-grep found there (the event delete, the bulk dialog). The row now names its
confirm modals explicitly.

## Open decisions (not for a builder to invent)

1. **The grabber.** §10.9 draws one on every bottom sheet, but screen 1 has no drag-to-close. Keep
   the grabber as a visual cue only (default), or add a drag to close?
2. **A way back from the idea form.** The spec reaches the idea form from *Save it as an idea
   instead* but gives no way back except closing. Default: a *Back to New post* control that keeps
   what was typed.
3. **Carry the typed idea into the idea form?** It would be natural (title from the first line,
   description from the rest), but the spec does not say so. Default: no carry-over; the idea form
   starts empty.
4. **No connected account.** `BriefForm.clean_accounts` refuses an empty choice, so with no account
   Ask the team can only fail. Proposed: the panel says so before anything is typed and points to
   Settings → Accounts (wording to agree); Write it myself and the idea form still work.
5. **Idea refusals.** Today a refused idea shows in the error toast (`htmx-error`). In the sheet the
   refusal could show in the idea form's own error line, like Ask the team's. Default: inline.
6. **The look checkbox's words.** The plan says *Keep the brand look*; the form said "Match the
   look of the last post" (`apps/studio/forms.py`). Settled in T16's review: the sheet says the
   plan's and spec's words, *Keep the brand look* (`BriefForm`'s label; no other template renders
   the form). They are also the thread's words for the same choice: `style_lock` on is "the brand
   look" and off "a fresh layout" (`apps/studio/chat.py`, "Choose the brand look or a fresh
   layout"; `jobtypes/chat.py`, "The brand look will be followed."). Ticked, the team follows the
   look of the workspace's latest post, or the brand profile's defaults before anything has posted;
   unticked, it picks a fresh look within the brand (`apps/studio/style.py`). The owner may still
   choose other words.
7. **The keyboard on iOS.** `max-h-[92vh]` does not shrink when the keyboard opens, so the footer
   (with *Send*) can sit under the keyboard while the person types; they close the keyboard, then
   tap *Send*, as in most iOS sheets. `92dvh` would follow the visible area (iOS Safari 16+ supports
   it). The spec pins `vh`, so this is the owner's call; WebKit in CI (T21) shows it.
8. **A rate-limited Send.** Settled in T16b. `studio:create` carried `@ratelimit(..., block=True)`
   with no `RATELIMIT_VIEW`, so the eleventh Send in a minute raised `Ratelimited`, answered the 403
   page, and the sheet's inline error would have printed that page's text ("403 … You don't have
   permission to view this page …"). The decorator now has `block=False` with the same rate
   (10/m), key (`user`), method and group (named after `create`, which it still wraps), and `create`
   reads `request.limited` before anything else: from the sheet (`request.htmx`) it answers 429 with
   one sentence, "You've sent a lot in the last minute. Try again in a moment." (no numbers), through
   the same fragment as the 400 refusals, and nothing is made; without HTMX it raises `Ratelimited`
   as the decorator did, so the page still gets the 403 page. `base.html`'s `htmx:responseError`
   handler needed no change: htmx 2 reports every 4xx and 5xx there (`responseHandling`'s
   `[45]..`), and the handler writes any status's text into `data-inline-error`. Pinned in
   `apps/studio/tests/test_new_post_sheet.py` (the 429 sentence and nothing made; the page's 403;
   the rate and key; the limit before every other check, with and without HTMX).
9. **Two ways to ask the team on Home.** Home keeps its thread composer (goldens 02 and 03), and the
   sheet's Ask the team starts a separate thread for the idea. Screen 2 decides how Home words its
   thread so that the two do not read as the same act.
10. **Where the help line sits** (from T16's review, for the owner and T25's audit). The spec puts
    "Your manager replies with what we're making. Nothing is made until you go ahead." under the
    button (`03-rebuild-screens.md`, *Ask the team*); the plan's T16 does not say where, and these
    notes (4, *Help line*) put it under the fields. T16 built it there: the last line of the panel's
    scrolling body, just above the sticky footer, which keeps to the error line and one row (the
    allowance line beside *Send*). Moving it under *Send* would add about two lines to the sticky
    footer on a phone, over the 92vh sheet and the keyboard (7). Default: under the fields, as
    built; T24's baselines photograph whichever stands.

## What T14 added beside these notes

- `SCREENS["new_post"]` in `apps/common/screens.py`. Its templates are the sheet
  (`components/new_post_sheet.html`) and its three panels (`studio/partials/new_post_team.html`,
  `studio/partials/new_post_self.html`, `composer/partials/new_post_idea.html`). Its fragment is
  `studio/partials/new_post_team_error.html` (T15's 400 answer). Its pages are Home and Calendar
  (`PAGE_TEMPLATES` already maps both), its roles owner, manager and editor, and it is not gated.
  The four templates are comment-only stubs that render nothing, so the registry's
  "every template exists" check holds; T16–T18 fill them.
- `tests/e2e/pairs/01-new-post.pair.ts`: the *before* block, which uses only main's hooks and was
  taken from main on 2 Nov, and the *after* block, which names screen 1's hooks and fails until they
  exist.
- D8's table in the spec updated from the re-grep above.
