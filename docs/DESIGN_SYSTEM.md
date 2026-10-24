# SM Bean design system: Quiet graphite + Pine

Version 2 · 23 Oct 2026 · Light mode · Replaces warm stone + orange + Georgia

Paths are relative to the repository root.

| Where | What it is |
|---|---|
| `docs/DESIGN_SYSTEM.md` (this file) | The spec: decisions, tokens, components, screens, verification. |
| `theme/static_src/src/styles.css` | The tokens and the shared CSS. **Part A**: the palette lock (`--color-*: initial`), Layer 1 raw scales (the only place an app colour hex lives), the `@theme` utilities (`bg-ink-50`, `text-brand-700` …), Layer 2 semantic tokens (`--surface-page`, `--text-secondary`, `--focus-ring` …) and Layer 3 component tokens. **Part B**: base rules (focus, selection, reduced motion, forced colours), the component classes (`.btn-*`, `.ui-input`, `.bb-toggle`, `.sidebar-nav-item` …) and the live-team parts (`.live-dot`, `.stage-track`, `.receipt`, `.hour-chart`, `.timeline`). Tailwind v4 compiles it from the templates (`cd theme/static_src && npm run build`); the output under `theme/static/css/dist/` is built in Docker and never committed. |
| `static/css/marketing.css` | The public site's own stylesheet. It does not load the Tailwind build, so it repeats the same values as literal `--mk-*` variables. |
| `tools/recolor.py` | The codemod that moved templates, static JS and Python class strings from stone, orange and the other default palettes to these scales (role-correct steps, not 1:1), and the guard: `python tools/recolor.py --check` lists any old palette class, mapped hex or orange marketing screenshot left anywhere and exits 1. |
| `templates/studio/partials/status_badge.html`, `templates/approvals/partials/_status_badge.html` | The status pills (10.5): the one place a status gets its tone, icon and word. |
| `templates/studio/index.html`, `templates/studio/team.html`, `templates/studio/partials/live_strip.html` | Home, the Team view and Home's "Right now" card: the reference screens for sections 13 and 14. |
| `apps/common/tests/test_a11y_sweep.py`, `apps/common/tests/test_marketing_screenshots.py` | Checks that keep the rules: no words in `text-ink-300`/`text-ink-400`, labelled dialogs and controls, no orange interface left in the marketing screenshots. |

The palette, the contrast tables in section 23 and the reference mock-ups were produced in the October 2026 design round; its working scripts and mock-ups are not kept in the repository. The live screens listed above are now the reference.

---

## 1. Concept

**The work is the colour.** SM Bean is a calm, cool graphite workspace in the spirit of a native Mail or Settings window: a pale grey canvas, white cards with a hairline, the phone's own system font, and hierarchy carried by size and weight. One deep **Pine** green (`#115641`) is the only colour the interface owns, and it means one thing: *this is yours to act on* (the one primary button in a view, links, focus, a checked control, the Approvals count). Pine was chosen on evidence: it sits 87–94° of hue and 20.8–30.1 OKLab units away from LinkedIn and Facebook blue (and stays 20.3 away for deuteranopes, where a violet collapses to 7.8), 120° from the Neopolis orange, and 14.2 units from the success green it must never be mistaken for. Everything else is graphite, so a client's navy-and-orange post, a LinkedIn glyph and the Instagram gradient are always the most colourful things on screen. The always-on team gets its own visual language built from the same parts: a status dot with a word, a stage track for each job, an hour-bar chart of the last day and a timeline of the next one.

---

## 2. Principles

1. **One accent, one meaning.** Pine marks *your move*: the single solid primary per view, tinted buttons for repeated row actions, links, focus, selected controls, the Approvals badge, the active sidebar icon. Nothing decorative is ever Pine.
2. **Busy is not urgent.** Work in the team's hands (working, queued, publishing, scheduled) is petrol *info*, never the accent. Waiting for a person is amber *warning*. Done is leaf *success*. Stopped is red *danger*.
3. **Weight before colour.** Titles are ink-950 at 700/600, body ink-900, secondary ink-600, tertiary ink-500. No coloured headings, no uppercase labels.
4. **Content keeps its colours.** Creatives, client brand colours and platform glyphs render as they are, framed only by a neutral hairline. The interface never borrows them and never tints them.
5. **Status is never colour alone.** Every status has a shape (icon or dot form) and a word, rendered by one partial. Status hues are lightness-staggered so they separate for colour-blind people too.
6. **Depth is functional.** Hairline plus a 1px shadow for cards; real shadows only for what floats (menus, toasts, modals). No hover lifts, no coloured glows, no gradients in the app.
7. **Motion explains a change, then gets out of the way.** 100–320ms, ease-out, no overshoot except the toggle knob; every animation has a reduced-motion equivalent that keeps the meaning.
8. **Accessible by construction.** WCAG 2.2 AA everywhere (144 pairs checked, section 23), real 2px focus outlines that survive forced-colours mode, 24px minimum targets (44px on touch), sentence case, 12px minimum for words.

---

## 3. Palette

All values were generated in OKLCH and converted to sRGB; Layer 1 of `styles.css` holds them. Tailwind utilities use the scale names directly: `bg-ink-50`, `text-brand-700`, `ring-success-200`, `bg-info-500`.

### 3.1 `ink`: cool graphite neutrals (OKLCH hue 258, chroma ≤ 0.015)

Kept exactly from the chosen direction (both design reviews re-verified them).

| Step | Hex | Role |
|---|---|---|
| 0 | `#FFFFFF` | Cards, inputs, popovers, active nav pill |
| 25 | `#FBFCFD` | Table header, row hover on white, internal-note fill |
| 50 | `#F6F7F8` | **App canvas**, sunken boxes inside cards, empty creative tiles |
| 100 | `#EDEFF2` | **Sidebar**, your chat bubble, neutral chip, segmented track, skeleton, disabled fill |
| 200 | `#E1E4E8` | Hairlines, dividers, card edges, chart track, stage connectors (decorative) |
| 300 | `#CED2D7` | Secondary-button edge, clickable-card hover edge, table header rule, chart baseline |
| 400 | `#83888F` | **Control boundary** (inputs, checkbox, toggle-off, waiting node, idle ring, hour bars): ≥ 3.10:1 on every surface. Never text. |
| 500 | `#656B73` | Tertiary text, placeholders, meaningful icons, neutral status icon (≥ 4.67:1 on every surface) |
| 600 | `#52575F` | Secondary text; the lightest text allowed on translucent bars |
| 700 | `#3E434A` | Body-2, ghost button labels, neutral chip text |
| 800 | `#2E3238` | Strong secondary, receipt text |
| 900 | `#1C1F24` | **Primary text**, toast and tooltip fill, selected filter chip, tab underline, account-manager avatar, current-hour bar, "Now" line |
| 950 | `#0E1114` | Titles, active nav label, marketing dark band |

### 3.2 `brand`: Pine (OKLCH hue 168)

| Step | Hex | Role |
|---|---|---|
| 50 | `#EFFAF5` | Selected table row / list row |
| 100 | `#DDF3EA` | **Tinted button** fill, text selection |
| 200 | `#BFE7D6` | Tinted button hover; marketing on-dark CTA fill |
| 300 | `#94D2BA` | Action text on the dark toast ("Undo") |
| 400 | `#62B194` | Decorative only (never text, rings or icons) |
| 500 | `#388E71` | Decorative only (`--primary-bright`) |
| 600 | `#1E7057` | **Focus ring**, focused field edge, progress fill (≥ 4.79:1 on every surface) |
| 700 | `#115641` | **Primary fill**, links, checkbox/toggle on, active nav icon, Approvals badge, tinted-button text (white on it 8.64:1) |
| 800 | `#0D4534` | Primary hover, link hover, tinted-button hover text |
| 900 | `#0B3629` | Primary pressed |
| 950 | `#062118` | Text on the marketing on-dark CTA; dark-mode reserve |

Primary sits at **700** and hover at **800**: the same steps the old orange used (`orange-700` 288 uses, `orange-800` 116), so the codemod was a same-step rename for the common case.

### 3.3 Status scales

Role per step, identical for all four: **50** soft fill · **100** soft hover · **200** hairline ring · **300** icon on the dark toast · **400** decorative · **500 icon / dot / solid** · **600 text** (chip and inline) · **700–950** darker text, alert titles, dark-mode reserve.

The icon steps are deliberately staggered in lightness (danger L 0.44 → info 0.44 → warning 0.53 → success 0.625), and the text steps too (danger 0.38 → info 0.40 → warning 0.455 → success 0.53), so the statuses stay apart under protanopia and deuteranopia (closest icon pair 7.9, section 23).

| Step | success (leaf, h 145) | warning (amber, h 80→55) | danger (red, h 27) | info (petrol, h 232) |
|---|---|---|---|---|
| 50 | `#EDFCED` | `#FFF7EB` | `#FFF3F1` | `#EFF8FD` |
| 100 | `#DAF8DA` | `#FFEED4` | `#FFE4E0` | `#DDF1FC` |
| 200 | `#BCF0BC` | `#FFDDAE` | `#FFCDC6` | `#BEE3F8` |
| 300 | `#95E097` | `#FFCA82` | `#FEA69C` | `#95CDEB` |
| 400 | `#6CC871` | `#FCAA38` | `#EF675C` | `#4F9CC2` |
| **500** icon | `#429E4A` | `#9B5A00` | `#991618` | `#035A7B` |
| **600** text | `#317F38` | `#7F4700` | `#7C1213` | `#044E6B` |
| 700 | `#28682D` | `#683904` | `#6A0E0E` | `#064058` |
| 800 | `#215525` | `#552C04` | `#570E0D` | `#073548` |
| 900 | `#193F1B` | `#432105` | `#450D0B` | `#082A3A` |
| 950 | `#0E2810` | `#2C1302` | `#2C0806` | `#041B26` |

| Status | Meaning | Words that use it |
|---|---|---|
| success | it happened | Approved, Published, Connected, Done, Draft ready |
| warning | a person is needed | Ready for approval, Waiting for client, Changes requested, Partly published, Needs you, Expires soon |
| danger | it stopped | Failed, Rejected, Stopped, Disconnected; destructive actions |
| info | in the team's hands | Working, Queued, Publishing, Scheduled |
| neutral (ink) | nothing is happening | Draft, Paused, On hold, Idle, Not possible right now |

### 3.4 Content colours (never UI fills)

LinkedIn `#0A66C2` · Facebook `#1877F2` (2023 mark `#0866FF`) · Instagram gradient `#F58529 → #DD2A7B → #8134AF → #515BD4` · X / Threads / TikTok `#000000` · YouTube `#FF0000` · Pinterest `#E60023` / `#BD081C` · Bluesky `#0085FF` · Telegram `#229ED9` · Google "G" `#4285F4 #34A853 #FBBC05 #EA4335`. Shown only as logo-shaped glyphs at 14–24px or inside platform-faithful previews, always beside the platform's name.

### 3.5 Why Pine (the accent decision)

The owner asked for an Apple-calm interface; the design reviews asked that the accent leave the LinkedIn/Facebook blue band, not fight navy-and-orange creatives, and stay distinct from success. Candidates, measured (OKLab ΔE ×100; 10+ is clearly different side by side):

| Candidate | vs LinkedIn (normal / deuteranopia) | vs Facebook (normal / deut.) | vs Instagram purple | vs success text | White on it |
|---|---|---|---|---|---|
| Graphite indigo `#404DB3` | 6.9 / **4.1** | 13.5 / 12.4 | 11.6 | 27.0 | 7.17:1 |
| Iris violet `#6B36F6` | 14.8 / **7.8** | 13.9 / **5.0** | 12.1 | 37.1 | 6.03:1 |
| Re-stepped ink-violet `#5C4295` | 12.5 / **7.8** | 18.8 / 16.2 | **8.3** | 26.6 | 7.87:1 |
| Harbour sea `#007665` | 16.9 / 16.6 | 22.4 / 21.6 | 26.2 | **7.7** | 5.56:1 |
| Teal-pine `#0A5D51` | 18.2 / 17.9 | 25.7 / 25.0 | 25.3 | 12.9 | 7.79:1 |
| Folio forest `#235342` | 20.5 / 20.2 | 28.2 / 27.6 | 25.6 | 15.0 | 8.80:1 |
| **Pine `#115641` (chosen)** | **20.8 / 20.3** | **28.4 / 27.7** | **26.8** | **14.2** | **8.64:1** |

- Any violet or indigo turns into blue for the 1 in 12 men with red-green colour blindness, landing beside the LinkedIn glyph (ΔE 4–8). Greens keep their distance (≥ 20) because lightness survives the simulation.
- Pine vs success is solved by lightness, not hue alone: the success text step is L 0.53 against Pine's 0.405, so "Approve & schedule" (Pine text) and an "Approved" pill (leaf text) are 14.2 apart for everyone and 14.0 for deuteranopes (Folio's pair was 9.5). On top of that the accent never appears in a status pill, and "Scheduled" after approval uses info, not success.
- Pine is complementary-adjacent to the Neopolis orange (120° hue gap, ΔE 38) and far from the navy (16.4): it never fights a creative.
- On a cool graphite canvas a deep green reads as architect / private bank, which suits Indian real-estate developers and their approvers, without the editorial serif that made Folio feel less native.

---

## 4. Semantic roles

These are the `:root` variables in Layer 2 of `theme/static_src/src/styles.css`. Existing names are kept, so every `var(--…)` already in templates keeps working.

| Role | Variable | Value |
|---|---|---|
| Canvas | `--surface-page` | ink-50 `#F6F7F8` (the inset white main sheet is removed) |
| Card / input | `--surface-0` | `#FFFFFF` |
| Sunken (inside a card) | `--surface-1` | ink-50 |
| Neutral fill | `--surface-2` | ink-100 |
| Sheet (table header, row hover, internal note) | `--surface-sheet` | ink-25 |
| Sidebar | `--surface-sidebar` | ink-100 + 1px ink-200 right edge |
| Translucent bar | `--surface-sticky` | `rgb(246 247 248 / .92)` + blur; ink-600 or darker text only |
| Overlay | `--overlay` | `rgb(14 17 20 / .36)`, no blur |
| Hairline | `--border` | ink-200 |
| Hover edge | `--border-hover` | ink-300 |
| Control boundary | `--border-control` | ink-400 |
| Title / text / body-2 / secondary / tertiary | `--text-strong` / `--text-primary` / `--text-body` / `--text-secondary` / `--text-tertiary` (= `--text-ghost`) | ink-950 / 900 / 700 / 600 / 500 |
| Link / hover | `--text-link` / `--text-link-hover` | brand-700 / brand-800; underlined inside sentences |
| Primary fill / hover / pressed | `--primary` (= `--primary-strong`) / `--primary-hover` / `--primary-pressed` | brand-700 / 800 / 900 |
| Tint (selected row) / tinted button | `--primary-soft` / `--primary-muted` | brand-50 / brand-100 |
| Focus | `--focus-ring` (= `--primary-ring`), `--focus-ring-width` 2px, `--focus-ring-offset` 2px | brand-600 |
| Field halo | `--primary-halo` | `rgb(30 112 87 / .18)` (decorative) |
| Selection | `::selection` | brand-100 background, ink-900 text |
| Person bubble | – | ink-100, ink-900 text |
| Manager / specialist message | – | no bubble; ink-900 text on white, 28px ink-900 avatar |
| Client bubble | – | white + 1px ink-200 + neutral "Client" tag |
| Teammate bubble | – | ink-50 + 1px ink-200 |
| Internal note | – | ink-25, 1px **dashed** ink-400, lock icon, "Note for the team" 12/600 ink-700 |
| System line | – | centred 12/16 ink-500 between ink-200 hairlines |
| Toast / tooltip | – | ink-900 fill, white text, ink-300 detail, brand-300 action |
| Legacy status names | `--success-50/500/700`, `--warning-50/500/700`, `--info-50/500/700`, `--error-50/200/500/600/700`, `--error-soft`, `--warning-soft`, `--success-soft` | re-pointed to the new scales (`--error-*` → danger) |
| Retired | `--shadow-primary` (none), `--accent-*` (re-pointed to status), `--brand-green-*` (re-pointed to brand), `--color-illustration-*` (neutral) | kept only so nothing breaks |

---

## 5. Typography

**Family: the system font. No webfont, 0 KB.** SF Pro on the owner's Mac, iPhone and iPad (with automatic Text/Display optical sizes); Segoe UI Variable on Windows; Roboto on Android. It satisfies CSP `font-src 'self'` with nothing to host, has no fallback flash, and includes the rupee sign. Noto Sans before the generic fallback helps Telugu and Devanagari brand names.

```
--font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, "Noto Sans", "Helvetica Neue", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
--font-mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, "Cascadia Mono", Consolas, "Liberation Mono", monospace;
```

Georgia (app) and Instrument Serif + Inter (marketing, 5 files, 95,428 bytes) are retired. If uniform cross-platform rendering is ever preferred, the OFL Inter variable woff2 already committed at `static/fonts/inter-latin-normal.woff2` (48,432 bytes, 0 new bytes) is the fallback option; it is not used now because native SF Pro is the most "Apple" choice there is.

| Role | Tailwind | px / line-height | Weight | Tracking | Use |
|---|---|---|---|---|---|
| Marketing hero | `text-[64px]/[68px] font-bold tracking-[-0.035em]` | 64/68 (phone 40/44) | 700 | -0.035em | public site only |
| Display | `text-display` | 40/44 | 700 | -0.025em | marketing section titles, login wordmark |
| H1 | `text-h1` | 28/34 (phone 26/32) | 700 | -0.020em | page titles ("Good afternoon, Ana", "Your team", "Set up") |
| H2 | `text-h2` | 20/26 | 600 | -0.015em | card titles (Today, Your team, Working now) |
| H3 | `text-h3` | 16/22 (section heads 17/22) | 600 | -0.010em | row titles, modal sections, "Recent work" |
| Body large | `text-body-lg` | 15/24 | 400 | -0.005em | chat messages, composer, descriptions under H1 |
| Body | `text-body` / `text-sm` | 14/20 | 400 (labels 500, emphasis 600) | 0 | default UI, buttons, rows, forms |
| Table | `text-table` | 14/22 | 400 | 0 | dense tables |
| Small | `text-small` | 13/18 | 400–500 | 0 | meta, helper text, card subtitles, live states |
| Caption | `text-caption` | 12/16 | 500 (pills and group labels 600) | +0.005em | timestamps, pills, group labels, axis labels |
| Micro | `text-micro` | 11/14 | 600 | +0.02em | **numerals only** (count badges) |
| Mono | `font-mono text-[13px]/5` | 13/20 (owner boxes 12/18) | 400 | 0 | setting names the owner must type |

Rules:
- Hierarchy by size and weight only. Negative tracking only at 20px and above.
- **No uppercase, no wide tracking.** Group labels are 12/600 ink-500 in sentence case ("Waiting for you", "Done since yesterday", "Brief").
- Words are never smaller than 12px. Inputs are 16px below 1024px (stops iOS zoom).
- `tabular-nums` on counts, badges, times, dates in lists, budgets, "5 of 11 done", tables, chart axes and the calendar grid; proportional figures in prose.
- Reading measure ≤ 72ch; thread column ≤ 720px.

---

## 6. Shape

Radii use **Tailwind's default scale unchanged**, so no existing `rounded-*` class shifts size (calendar cells and flatpickr stay put).

| Element | Radius | Class |
|---|---|---|
| Buttons, inputs, selects, nav items, segmented track | 8px (segment 7px) | `rounded-lg` |
| Composer, list cards, brief card, popovers, menus, toasts, callouts | 12px | `rounded-xl` |
| Hero cards (Today, thread card, Team cards), modals | 16px | `rounded-2xl` |
| Recent-work tiles | 14px | `rounded-[14px]` |
| Creative thumbnails | 7px at ≤ 56px, 10px larger | `rounded-[7px]` / `rounded-[10px]` |
| Owner box, skeleton blocks | 6px | `rounded-md` |
| Checkbox | 4px | `rounded` |
| Pills, badges, avatars, toggles, filter chips, live dots | full | `rounded-full` |
| Chat bubbles | 18px with a 6px tail corner | `rounded-[18px] rounded-br-md` (yours), `rounded-bl-md` (client) |
| Phone bottom sheet | 16px top corners | `rounded-t-2xl` |

Borders are 1px everywhere (the old 1.5px input borders go; checkbox 1.5px). Hairlines ink-200; control edges ink-400; secondary-button edge `ring-1 ring-inset ring-ink-300` (decorative: the label carries contrast); creatives get `shadow-[inset_0_0_0_1px_rgba(14,17,20,.06)]` so white creatives keep an edge.

---

## 7. Elevation

| Level | Use | CSS |
|---|---|---|
| 0 | canvas, flat content | none |
| 1 | cards, secondary buttons, active nav pill | `--shadow-xs: 0 1px 2px rgba(14,17,20,.05)` + 1px ink-200 hairline |
| 1+ | hovered clickable card | `--shadow-sm: 0 1px 2px rgba(14,17,20,.04), 0 1px 3px rgba(14,17,20,.06)` + ink-300 edge |
| 2 | sticky translucent bars | `background: rgb(246 247 248 / .92); backdrop-filter: saturate(180%) blur(20px); border-bottom: 1px solid rgb(14 17 20 / .06)` (solid ink-50 under `@supports not` and `prefers-reduced-transparency`) |
| 3 | menus, popovers, toasts | `--shadow-lg: 0 12px 32px -8px rgba(14,17,20,.16), 0 4px 8px -2px rgba(14,17,20,.06)` |
| 4 | modals, sheets, marketing product frame | `--shadow-xl: 0 24px 64px -12px rgba(14,17,20,.24), 0 8px 16px -4px rgba(14,17,20,.08)` + overlay `rgb(14 17 20 / .36)` |
| – | primary button | `--shadow-button: 0 1px 2px rgba(14,17,20,.12), inset 0 1px 0 rgba(255,255,255,.12)` |
| – | segmented selected | `--shadow-segment: 0 1px 2px rgba(14,17,20,.08), 0 0 0 .5px rgba(14,17,20,.06)` |
| – | nav active | `--shadow-nav-active: 0 1px 2px rgba(14,17,20,.06), 0 0 0 1px rgba(14,17,20,.04)` |

Removed: the orange glow (`0 4px 14px rgba(249,115,22,.28)`), every `translateY` hover lift, coloured shadows. Translucency is used only on the phone top bar and sticky page/table headers; the bar is 92% opaque (not 82%) so secondary text stays 5.82:1 even with a navy creative scrolling underneath.

---

## 8. Motion

| Token | Duration | Use |
|---|---|---|
| `--dur-instant` | 100ms | hover/press colour, button `:active` scale(.98) |
| `--dur-fast` | 160ms | pill cross-fade, dropdown open, checkbox, toggle, count step |
| `--dur-base` | 220ms | disclosure (grid rows 0fr→1fr) + chevron, popover, row collapse |
| `--dur-slow` | 320ms | modal/sheet, sidebar collapse 240→60px, mobile drawer, Set up tick draw |
| message in | 240ms | new chat message |
| live pulse | 2s loop | working dot and working stage node only |

Easings: enter `cubic-bezier(0.22, 1, 0.36, 1)` (`--ease-out`); size changes `cubic-bezier(0.65, 0, 0.35, 1)` (`--ease-in-out`); exit `cubic-bezier(0.4, 0, 1, 1)` at 70% of the enter duration (`--ease-exit`); toggle knob only `cubic-bezier(0.34, 1.3, 0.64, 1)` (`--ease-spring`).

Transitions that carry meaning:
- **New message:** opacity 0→1 + translateY(6px)→0, 240ms; the "The team is writing" line fades out as the message fades in. Consecutive messages from one agent group under one avatar.
- **Status change** (Working → Ready for approval): 160ms cross-fade of colour, icon and word; the spinner is replaced, never popped. Announced with `aria-live="polite"`.
- **Approve & schedule** (section 12.3): spinner ≥ 300ms → "Scheduled · Mon 10:10" (info) → hold 1.2s → row collapses 220ms → counts step → two-line toast with Undo.
- **Brief started:** a 2px indeterminate info-500 line runs along the brief card's bottom edge until the first agent step arrives.
- **Auto-start countdown:** "Starting in 10 s · Stop" with a 2px info-500 line draining over 10s.
- **Count badges** roll down one digit (4px slide + fade, 160ms).
- **Set up step done:** ring fills success-500, tick draws (stroke-dashoffset 24→0, 320ms), progress widens 320ms, "5 of 11" → "6 of 11".
- **HTMX:** 2px brand-700 bar at the top, width 200ms, fades out 250ms.
- **Popover** translateY(-4px) + opacity 160ms; **modal** scale(.98) + opacity 220ms; **phone sheet** translateY(100%)→0 320ms.
- **Skeleton** shimmer 1.4s linear, shown only after a 300ms delay.

**Reduced motion** (`prefers-reduced-motion: reduce`): all transforms, slides, scales and loops are removed (global rule in Part B of `styles.css`); opacity fades of ≤ 120ms may stay (`.fade-safe`); the row collapse is instant; the working pulse and stage-node pulse stop (the filled dot and the word "Working" remain); spinners become a static ring beside the word; typing dots become the text "The team is writing…"; the skeleton is a static ink-100 block; the countdown updates text only; progress and HTMX bars appear without width animation; smooth scrolling is off.

---

## 9. Focus and selection

- **Focus ring:** `outline: 2px solid var(--focus-ring); outline-offset: 2px;` on `:focus-visible`, globally (Part B). brand-600 measures 5.98:1 on white, 5.58 on ink-50, 5.19 on the sidebar, 5.15 on the tinted button, 4.79 on a translucent bar over a navy creative. It is a real outline, so it survives Windows forced-colours mode (the Graphite must-fix). Utility form for explicit markup: `focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600`.
- **Text fields:** the edge becomes the ring: `border-color: brand-600; box-shadow: 0 0 0 1px brand-600, 0 0 0 4px rgb(30 112 87 / .18); outline: 2px solid transparent` (the transparent outline turns into a system outline under forced colours). No layout shift.
- **Selected states** (not focus): selected row `bg-brand-50` + `aria-selected`; selected filter chip and segment are **ink**, never Pine (`bg-ink-900 text-white`; white segment on the ink track); checkbox/toggle on brand-700; active nav item white pill + 600 weight + brand-700 icon (8.64:1) + `aria-current="page"`. Under forced colours every box-shadow-only state gets `outline: 2px solid Highlight` (Part B).
- **Text selection:** brand-100 background, ink-900 text.
- `scroll-padding-top: 72px` on `html` so a focused control is never hidden under a sticky bar (WCAG 2.2, 2.4.11).

---

## 10. Components (utility recipes use the new scale names)

Global focus styles come from Part B, so the `focus-visible:` classes below are explicit but not required.

### 10.1 Buttons

| Variant | Recipe | Use |
|---|---|---|
| **Primary** (md) | `inline-flex items-center justify-center gap-1.5 h-9 max-lg:h-11 px-3.5 rounded-lg bg-brand-700 text-white text-sm font-semibold shadow-[var(--shadow-button)] hover:bg-brand-800 active:bg-brand-900 active:scale-[.98] transition-[background-color,transform] duration-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:bg-ink-100 disabled:text-ink-500 disabled:shadow-none disabled:cursor-not-allowed` | the single most important action in the view |
| Secondary | `inline-flex items-center justify-center gap-1.5 h-9 max-lg:h-11 px-3.5 rounded-lg bg-white text-ink-900 text-sm font-semibold ring-1 ring-inset ring-ink-300 shadow-xs hover:bg-ink-25 hover:ring-ink-400 active:bg-ink-50 transition-colors duration-100` | "New" in the sidebar, Manage, Change, Run now, Send while a brief waits |
| **Tinted** | `inline-flex items-center justify-center gap-1.5 h-8 max-lg:h-11 px-3 rounded-lg bg-brand-100 text-brand-700 text-[13px] font-semibold hover:bg-brand-200 hover:text-brand-800 transition-colors duration-100` | repeated row actions: Approve & schedule, Use this angle, Approve in Approvals, Answer |
| Ghost | `inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-ink-700 text-[13px] font-semibold hover:bg-ink-900/5 hover:text-ink-900 active:bg-ink-900/10` | Review, Change something, Cancel |
| Icon | `inline-grid place-items-center size-8 max-lg:size-11 rounded-lg text-ink-500 hover:bg-ink-900/5 hover:text-ink-900` + `aria-label` | close, menu, overflow |
| Danger (confirm in a modal only) | `… bg-danger-500 text-white hover:bg-danger-600` (8.46:1) | "Discard post" (the button repeats the verb) |
| Danger ghost (in rows and menus) | `… text-danger-500 hover:bg-danger-50` | Delete, Discard; never a filled red button in a resting list |

Sizes: sm `h-8 px-3 text-[13px]`, md `h-9 px-3.5 text-sm`, lg `h-11 px-[18px] text-[15px] rounded-[10px]`; every size is ≥ 44px tall below 1024px. Loading: keep the width, swap the icon for a 14px spinner, `aria-busy="true"`.

**One solid primary per view.** Repeated actions are tinted. While a brief card waits for *Start*, the composer's *Send* renders secondary. Only the first unfinished Set up step gets a primary. Success green is never an action colour.

### 10.2 Links

- In sentences (status line, messages, help text): `text-brand-700 underline decoration-1 underline-offset-3 hover:text-brand-800` (or `.link-inline` / `.prose a`). The underline is currentColor, so it is as visible as the text (fixes Folio's 2.09:1 and Graphite's 1.77:1 underlines). Pine vs body text is only 1.91:1, so the underline is required by WCAG 1.4.1.
- Standalone (card header "All threads", "Open Team"): `text-[13px] font-medium text-brand-700 whitespace-nowrap hover:underline underline-offset-3`.

### 10.3 Forms

| Part | Recipe |
|---|---|
| Label | `block mb-1.5 text-[13px] font-medium text-ink-900` |
| Input / textarea | `block w-full h-9 max-lg:h-11 rounded-lg border border-ink-400 bg-white px-3 text-sm max-lg:text-base text-ink-900 placeholder:text-ink-500 hover:border-ink-500 focus:border-brand-600 focus:outline-2 focus:outline-transparent focus:shadow-[0_0_0_1px_var(--focus-ring),0_0_0_4px_var(--primary-halo)] aria-[invalid=true]:border-danger-500` (textarea: `h-auto min-h-22 py-2`) |
| Select | input recipe + `bb-select` (chevron stroke `#656B73`) |
| Help | `mt-1.5 text-[13px]/[18px] text-ink-600` linked with `aria-describedby` |
| Error | `mt-1.5 flex gap-1.5 text-[13px]/[18px] text-danger-500` + 14px alert icon; field `aria-invalid="true"` |
| Checkbox | `size-4 rounded border-[1.5px] border-ink-400 accent-brand-700` (or `.bb-checkbox`); 24px hit area via the label, 44px on touch |
| Radio card (brief angles) | `block rounded-xl ring-1 ring-inset ring-ink-200 p-3 hover:ring-ink-300 has-[:checked]:ring-2 has-[:checked]:ring-brand-700 has-[:checked]:bg-brand-50`; chosen shows a brand-700 check + the word "Chosen" |
| Toggle | `.bb-toggle` (36×20 track: off ink-400, on brand-700; knob slides 160ms with the spring easing) |
| Disabled | `bg-ink-50 border-ink-200 text-ink-500` (4.67:1, no opacity fade) |

### 10.4 Cards and rows

- Card: `rounded-2xl border border-ink-200 bg-white p-5 max-sm:p-4 shadow-xs` (nested and list cards `rounded-xl p-4`). Header: `flex items-baseline justify-between gap-3`; title `text-h2 text-ink-950`; subtitle `mt-0.5 text-[13px]/[18px] text-ink-600`; standalone link right-aligned. Clickable: add `transition-[border-color,box-shadow] duration-150 hover:border-ink-300 hover:shadow-sm` (no transform).
- List row: list `divide-y divide-ink-200`; row `flex items-center gap-3 min-h-14 px-4 py-3 hover:bg-ink-25 aria-selected:bg-brand-50`; leading 20–32px status glyph or 44×55 creative thumb (`rounded-[7px] shadow-[inset_0_0_0_1px_rgba(14,17,20,.06)]`); title `text-sm font-semibold text-ink-900`; meta `text-xs text-ink-500 tabular-nums`; trailing actions or `size-4 text-ink-400` chevron.

### 10.5 Status pill, badges, chips

**Status pill** (owned by `studio/partials/status_badge.html` and `approvals/partials/_status_badge.html`; review rejects hand-set status colours):
base `inline-flex items-center gap-1.5 h-[22px] pl-[7px] pr-2 rounded-full text-xs font-semibold whitespace-nowrap ring-1 ring-inset`, 12px icon at 2.5 stroke.

| Tone | Pill classes | Icon class |
|---|---|---|
| neutral | `bg-ink-100 text-ink-700 ring-ink-200` | `text-ink-500` |
| info | `bg-info-50 text-info-600 ring-info-200` | `text-info-500` |
| success | `bg-success-50 text-success-600 ring-success-200` | `text-success-500` |
| warning | `bg-warning-50 text-warning-600 ring-warning-200` | `text-warning-500` |
| danger | `bg-danger-50 text-danger-600 ring-danger-200` | `text-danger-500` |

| Status value | Word | Tone | Icon |
|---|---|---|---|
| `queued` | Queued | info | three dots |
| `working` | The team is on it / Working | info | spinner (static ring under reduced motion) |
| `ready`, `pending_review` | Ready for approval | warning | clock |
| `pending_client` | Waiting for client | warning | clock |
| `changes_requested` | Changes requested | warning | return arrow |
| `partially_published` | Partly published | warning | triangle |
| `approved` | Approved | success | check |
| `scheduled` | Scheduled · Mon 10:10 | info | calendar |
| `publishing` | Publishing | info | spinner |
| `published` | Published | success | check |
| `failed` | Failed | danger | x-octagon |
| `rejected` | Rejected | danger | x-octagon |
| `draft` | Draft | neutral | dash |
| `on_hold`, `paused` | On hold / Paused | neutral | pause |
| connection ok / expired / disconnected | Connected / Expires soon / Disconnected | success / warning / danger | check / clock / x-octagon |

- Count badge: `inline-flex items-center justify-center min-w-5 h-[18px] px-1.5 rounded-full bg-ink-200 text-ink-700 text-[11px] font-semibold tabular-nums`. Your-turn badge (Approvals waiting only): `bg-brand-700 text-white`. Failed-runs count: `bg-danger-500 text-white`.
- Filter chip: `h-8 max-lg:h-11 px-3 rounded-full text-[13px] font-medium text-ink-700 hover:bg-ink-100 aria-pressed:bg-ink-900 aria-pressed:text-white aria-pressed:font-semibold` (count `text-ink-500`, selected `text-ink-300`).
- Tag chip: `inline-flex items-center gap-1 h-6 pl-2 pr-0.5 rounded-full bg-ink-100 text-xs font-semibold text-ink-700`; remove button `size-6 grid place-items-center rounded-full hover:bg-ink-200` (24px target).

### 10.6 Tabs

- Peer views (Home / Routines / Team / Settings; List / Calendar) are a **segmented control**: track `inline-flex p-0.5 rounded-[9px] bg-ink-900/5` (`role="tablist"`); segment `px-3.5 py-[5px] rounded-[7px] text-[13px] font-medium text-ink-600 aria-selected:bg-white aria-selected:text-ink-950 aria-selected:font-semibold aria-selected:shadow-[var(--shadow-segment)]`.
- Section tabs (Queue / Drafts / Approvals / Sent): `flex gap-6 border-b border-ink-200`; tab `h-10 -mb-px border-b-2 border-transparent text-sm font-medium text-ink-600 hover:text-ink-900 aria-selected:border-ink-900 aria-selected:text-ink-950 aria-selected:font-semibold`; counts are neutral badges. Tabs never use the accent.

### 10.7 Tables

Wrapper `overflow-hidden rounded-xl border border-ink-200 bg-white`. Header cells `h-9 px-4 text-left text-xs font-semibold text-ink-600 bg-ink-25 border-b border-ink-300` (sticky: add `.translucent-bar sticky top-0`). Body cells `px-4 py-3.5 text-table text-ink-900 border-b border-ink-200`; rows `hover:bg-ink-25 aria-selected:bg-brand-50`; numbers `text-right tabular-nums`; first column 16px checkbox. Below 640px rows collapse into list rows.

### 10.8 Toast

`fixed bottom-6 right-6 max-sm:inset-x-4 max-sm:bottom-4 z-50 flex items-start gap-3 max-w-[420px] rounded-xl bg-ink-900 px-3.5 py-3 text-sm font-medium text-white shadow-lg toast-enter`. Leading 18px icon `text-success-300 | text-warning-300 | text-danger-300 | text-info-300`; title 14/500 white; detail line `text-[13px] text-ink-300` (e.g. "Same tower. A fairer number. · LinkedIn"); action `font-semibold text-brand-300 hover:underline` ("Undo", 9.59:1); close `text-ink-300 hover:text-white`. `role="status"` (errors `role="alert"`). Success dismisses after 6s; the timer pauses on hover and focus; errors persist. Replaces the pink inline error box in `base.html`.

### 10.9 Modal and sheet

Overlay `fixed inset-0 bg-ink-950/35`. Dialog `w-full max-w-[560px] rounded-2xl bg-white shadow-xl` (sm 400, lg 720). Header `flex items-start justify-between px-6 pt-5 pb-4` with `text-h2` title and a 32px icon close; body `px-6 pb-5 text-sm text-ink-700`; footer `flex justify-end gap-2 px-6 py-4 border-t border-ink-200` (secondary then primary or danger). Below 640px: bottom sheet `fixed inset-x-0 bottom-0 rounded-t-2xl max-h-[92vh]` with a `mx-auto mt-2 h-[5px] w-9 rounded-full bg-ink-300` grabber. Focus is trapped; Escape closes; focus returns to the trigger.

### 10.10 Empty state, skeleton, progress, callouts, menus

- Empty state: `px-6 py-8 text-center`; 32px line icon `text-ink-400` stroke 1.5; title `mt-3 text-[15px] font-semibold text-ink-900`; body `mt-1 mx-auto max-w-[44ch] text-sm text-ink-600`; at most one action (secondary; primary only if it is the page's main action). No illustrations, no sparkles. Example: "Nothing in progress" / "Tell your team what you want and follow it here."
- Skeleton: `.skeleton` blocks at real sizes (text lines 10–12px tall, 6px gaps, thumbnails at their real radius) inside a `.skeleton-delay` container with `aria-busy="true"`.
- Progress: track `h-1 rounded-full bg-ink-200`, fill `h-1 rounded-full bg-brand-600` (4.69:1 against the track), label `text-[13px] font-semibold text-ink-900 tabular-nums` ("5 of 11 done").
- Neutral callout ("Nothing goes out without you"): `flex gap-3 rounded-xl bg-ink-50 ring-1 ring-inset ring-ink-200 p-4`; 16px lock `text-ink-700`; title `text-sm font-semibold text-ink-900`; body `text-[13px]/[18px] text-ink-600`. Warning/danger callouts use their 50 / 200 / 600 tones plus an icon.
- Owner box ("For the owner"): `rounded-md bg-ink-50 ring-1 ring-inset ring-ink-200 px-3 py-2 text-xs/[18px] text-ink-700`; label `font-semibold text-ink-900`; setting names in `font-mono`. Copy describes the step in plain words, with no vendor names ("Add the writing key to the web and worker services").
- Menu / popover: `rounded-xl bg-white p-1 shadow-lg ring-1 ring-ink-200`; item `flex h-[34px] items-center gap-2 rounded-lg px-2.5 text-sm text-ink-900 hover:bg-ink-50`; destructive item `text-danger-500`; separator `my-1 h-px bg-ink-200`.
- Tooltip: `rounded-md bg-ink-900 px-2 py-1 text-xs font-medium text-white`, 400ms delay, no arrow.

---

## 11. App shell

| Part | Treatment |
|---|---|
| Sidebar | `w-60` (collapsed `w-[60px]`), `bg-ink-100 border-r border-ink-200 px-3 py-3 flex flex-col gap-0.5`. Workspace switcher: 28px mark (client icon, or `bg-ink-900` with a white initial, `rounded-[7px]`), name 14/600. "New" = secondary button, full width. Nav items `.sidebar-nav-item` (32px tall, 44px on touch; icon 18px stroke 1.75 ink-500; label 14/500 ink-700; hover `bg-ink-900/5`; active = white pill + `--shadow-nav-active` + 600 ink-950 label + brand-700 icon + `aria-current="page"`). Section label `.sidebar-section-label` 12/600 ink-500 sentence case. Badges `.sidebar-badge` (neutral) / `.sidebar-badge.is-turn` (Approvals). Footer: 28px ink-200 avatar, name 13/600, role 12 ink-500. |
| Main | `flex-1 min-w-0 bg-ink-50 px-10 pt-8 pb-16 max-lg:px-6 max-sm:px-4`; the inset white sheet is removed: cards sit directly on the canvas. |
| Page header | `text-h1 text-ink-950` → status line `mt-1.5 text-sm text-ink-600` with `·` separators in ink-400 and underlined links → segmented tabs `mt-5` → content `mt-6`. |
| Phone top bar | 52px `.translucent-bar sticky top-0`: menu icon, workspace 16/600, spacer, Approvals badge. Drawer 280px over `bg-ink-950/35`. |
| Widths | Home, Publish, Team 1180px; Routines 960px; Set up 880px; thread column ≤ 720px; Home grid `grid-cols-[minmax(0,1fr)_372px] gap-6` at ≥ 1280px, one column below with Today first only when something waits. |
| Rhythm | 4px base: 4, 8, 12, 16, 20, 24, 32, 40, 64. Card padding 20 (16 phone); gap between cards 24; section gap 40; group label top margin 18; page padding 32/40 desktop, 24 tablet, 16 phone. |
| Breakpoints | phone < 640, tablet 640–1023 (sidebar becomes a drawer, 44px targets), desktop ≥ 1024, wide ≥ 1280. |

---

## 12. Conversation

| Element | Treatment |
|---|---|
| **You** (person bubble) | right-aligned, `max-w-[78%] rounded-[18px] rounded-br-md bg-ink-100 px-3.5 py-2.5 text-body-lg text-ink-900`; meta "You · 15:35" `text-xs font-medium text-ink-500 text-right` above. No longer a filled orange bubble. |
| **Account manager / specialist** | left, no bubble: 28px `bg-ink-900 text-white` avatar (11/600 initials), name `text-[13px] font-semibold text-ink-900` + "· 15:35" ink-500; body `text-body-lg text-ink-900`. Consecutive messages group under one avatar. Action cards (brief, draft, routine) nest below at `rounded-xl`. Full width on phones. Specialist avatars are neutral (`bg-ink-100 text-ink-700`); colour is never per agent. |
| Client | left, `bg-white ring-1 ring-ink-200 rounded-[18px] rounded-bl-md`, name + neutral "Client" tag. |
| Teammate | left, `bg-ink-50 ring-1 ring-ink-200`. |
| **Internal note** | `rounded-xl bg-ink-25 border border-dashed border-ink-400 px-3.5 py-2.5`; 14px lock + "Note for the team" `text-xs font-semibold text-ink-700`. "Not sent" is carried by the dashed shape, so warning keeps its one meaning. |
| System line | centred `text-xs text-ink-500` between ink-200 hairlines ("Brief confirmed by Ana · 15:36"). |
| Writing | three 4px ink-400 dots + "The team is writing" `text-xs text-ink-500` (static text under reduced motion). |
| Links in messages | underlined (10.2). |

### 12.1 Brief card

`rounded-xl bg-white ring-1 ring-inset ring-ink-200 px-4 py-3.5`. Eyebrow "Brief" `text-xs font-semibold text-ink-500`; title `text-[15px] font-semibold text-ink-950`; definition list `grid grid-cols-[96px_1fr] gap-x-3 gap-y-1 text-[13px]/[18px]` (labels ink-500, values ink-900) that **stacks below 640px** (`max-sm:grid-cols-1`, values get `mb-1.5`). Angles are radio cards (10.3). Actions: **Start** (primary sm, the only solid button in the thread) + "Change something" (ghost). After Start: the 2px info line runs along the bottom edge, then the card compacts to one row with a status pill and the stage track (14.2). Auto mode: "Starting in 10 s · Stop" with the draining info line.

### 12.2 Composer

Container `rounded-xl border border-ink-400 bg-white p-3 pb-2.5 focus-within:border-brand-600 focus-within:shadow-[0_0_0_1px_var(--focus-ring)]` (at rest it is never shown focused). Borderless textarea `text-body-lg placeholder:text-ink-500`, grows 1→8 lines. Toolbar: ghost "Photo and direction" (icon only on phones) · checkbox "Note for the team only" (its own row below 640px) · spacer · **Send** (primary sm; secondary while a brief waits; 44px tall on phones). Cmd/Ctrl+Enter sends. Sticky to the card bottom on the phone thread page.

### 12.3 Approve sequence (Today, Approvals, portal)

1. Click the tinted "Approve & schedule": width-locked 14px spinner (shown ≥ 300ms).
2. The button cross-fades (160ms) into an info pill with a calendar icon: "Scheduled · Mon 10:10". **Not** success green, so a Pine action and a green status are never side by side.
3. Hold 1.2s, then the row collapses (height via grid rows + opacity, 220ms in-out).
4. The "waiting for you" count and the sidebar badge step together (4px slide + fade, 160ms); `aria-live="polite"` announces "Scheduled for Monday 26 October, 10:10".
5. Two-line toast: "Scheduled for Mon 26 Oct, 10:10" / "Same tower. A fairer number. · LinkedIn" + Undo (6s, pauses on hover/focus).
Reduced motion: the swap and collapse are instant; the toast still appears.

---

## 13. Today card

Hero card (`rounded-2xl p-5`), 372px right column on desktop. Header "Today" `text-h2` + "Fri 23 Oct" `text-[13px] text-ink-500` right-aligned. Summary line (not a pill): "**2** waiting for you · **1** needs a look" `text-[13px] text-ink-600 tabular-nums`, counts ink-900 600.

| Group | Row |
|---|---|
| Waiting for you | 44×55 creative thumb · title 14/600 (2-line clamp) · meta 12 ink-500 with 14px platform glyphs (≥ 8px from any button) · tinted "Approve & schedule" sm + ghost "Review" sm. After approval the row shows the info "Scheduled" pill, then collapses. |
| Done since yesterday | 16px success-500 check + 13px ink-700 text + ink-500 time; repeats grouped ("3 drafts ready"); collapses after 3 ("Show 4 more"). |
| Needs a look | 16px danger-500 triangle + text + underlined link "Run it again". |
| Footer | "Next planned run: Fri 23 Oct, 10:30" `text-xs text-ink-500`. |

Group labels 12/600 ink-500, sentence case, 18px top margin. On phones Today comes first only when something is waiting; otherwise it collapses to one line ("Nothing waiting · next run Fri 10:30").

---

## 14. The live team view (24/7 agents and their tasks)

One system with the rest: the same five status tones, the same shapes, the same type. Built in `templates/studio/team.html` and, compactly, as the "Right now" card on Home (`templates/studio/partials/live_strip.html`).

### 14.1 Live state: dot + word

| State | Shape (CSS class) | Colour | Word | Motion |
|---|---|---|---|---|
| Working | 8px filled circle (`.live-dot--working`) | info-500 `#035A7B` (7.63:1) | Working | 2s pulse ring (`--animate-live-pulse`); static under reduced motion |
| Idle | 8px ring, 1.5px (`.live-dot--idle`) | ink-400 `#83888F` (3.57:1) | Idle | none |
| Needs you | 9px diamond (`.live-dot--needs-you`) | warning-500 `#9B5A00` | Needs you | none |
| Stopped | 9px rounded square (`.live-dot--stopped`) | danger-500 `#991618` | Stopped | none |

Markup: `<span class="live-state"><i class="live-dot live-dot--working" aria-hidden="true"></i>Working</span>`. The word is always present, so shape and colour are redundant cues (colour-blind safe, forced-colours safe). Summary line under the page title: "3 working · 1 needs you · 1 stopped · 8 idle", inside `aria-live="polite"`.

### 14.2 Stage track (one job's progress)

`<ol class="stage-track" aria-label="Step 3 of 6: Copy, working">` with `<li class="stage" data-state="…"><span class="stage-node">…</span>Copy</li>`.

| Node state | Look | Contrast |
|---|---|---|
| done | 16px success-500 disc + white 10px check | disc 3.38:1 on white; check 3.38:1 on disc |
| working | 16px ring 2px info-500 + 6px info-500 centre that pulses; label ink-900 600; `aria-current="step"` | 7.63:1 |
| needs you | 16px ring 2px warning-500; label ink-900 600 + the word "Your answer" | 5.45:1 |
| waiting | 16px ring 1.5px ink-400 + label ink-600 | 3.57:1 |
| failed | 16px danger-500 disc + white x | 8.46:1 |

Connectors are 2px: success-500 between reached nodes, ink-200 ahead (decorative; nodes carry the state). Labels 12/16 500 ink-600, never wrap (≤ 6 stages; on phones 11px allowed only if the label still fits, otherwise show the current stage name only). Standard stages for a post: Brief → Angles → Copy → Design → Check → For you. Routines show their own (Read results → Your answer → Four briefs).

### 14.3 Delivery receipt (post status, grafted from Harbour)

`<ol class="receipt">` vertical list, 16px nodes joined by a 1px ink-200 line: done = success-500 disc + check; current = 2px info-500 ring; pending = 1.5px ink-400 ring **plus the word "Pending"** in the time slot (fixes Harbour's 1.62:1 node); failed = danger disc + x. Text 13/18 ink-800, times ink-500 tabular. Example: "Approved by Ana · Fri 10:10" → "Scheduled for LinkedIn · Mon 26 Oct, 10:10" → "Published · View post". Used on the brief page, Today "Done", the Team view ("Latest post") and the client portal's Published view.

### 14.4 Hour-bar chart (last 24 hours)

Form: one magnitude series over time → bars, one hue (dataviz rule: colour comes last; status colours stay reserved).
- Card header "Last 24 hours" + caption "Tasks finished"; three hero numbers above (28/700 ink-950 tabular: tasks done, stopped, posts ready).
- `.hour-chart`: 24 bars, 2px gaps, 96px tall, 4px rounded tops anchored to an ink-300 baseline; bars ink-400 (3.57:1), **current hour ink-900**, stopped tasks stacked on top in danger-500 with a 2px surface gap. No gridlines. Never Pine (the accent is not a data colour).
- Axis: `.chart-axis` 12/500 ink-500 tabular, every 6 hours + "Now".
- Legend always present (three series roles): Done · Stopped · This hour, with 10px swatches; text stays in ink.
- Hover/focus: bar darkens to ink-600 and shows `.chart-tip` ("10:00–11:00 · 6 done · 0 stopped").
- Accessibility: the chart is `role="img"` with a one-sentence `aria-label` summary ("Busiest at 10:00 with 6. One task stopped at 14:00.") plus a "Show as table" disclosure with the 24 rows.

### 14.5 Next 24 hours timeline

Desktop (`.timeline`, 150px tall): a 1px ink-300 axis from Now to +24h; a 2px ink-900 "Now" line; ticks every 6 hours at the bottom (12px ink-500 tabular); quiet hours as a hatched band (`ink-100 / ink-50` at 135°) with its label inside ("Quiet hours 22:00–07:00", ink-600).

| Event | Marker | Caption |
|---|---|---|
| Scheduled post | 16px info-500 disc + white calendar glyph | title 12/600 ink-900 (≤ 168px, ellipsis) + platform glyph + time |
| Routine run | 12px ink-700 diamond | name + "Routine · 09:00" |
| Approval due | 16px ring 2px warning-500 + clock | "Approve by 18:00" + count |
| Run that stopped | 9px danger-500 square | name + "Stopped" |

Collision rules: captions alternate below / above the axis (`.timeline-event.is-up`); events closer than 64px merge into an ink-900 "+3" cluster pill that opens a popover list. Every event is a link to its detail. Legend under the timeline. Below 768px the timeline renders as a plain list (`role="list"`) in time order with the same markers, with "Quiet hours 22:00–07:00" as a divider row. The header caption repeats the promise: "Nothing goes out without your approval".

### 14.6 Layout

- **Team tab** (`studio/team.html`): H1 "Your team" + live summary line; row 1 `grid-cols-[minmax(0,1fr)_400px]`: **Working now** (one row per running job: title 14/600, start time + elapsed, platform glyphs + "Copywriter is writing three versions", stage track; a needs-you job gets a tinted "Answer") and **Last 24 hours** (numbers, hour-bar chart, latest-post receipt); row 2 full width **Next 24 hours**; row 3 departments as cards (3-up) listing each agent: neutral 28px avatar, name 14/600, last activity 12 ink-500, live state right-aligned. Department colour avatars are retired (`apps/studio/team.py` colours → ink-700).
- **Home "Right now" card** (under Today): "3 working · 1 stopped · 9 idle" + the current job's stage track + "Open Team".
- Refresh: HTMX poll every 15s on the Team tab only; changes cross-fade 160ms; counts announced politely; no motion beyond the working pulse.

---

## 15. Client portal

Same tokens; calmer still. No sidebar. Header `h-14 bg-white border-b border-ink-200` with the agency logo (or ink-900 mark) and the client name 15/600; section tabs are the underline tabs (ink-900 underline). Harbour's dark header is not used: the chrome stays pale so the creatives are the loudest thing. Content on the ink-50 canvas, `max-w-[960px]`; body copy 16/26 for approvers who read every word. Each post: creative on white with the neutral hairline, caption, status pill, delivery receipt; one solid **Approve** (primary) + secondary **Ask for changes**; the approve sequence (12.3) without the sidebar badge. Magic-link email uses the literal hex palette (emails never load the stylesheet, so `tools/recolor.py` writes the new hex there instead of `var(--…)`). A white-label agency can swap Layer 1 brand values; the contrast guard (section 22) runs on every swap.

## 16. Login and auth

ink-50 page (no radial gradients); centred 400px card `rounded-2xl bg-white shadow-lg p-10` (full-bleed below 480px); wordmark 16/600 ink-950; "Continue with Google" secondary button with the official multicolour G; email field and full-width primary; links underlined; errors in the danger alert style.

## 17. Marketing site

Same tokens and system font, with a larger scale, twice the whitespace and real imagery.
- **Hero (white):** headline 64/68 700 ink-950 (phone 40/44): "Your social media team. Nothing goes out without you." Subhead 19/28 ink-600 (max 56ch): "Tell your team what you want to post. They plan, write and design it. You approve every post, from your desk or from Telegram." One lg primary "Get started" + text link "See how approvals work". Below: the real Home screen in a 16px-radius frame with `--shadow-xl`, then a strip of real client creatives (with permission). The creatives are the only colour.
- **Sections** alternate white and ink-50, 120px padding (72 phone), 1120px max width: (1) three-up features with 24px ink-900 line icons (no coloured tiles); (2) "How approval works": Today row → Review → Approve → toast as real UI crops joined by 1px ink-300 connectors; (3) **one dark band** (ink-950, the only one) "Approvals that hold": the delivery receipt at large scale beside one natural-colour architectural photograph (balcony or lobby, never tinted), text ink-50 (17.65:1) and ink-300 (12.47:1), CTA `bg-brand-200 text-brand-950` (12.61:1); (4) "Your team, around the clock": the Team view's stage tracks and hour chart as a live-looking crop; (5) "On your phone": the Telegram flow in a phone frame; (6) "Built for agencies in India": IST times, rupee budgets (the system font has ₹), real Neopolis creatives; (7) pricing on white cards, recommended plan with a 1px brand-700 edge, tabular prices; (8) FAQ disclosures; footer ink-50 with 13px ink-600 links.
- **Differs from the app:** display sizes, double spacing, imagery-led, one dark band, no sidebar or translucency; each band ends in at most one primary.
- **Implementation:** `static/css/marketing.css` carries the same values as literal `--mk-*` variables; the Instrument Serif and Inter `@font-face` rules and their preloads are gone, so no font file sits on the critical path.

## 18. Iconography

One stroke set (the inline Feather/Lucide-style SVGs already in the templates): 24px grid, 1.75px stroke (1.5px at 32px, 2.5px at 12px in pills), round caps and joins, `currentColor`. Sizes: 12 in pills, 16 in buttons and rows, 18 in nav, 20 standalone, 32 in empty states. Default colour ink-500; coloured only for status. Fixed status shapes: check (done), clock (waiting for a person), return arrow (changes requested), triangle (needs a look, partly published), x-octagon (failed, rejected), calendar (scheduled), spinner (working, publishing), three dots (queued), dash (draft), pause (paused, on hold), lock (internal note, the approval promise). Calendar-grid dots use the same shapes (filled circle, ring, diamond, square). Icon-only buttons always carry `aria-label`; decorative icons `aria-hidden="true"`.

## 19. Imagery and creatives

- Creatives always sit on white or ink-50 with `shadow-[inset_0_0_0_1px_rgba(14,17,20,.06)]`; never a brand frame, tint or overlay. 4:5 tiles at radius 14, thumbnails 7/10.
- Empty or failed creative tiles show the status icon and one line ("Stopped before the picture", "Designing the picture") on ink-50, not a bare image glyph.
- Platform glyphs: official colours, 14–20px, never recoloured, never inside a pill, at least 8px from any tinted button.
- The app has no stock photos, illustrations, 3D shapes or gradients. Marketing allows real product UI, real client creatives (with permission) and at most one natural architectural photograph.

## 20. Copy rules

Sentence case everywhere (buttons, labels, statuses, tabs). No model or vendor names in visible copy; describe the step ("Add the writing key to the web and worker services") and show exact setting names in mono only where the owner must type them. Dates and times in the owner's time zone, "Mon 26 Oct, 10:10". Status words come from the fixed list in 10.5. Numbers are tabular.

## 21. Dark mode later (out of scope now)

Light mode is the product. The tokens are ready: utilities read Layer 1 variables inline (`@theme inline`), so a later `[data-theme="dark"]` block redefines `--ink-*`, `--brand-*`, status scales and Layer 2 surfaces/text and every `bg-ink-*`, `text-brand-*` class follows. Two prerequisites: codemod `bg-white` (315 uses) → `bg-surface` and `text-white` on fills → an on-primary token; and choose dark steps (links brand-300, primary fill brand-500 with ink-950 text) and re-check every pair in section 23 against the dark surfaces. The toast and tooltip are already dark and verified.

## 22. White-label guard

`--brand-*` is Layer 1, so an agency can bring its own accent. On save, a guard (WCAG relative luminance and OKLab ΔE, as in section 23) must: darken the chosen 700 step until white on it is ≥ 4.5:1; check the 600 step is ≥ 3:1 on white, ink-50 and ink-100 (focus ring); warn when the accent is within OKLab ΔE 10 of LinkedIn `#0A66C2` or Facebook `#1877F2`, or within 10 of success-600 `#317F38`; never let a brand colour replace a status colour.

---

## 23. Verified contrast and colour-vision tables

Computed in the design round (WCAG 2.x relative luminance; OKLab ΔE ×100; Machado 2009 colour-vision simulation at full severity) from the exact hexes in Layer 1 of `styles.css`. Output pasted verbatim. "Sticky bar over navy" is the translucent bar (ink-50 at 92%) blended over a Neopolis navy creative `#1E2533`, the worst case a scrolling bar can sit on.

#### Text (body and small text need 4.5:1; large 3:1)

| Pair | Foreground | Background | Ratio | Needs | Result |
|---|---|---|---:|---:|---|
| title ink-950 on surface white | `#0E1114` | `#FFFFFF` | 18.94:1 | 4.5:1 | PASS |
| title ink-950 on ink-25 sheet/row hover | `#0E1114` | `#FBFCFD` | 18.44:1 | 4.5:1 | PASS |
| title ink-950 on ink-50 canvas/sunken | `#0E1114` | `#F6F7F8` | 17.65:1 | 4.5:1 | PASS |
| title ink-950 on ink-100 sidebar/bubble | `#0E1114` | `#EDEFF2` | 16.44:1 | 4.5:1 | PASS |
| title ink-950 on brand-50 selected row | `#0E1114` | `#EFFAF5` | 17.73:1 | 4.5:1 | PASS |
| title ink-950 on sticky bar over navy (#E5E6E8) | `#0E1114` | `#E5E6E8` | 15.16:1 | 4.5:1 | PASS |
| text ink-900 on surface white | `#1C1F24` | `#FFFFFF` | 16.52:1 | 4.5:1 | PASS |
| text ink-900 on ink-25 sheet/row hover | `#1C1F24` | `#FBFCFD` | 16.09:1 | 4.5:1 | PASS |
| text ink-900 on ink-50 canvas/sunken | `#1C1F24` | `#F6F7F8` | 15.41:1 | 4.5:1 | PASS |
| text ink-900 on ink-100 sidebar/bubble | `#1C1F24` | `#EDEFF2` | 14.34:1 | 4.5:1 | PASS |
| text ink-900 on brand-50 selected row | `#1C1F24` | `#EFFAF5` | 15.47:1 | 4.5:1 | PASS |
| text ink-900 on sticky bar over navy (#E5E6E8) | `#1C1F24` | `#E5E6E8` | 13.23:1 | 4.5:1 | PASS |
| body-2 ink-700 on surface white | `#3E434A` | `#FFFFFF` | 9.97:1 | 4.5:1 | PASS |
| body-2 ink-700 on ink-25 sheet/row hover | `#3E434A` | `#FBFCFD` | 9.71:1 | 4.5:1 | PASS |
| body-2 ink-700 on ink-50 canvas/sunken | `#3E434A` | `#F6F7F8` | 9.29:1 | 4.5:1 | PASS |
| body-2 ink-700 on ink-100 sidebar/bubble | `#3E434A` | `#EDEFF2` | 8.65:1 | 4.5:1 | PASS |
| body-2 ink-700 on brand-50 selected row | `#3E434A` | `#EFFAF5` | 9.33:1 | 4.5:1 | PASS |
| body-2 ink-700 on sticky bar over navy (#E5E6E8) | `#3E434A` | `#E5E6E8` | 7.98:1 | 4.5:1 | PASS |
| secondary ink-600 on surface white | `#52575F` | `#FFFFFF` | 7.27:1 | 4.5:1 | PASS |
| secondary ink-600 on ink-25 sheet/row hover | `#52575F` | `#FBFCFD` | 7.08:1 | 4.5:1 | PASS |
| secondary ink-600 on ink-50 canvas/sunken | `#52575F` | `#F6F7F8` | 6.78:1 | 4.5:1 | PASS |
| secondary ink-600 on ink-100 sidebar/bubble | `#52575F` | `#EDEFF2` | 6.31:1 | 4.5:1 | PASS |
| secondary ink-600 on brand-50 selected row | `#52575F` | `#EFFAF5` | 6.81:1 | 4.5:1 | PASS |
| secondary ink-600 on sticky bar over navy (#E5E6E8) | `#52575F` | `#E5E6E8` | 5.82:1 | 4.5:1 | PASS |
| tertiary/placeholder ink-500 on surface white | `#656B73` | `#FFFFFF` | 5.38:1 | 4.5:1 | PASS |
| tertiary/placeholder ink-500 on ink-25 sheet/row hover | `#656B73` | `#FBFCFD` | 5.24:1 | 4.5:1 | PASS |
| tertiary/placeholder ink-500 on ink-50 canvas/sunken | `#656B73` | `#F6F7F8` | 5.01:1 | 4.5:1 | PASS |
| tertiary/placeholder ink-500 on ink-100 sidebar/bubble | `#656B73` | `#EDEFF2` | 4.67:1 | 4.5:1 | PASS |
| tertiary/placeholder ink-500 on brand-50 selected row | `#656B73` | `#EFFAF5` | 5.04:1 | 4.5:1 | PASS |
| link brand-700 on surface white | `#115641` | `#FFFFFF` | 8.64:1 | 4.5:1 | PASS |
| link brand-700 on ink-25 sheet/row hover | `#115641` | `#FBFCFD` | 8.41:1 | 4.5:1 | PASS |
| link brand-700 on ink-50 canvas/sunken | `#115641` | `#F6F7F8` | 8.05:1 | 4.5:1 | PASS |
| link brand-700 on ink-100 sidebar/bubble | `#115641` | `#EDEFF2` | 7.50:1 | 4.5:1 | PASS |
| link brand-700 on brand-50 selected row | `#115641` | `#EFFAF5` | 8.09:1 | 4.5:1 | PASS |
| link brand-700 on sticky bar over navy (#E5E6E8) | `#115641` | `#E5E6E8` | 6.92:1 | 4.5:1 | PASS |
| link hover brand-800 on surface white | `#0D4534` | `#FFFFFF` | 10.95:1 | 4.5:1 | PASS |
| link hover brand-800 on ink-25 sheet/row hover | `#0D4534` | `#FBFCFD` | 10.66:1 | 4.5:1 | PASS |
| link hover brand-800 on ink-50 canvas/sunken | `#0D4534` | `#F6F7F8` | 10.21:1 | 4.5:1 | PASS |
| link hover brand-800 on ink-100 sidebar/bubble | `#0D4534` | `#EDEFF2` | 9.50:1 | 4.5:1 | PASS |
| link hover brand-800 on brand-50 selected row | `#0D4534` | `#EFFAF5` | 10.25:1 | 4.5:1 | PASS |
| link hover brand-800 on sticky bar over navy (#E5E6E8) | `#0D4534` | `#E5E6E8` | 8.77:1 | 4.5:1 | PASS |
| tertiary ink-500 on sticky bar over navy (NOT ALLOWED; shown to justify the rule) | `#656B73` | `#E5E6E8` | 4.31:1 | 4.5:1 | FAIL |
| text ink-900 on sticky bar over orange creative | `#1C1F24` | `#F6ECE6` | 14.21:1 | 4.5:1 | PASS |
| secondary ink-600 on sticky bar over orange creative | `#52575F` | `#F6ECE6` | 6.25:1 | 4.5:1 | PASS |
| white on primary brand-700 | `#FFFFFF` | `#115641` | 8.64:1 | 4.5:1 | PASS |
| white on primary hover brand-800 | `#FFFFFF` | `#0D4534` | 10.95:1 | 4.5:1 | PASS |
| white on primary pressed brand-900 | `#FFFFFF` | `#0B3629` | 13.34:1 | 4.5:1 | PASS |
| white on destructive danger-500 | `#FFFFFF` | `#991618` | 8.46:1 | 4.5:1 | PASS |
| white on destructive hover danger-600 | `#FFFFFF` | `#7C1213` | 10.75:1 | 4.5:1 | PASS |
| white on toast/selected chip ink-900 | `#FFFFFF` | `#1C1F24` | 16.52:1 | 4.5:1 | PASS |
| white on manager avatar ink-900 | `#FFFFFF` | `#1C1F24` | 16.52:1 | 4.5:1 | PASS |
| tinted button brand-700 on brand-100 | `#115641` | `#DDF3EA` | 7.44:1 | 4.5:1 | PASS |
| tinted button hover brand-800 on brand-200 | `#0D4534` | `#BFE7D6` | 8.14:1 | 4.5:1 | PASS |
| approvals badge white on brand-700 | `#FFFFFF` | `#115641` | 8.64:1 | 4.5:1 | PASS |
| count badge ink-700 on ink-200 | `#3E434A` | `#E1E4E8` | 7.82:1 | 4.5:1 | PASS |
| neutral chip ink-700 on ink-100 | `#3E434A` | `#EDEFF2` | 8.65:1 | 4.5:1 | PASS |
| disabled label ink-500 on ink-100 | `#656B73` | `#EDEFF2` | 4.67:1 | 4.5:1 | PASS |
| success chip text success-600 on success-50 | `#317F38` | `#EDFCED` | 4.68:1 | 4.5:1 | PASS |
| success text success-600 on white | `#317F38` | `#FFFFFF` | 4.97:1 | 4.5:1 | PASS |
| success text success-600 on canvas ink-50 | `#317F38` | `#F6F7F8` | 4.64:1 | 4.5:1 | PASS |
| success alert body success-700 on success-50 | `#28682D` | `#EDFCED` | 6.35:1 | 4.5:1 | PASS |
| success icon-as-text success-500 on white | `#429E4A` | `#FFFFFF` | 3.38:1 | 3.0:1 | PASS |
| warning chip text warning-600 on warning-50 | `#7F4700` | `#FFF7EB` | 7.05:1 | 4.5:1 | PASS |
| warning text warning-600 on white | `#7F4700` | `#FFFFFF` | 7.49:1 | 4.5:1 | PASS |
| warning text warning-600 on canvas ink-50 | `#7F4700` | `#F6F7F8` | 6.98:1 | 4.5:1 | PASS |
| warning alert body warning-700 on warning-50 | `#683904` | `#FFF7EB` | 9.08:1 | 4.5:1 | PASS |
| warning icon-as-text warning-500 on white | `#9B5A00` | `#FFFFFF` | 5.45:1 | 4.5:1 | PASS |
| danger chip text danger-600 on danger-50 | `#7C1213` | `#FFF3F1` | 9.90:1 | 4.5:1 | PASS |
| danger text danger-600 on white | `#7C1213` | `#FFFFFF` | 10.75:1 | 4.5:1 | PASS |
| danger text danger-600 on canvas ink-50 | `#7C1213` | `#F6F7F8` | 10.03:1 | 4.5:1 | PASS |
| danger alert body danger-700 on danger-50 | `#6A0E0E` | `#FFF3F1` | 11.50:1 | 4.5:1 | PASS |
| danger icon-as-text danger-500 on white | `#991618` | `#FFFFFF` | 8.46:1 | 4.5:1 | PASS |
| info chip text info-600 on info-50 | `#044E6B` | `#EFF8FD` | 8.46:1 | 4.5:1 | PASS |
| info text info-600 on white | `#044E6B` | `#FFFFFF` | 9.10:1 | 4.5:1 | PASS |
| info text info-600 on canvas ink-50 | `#044E6B` | `#F6F7F8` | 8.49:1 | 4.5:1 | PASS |
| info alert body info-700 on info-50 | `#064058` | `#EFF8FD` | 10.37:1 | 4.5:1 | PASS |
| info icon-as-text info-500 on white | `#035A7B` | `#FFFFFF` | 7.63:1 | 4.5:1 | PASS |
| ink-900 body on success-50 callout | `#1C1F24` | `#EDFCED` | 15.54:1 | 4.5:1 | PASS |
| ink-900 body on internal note ink-25 | `#1C1F24` | `#FBFCFD` | 16.09:1 | 4.5:1 | PASS |
| note label ink-700 on ink-25 | `#3E434A` | `#FBFCFD` | 9.71:1 | 4.5:1 | PASS |
| toast detail ink-300 on ink-900 | `#CED2D7` | `#1C1F24` | 10.88:1 | 4.5:1 | PASS |
| toast action brand-300 on ink-900 | `#94D2BA` | `#1C1F24` | 9.59:1 | 4.5:1 | PASS |
| tooltip white on ink-900 | `#FFFFFF` | `#1C1F24` | 16.52:1 | 4.5:1 | PASS |
| marketing dark band ink-50 on ink-950 | `#F6F7F8` | `#0E1114` | 17.65:1 | 4.5:1 | PASS |
| marketing dark band ink-300 on ink-950 | `#CED2D7` | `#0E1114` | 12.47:1 | 4.5:1 | PASS |
| marketing on-dark CTA brand-950 on brand-200 | `#062118` | `#BFE7D6` | 12.61:1 | 4.5:1 | PASS |
| portal header text ink-900 on white | `#1C1F24` | `#FFFFFF` | 16.52:1 | 4.5:1 | PASS |
| chart axis label ink-500 on white | `#656B73` | `#FFFFFF` | 5.38:1 | 4.5:1 | PASS |
| timeline now label ink-900 on white | `#1C1F24` | `#FFFFFF` | 16.52:1 | 4.5:1 | PASS |
| large title 28px ink-950 on canvas (needs 3:1) | `#0E1114` | `#F6F7F8` | 17.65:1 | 3.0:1 | PASS |

#### Non-text: focus, control boundaries, icons, chart and track marks (need 3:1)

| Pair | Foreground | Background | Ratio | Needs | Result |
|---|---|---|---:|---:|---|
| focus ring brand-600 vs white | `#1E7057` | `#FFFFFF` | 5.98:1 | 3.0:1 | PASS |
| focus ring brand-600 vs ink-25 | `#1E7057` | `#FBFCFD` | 5.82:1 | 3.0:1 | PASS |
| focus ring brand-600 vs ink-50 canvas | `#1E7057` | `#F6F7F8` | 5.58:1 | 3.0:1 | PASS |
| focus ring brand-600 vs ink-100 sidebar | `#1E7057` | `#EDEFF2` | 5.19:1 | 3.0:1 | PASS |
| focus ring brand-600 vs brand-50 | `#1E7057` | `#EFFAF5` | 5.60:1 | 3.0:1 | PASS |
| focus ring brand-600 vs brand-100 tinted btn | `#1E7057` | `#DDF3EA` | 5.15:1 | 3.0:1 | PASS |
| focus ring brand-600 vs sticky over navy | `#1E7057` | `#E5E6E8` | 4.79:1 | 3.0:1 | PASS |
| control border ink-400 vs white | `#83888F` | `#FFFFFF` | 3.57:1 | 3.0:1 | PASS |
| control border ink-400 vs ink-25 | `#83888F` | `#FBFCFD` | 3.47:1 | 3.0:1 | PASS |
| control border ink-400 vs ink-50 canvas | `#83888F` | `#F6F7F8` | 3.33:1 | 3.0:1 | PASS |
| control border ink-400 vs ink-100 sidebar | `#83888F` | `#EDEFF2` | 3.10:1 | 3.0:1 | PASS |
| white focus gap vs primary brand-700 (ring offset) | `#FFFFFF` | `#115641` | 8.64:1 | 3.0:1 | PASS |
| checkbox/toggle on brand-700 vs white | `#115641` | `#FFFFFF` | 8.64:1 | 3.0:1 | PASS |
| toggle off track ink-400 vs white | `#83888F` | `#FFFFFF` | 3.57:1 | 3.0:1 | PASS |
| toggle knob white vs off track ink-400 | `#FFFFFF` | `#83888F` | 3.57:1 | 3.0:1 | PASS |
| toggle knob white vs on track brand-700 | `#FFFFFF` | `#115641` | 8.64:1 | 3.0:1 | PASS |
| composer focus border brand-600 vs white | `#1E7057` | `#FFFFFF` | 5.98:1 | 3.0:1 | PASS |
| success icon success-500 vs white | `#429E4A` | `#FFFFFF` | 3.38:1 | 3.0:1 | PASS |
| success icon success-500 vs success-50 chip | `#429E4A` | `#EDFCED` | 3.17:1 | 3.0:1 | PASS |
| warning icon warning-500 vs white | `#9B5A00` | `#FFFFFF` | 5.45:1 | 3.0:1 | PASS |
| warning icon warning-500 vs warning-50 chip | `#9B5A00` | `#FFF7EB` | 5.12:1 | 3.0:1 | PASS |
| danger icon danger-500 vs white | `#991618` | `#FFFFFF` | 8.46:1 | 3.0:1 | PASS |
| danger icon danger-500 vs danger-50 chip | `#991618` | `#FFF3F1` | 7.79:1 | 3.0:1 | PASS |
| info icon info-500 vs white | `#035A7B` | `#FFFFFF` | 7.63:1 | 3.0:1 | PASS |
| info icon info-500 vs info-50 chip | `#035A7B` | `#EFF8FD` | 7.09:1 | 3.0:1 | PASS |
| neutral icon ink-500 vs ink-100 chip | `#656B73` | `#EDEFF2` | 4.67:1 | 3.0:1 | PASS |
| neutral icon ink-500 vs white | `#656B73` | `#FFFFFF` | 5.38:1 | 3.0:1 | PASS |
| toast icon success-300 vs ink-900 | `#95E097` | `#1C1F24` | 10.53:1 | 3.0:1 | PASS |
| toast icon warning-300 vs ink-900 | `#FFCA82` | `#1C1F24` | 11.03:1 | 3.0:1 | PASS |
| toast icon danger-300 vs ink-900 | `#FEA69C` | `#1C1F24` | 8.77:1 | 3.0:1 | PASS |
| toast icon info-300 vs ink-900 | `#95CDEB` | `#1C1F24` | 9.61:1 | 3.0:1 | PASS |
| active nav icon brand-700 vs white pill | `#115641` | `#FFFFFF` | 8.64:1 | 3.0:1 | PASS |
| progress fill brand-600 vs track ink-200 | `#1E7057` | `#E1E4E8` | 4.69:1 | 3.0:1 | PASS |
| tab underline ink-900 vs white | `#1C1F24` | `#FFFFFF` | 16.52:1 | 3.0:1 | PASS |
| selected filter chip ink-900 vs canvas | `#1C1F24` | `#F6F7F8` | 15.41:1 | 3.0:1 | PASS |
| stage node done: success-500 disc vs white | `#429E4A` | `#FFFFFF` | 3.38:1 | 3.0:1 | PASS |
| stage node done: white check vs success-500 disc | `#FFFFFF` | `#429E4A` | 3.38:1 | 3.0:1 | PASS |
| stage node working: info-500 ring vs white | `#035A7B` | `#FFFFFF` | 7.63:1 | 3.0:1 | PASS |
| stage node waiting / receipt pending: ink-400 ring vs white | `#83888F` | `#FFFFFF` | 3.57:1 | 3.0:1 | PASS |
| stage node needs you: warning-500 ring vs white | `#9B5A00` | `#FFFFFF` | 5.45:1 | 3.0:1 | PASS |
| stage node failed: white x vs danger-500 disc | `#FFFFFF` | `#991618` | 8.46:1 | 3.0:1 | PASS |
| live dot working info-500 vs white | `#035A7B` | `#FFFFFF` | 7.63:1 | 3.0:1 | PASS |
| live dot idle ring ink-400 vs white | `#83888F` | `#FFFFFF` | 3.57:1 | 3.0:1 | PASS |
| live dot attention warning-500 vs white | `#9B5A00` | `#FFFFFF` | 5.45:1 | 3.0:1 | PASS |
| hour bar ink-400 vs white | `#83888F` | `#FFFFFF` | 3.57:1 | 3.0:1 | PASS |
| hour bar current ink-900 vs white | `#1C1F24` | `#FFFFFF` | 16.52:1 | 3.0:1 | PASS |
| hour bar failed segment danger-500 vs white | `#991618` | `#FFFFFF` | 8.46:1 | 3.0:1 | PASS |
| timeline scheduled marker info-500 vs white | `#035A7B` | `#FFFFFF` | 7.63:1 | 3.0:1 | PASS |
| timeline routine marker ink-700 vs white | `#3E434A` | `#FFFFFF` | 9.97:1 | 3.0:1 | PASS |
| timeline approval-due marker warning-500 vs white | `#9B5A00` | `#FFFFFF` | 5.45:1 | 3.0:1 | PASS |
| now line ink-900 vs white | `#1C1F24` | `#FFFFFF` | 16.52:1 | 3.0:1 | PASS |
| error field border danger-500 vs white | `#991618` | `#FFFFFF` | 8.46:1 | 3.0:1 | PASS |
| LinkedIn glyph vs white (content) | `#0A66C2` | `#FFFFFF` | 5.69:1 | 3.0:1 | PASS |
| Facebook glyph vs white (content) | `#1877F2` | `#FFFFFF` | 4.23:1 | 3.0:1 | PASS |

#### Decorative (exempt; listed so nobody mistakes them for state indicators)

| Pair | Foreground | Background | Ratio | Why exempt |
|---|---|---|---:|---|
| hairline ink-200 vs white | `#E1E4E8` | `#FFFFFF` | 1.28:1 | decorative |
| secondary-button border ink-300 vs white (label carries contrast) | `#CED2D7` | `#FFFFFF` | 1.52:1 | decorative |
| card white vs canvas ink-50 (hairline + shadow separate it) | `#FFFFFF` | `#F6F7F8` | 1.07:1 | decorative |
| active nav pill white vs sidebar ink-100 (state also: 600 weight, brand-700 icon 9.0:1, aria-current) | `#FFFFFF` | `#EDEFF2` | 1.15:1 | decorative |
| tinted button fill brand-100 vs white (text label carries it) | `#DDF3EA` | `#FFFFFF` | 1.16:1 | decorative |
| stage connector ink-200 vs white (nodes carry state) | `#E1E4E8` | `#FFFFFF` | 1.28:1 | decorative |

#### Status icons / dots (OKLab dE x100; 8+ clearly apart, below 8 the icon shape and word carry it)

| Pair | Normal | Protan | Deutan | Tritan | Luminance ratio |
|---|---:|---:|---:|---:|---:|
| info-500 vs neutral ink-500 | 11.4 | 7.9 | 11.1 | 9.6 | 1.42 |
| warning-500 vs danger-500 | 13.5 | 14.6 | 9.0 | 9.5 | 1.55 |
| success-500 vs warning-500 | 20.0 | 16.4 | 9.3 | 23.7 | 1.61 |
| warning-500 vs neutral ink-500 | 13.5 | 12.1 | 12.7 | 14.0 | 1.01 |
| danger-500 vs neutral ink-500 | 19.5 | 19.0 | 12.3 | 21.0 | 1.57 |
| success-500 vs neutral ink-500 | 18.4 | 16.9 | 13.8 | 13.0 | 1.59 |
| warning-500 vs info-500 | 22.7 | 16.3 | 21.6 | 21.9 | 1.40 |
| danger-500 vs info-500 | 24.8 | 16.3 | 16.4 | 26.5 | 1.11 |
| success-500 vs danger-500 | 32.6 | 30.6 | 17.3 | 32.2 | 2.51 |
| success-500 vs info-500 | 25.1 | 24.7 | 24.8 | 17.3 | 2.26 |

#### Status chip text

| Pair | Normal | Protan | Deutan | Tritan | Luminance ratio |
|---|---:|---:|---:|---:|---:|
| info-600 vs neutral ink-700 | 7.0 | 5.8 | 5.7 | 6.5 | 1.10 |
| success-600 vs warning-600 | 17.4 | 13.8 | 7.4 | 20.7 | 1.51 |
| warning-600 vs danger-600 | 11.2 | 12.1 | 7.7 | 7.9 | 1.44 |
| danger-600 vs neutral ink-700 | 14.9 | 9.9 | 8.8 | 17.4 | 1.08 |
| warning-600 vs neutral ink-700 | 14.0 | 10.5 | 13.9 | 14.8 | 1.33 |
| warning-600 vs info-600 | 19.3 | 14.1 | 17.9 | 18.9 | 1.22 |
| danger-600 vs info-600 | 21.6 | 15.6 | 14.1 | 23.1 | 1.18 |
| success-600 vs danger-600 | 27.7 | 25.6 | 14.2 | 27.6 | 2.16 |
| success-600 vs neutral ink-700 | 20.3 | 20.0 | 17.4 | 16.7 | 2.00 |
| success-600 vs info-600 | 20.0 | 19.6 | 19.6 | 12.3 | 1.83 |

#### Accent vs the colours it must never be confused with

| Pair | Normal | Protan | Deutan | Tritan | OKLCH hue gap |
|---|---:|---:|---:|---:|---:|
| pine brand-700 vs LinkedIn #0A66C2 | 20.8 | 21.0 | 20.3 | 13.4 | 87° |
| pine brand-700 vs Facebook #1877F2 | 28.4 | 29.0 | 27.7 | 21.3 | 90° |
| pine brand-700 vs Facebook 2023 #0866FF | 30.1 | 29.9 | 29.3 | 19.7 | 94° |
| pine brand-600 (focus) vs LinkedIn | 18.2 | 17.9 | 18.1 | 5.7 | 86° |
| pine brand-700 vs success-600 (chip text) | 14.2 | 14.3 | 14.0 | 12.2 | 23° |
| pine brand-700 vs success-500 (icon) | 23.4 | 23.7 | 23.1 | 21.6 | 23° |
| tinted button text brand-700 vs success chip text success-600 | 14.2 | 14.3 | 14.0 | 12.2 | 23° |
| pine brand-600 vs success-500 | 15.5 | 15.5 | 15.2 | 13.2 | 23° |
| pine brand-700 vs info-500 | 9.5 | 9.4 | 9.2 | 4.6 | 65° |
| pine brand-700 vs Neopolis orange #F97316 | 38.0 | 22.0 | 34.4 | 38.9 | 120° |
| pine brand-700 vs Neopolis navy #1E2533 | 16.4 | 16.8 | 14.9 | 15.5 | 96° |
| pine brand-700 vs Instagram purple #8134AF | 26.8 | 19.1 | 17.1 | 16.0 | 142° |
| pine brand-700 vs Instagram magenta #DD2A7B | 35.0 | 9.8 | 20.5 | 37.1 | 168° |
| pine brand-700 vs Telegram #229ED9 | 28.6 | 29.8 | 27.7 | 27.5 | 68° |
| pine brand-700 vs WhatsApp #25D366 | 37.9 | 38.9 | 36.7 | 36.4 | 18° |
| info-500 vs LinkedIn | 11.6 | 12.0 | 11.6 | 8.8 | 22° |
| info-500 vs Telegram | 22.7 | 23.7 | 22.2 | 23.0 | 4° |
| info-500 vs Neopolis navy | 18.8 | 20.0 | 17.7 | 19.8 | 32° |
| link brand-700 vs body ink-900 (why prose links are underlined) | 18.4 | 19.1 | 16.9 | 18.3 | 93° |

Luminance ratio link brand-700 vs body ink-900: 1.91:1; vs ink-700: 1.15:1 (below 3:1, so links in sentences carry a currentColor underline).

#### Accent candidates considered (dE x100 vs LinkedIn #0A66C2: normal / deutan; white-on-fill ratio)

| Candidate | OKLCH L / C / h | vs LinkedIn (normal / deutan) | vs Facebook (normal / deutan) | vs Instagram purple | vs success-600 | White on it |
|---|---|---|---|---|---|---:|
| Graphite indigo (winner's original) `#404DB3` | 0.469 / 0.161 / 273 | 6.9 / 4.1 | 13.5 / 12.4 | 11.6 | 27.0 | 7.17:1 |
| Folio forest `#235342` | 0.403 / 0.060 / 168 | 20.5 / 20.2 | 28.2 / 27.6 | 25.6 | 15.0 | 8.80:1 |
| Harbour sea `#007665` | 0.506 / 0.093 / 178 | 16.9 / 16.6 | 22.4 / 21.6 | 26.2 | 7.7 | 5.56:1 |
| Iris violet `#6B36F6` | 0.529 / 0.260 / 286 | 14.8 / 7.8 | 13.9 / 5.0 | 12.1 | 37.1 | 6.03:1 |
| Re-stepped ink-violet h295 `#5C4295` | 0.450 / 0.131 / 295 | 12.5 / 7.8 | 18.8 / 16.2 | 8.3 | 26.6 | 7.87:1 |
| Teal-pine h180 `#0A5D51` | 0.430 / 0.075 / 180 | 18.2 / 17.9 | 25.7 / 25.0 | 25.3 | 12.9 | 7.79:1 |
| **Pine h168 (chosen) brand-700** `#115641` | 0.406 / 0.075 / 168 | 20.8 / 20.3 | 28.4 / 27.7 | 26.8 | 14.2 | 8.64:1 |

Rows checked: 144; failures: 1 (tertiary ink-500 on sticky bar over navy (NOT ALLOWED; shown to justify the rule))

---

## 24. What came from where, and every must-fix

### 24.1 Base and grafts

| Source | Taken |
|---|---|
| **Quiet graphite (base)** | Cool graphite canvas and ink scale (unchanged), system font at 0 KB, hairline + 1px shadow depth, sidebar white-pill active state, segmented control, manager messages without a bubble, your bubble in ink-100, dark toast with Undo, tinted buttons, sentence-case 11/12px labels, one status partial, the codemod guard and `--color-*: initial` lock, the split of `--primary-ring` (solid) and `--primary-halo` (decorative). |
| Folio | Deep-green accent family (re-stepped to Pine on graphite), lightness-tuned status set and shaped status icons and calendar dots, the approve sequence that holds "Scheduled · Mon 10:10" for 1.2s, the two-line toast with errors that persist, skeletons only after 300ms, radio cards with "Chosen", the 2px field edge drawn without layout shift, Today first on phones only when something waits, calm dark-red destructive buttons, the marketing dark band and one architectural photograph. |
| Harbour | The delivery receipt, the dashed internal note with a lock, "Starting in 10 s · Stop" with a draining line, `aria-live` status announcements, 14/22 table rows, the "Built for agencies in India" marketing section, explicit codemod rules (`text-stone-400` → ink-500, orange-as-pending → warning). |
| Iris | 15/24 chat text, the indeterminate line under a started brief, consecutive messages grouped under one avatar, count badges that roll a digit, Done rows that collapse after three, Cmd/Ctrl+Enter, the composer edge turning brand while focused, `prefers-reduced-transparency`, 24px hit areas for small remove buttons, semantic `@theme inline` utilities (`bg-surface`, `text-fg`, `border-line`) for dark mode later, the white-label contrast guard, creatives never framed in brand colour. |

### 24.2 Must-fix ledger

| Must-fix (design review) | Resolution |
|---|---|
| Graphite: exactly one solid primary per view; Start and Send both solid | Rule in 10.1; Send renders secondary while a brief waits (12.2); Home renders it. Today and Approvals rows use tinted buttons. |
| Graphite: 390px composer and brief layouts must stack | Checkbox on its own row, 44px Send, definition list stacks below 640px (12.1, 12.2); rendered in `final-home-390.png`. |
| Graphite: `:focus-visible` must be a real outline (forced colours) | Global `outline: 2px solid var(--focus-ring); outline-offset: 2px` (9, Part B); fields use a transparent outline that forced colours paints. |
| Graphite: separate warning from danger by lightness | Icons warning-500 L 0.53 vs danger-500 L 0.44: 13.5 / 14.6 / 9.0 (normal / protan / deutan); chip text 11.2 / 12.1 / 7.7. Graphite had 4.1 and 2.9. |
| Graphite: move the accent out of the LinkedIn/Facebook band | Pine h168: ΔE 20.8 from LinkedIn, 28.4 from Facebook, 20.3 / 27.7 under deuteranopia (3.5). |
| Graphite: codemod primary must map to the repo's steps | Primary is brand-700, hover brand-800: same-step rename of orange-700/800 (`STEPS` in `tools/recolor.py`). |
| Graphite: internal note must not borrow warning | Dashed ink-400 on ink-25 with a lock (12). |
| Graphite: empty/failed creative tiles must not be bare | Status icon + one line (19). |
| Graphite: tag remove button under 24px | 24px remove button (10.5). |
| Folio: repeated row actions tinted, one solid per view | Tinted `bg-brand-100 text-brand-700` (10.1). |
| Folio: uppercase tracked eyebrows → sentence case 12/600 | All labels 12/600 ink-500 sentence case; the codemod removed 143 `uppercase` and 125 `tracking-wide*` (5). |
| Folio: visible link underline (currentColor) | Inline links underlined in currentColor, 1px, 3px offset (10.2). |
| Folio: "Scheduled" after approval uses info + calendar, not success | 12.3 and 10.5. |
| Folio: forest primary next to green success | Success text L 0.53 vs Pine L 0.405: ΔE 14.2 (Folio 9.5); accent never in a status pill. |
| Folio: `text-stone-400` → ink-400 fails | Maps to ink-500 (4.67:1+). |
| Folio: radius override shifts calendar/flatpickr | Tailwind's default radii kept; no override (6). |
| Folio: 68 KB font, no rupee | System font, 0 KB, has ₹ (5). |
| Folio a11y: sticky header over a navy creative drops tertiary text to 3.47:1 | Bar opacity 0.92 and only ink-600+ text in bars: 5.82:1 over navy; tertiary is disallowed there (4.31:1, shown in the table). |
| Shared: focus hidden under sticky bars | `scroll-padding-top: 72px` (9). |
| Shared: forced-colours check for box-shadow-only states | `@media (forced-colors: active)` outlines in Part B; QA step in 25. |
| Shared: filter pills 24px | 32px, 44px on touch (10.5). |
| Shared: active nav must not rest on the 1.15:1 fill | 600 weight + brand-700 icon (8.64:1) + `aria-current`; forced-colours outline. |
| Harbour: pale chrome, not a dark sidebar/frame | Pale ink-100 sidebar with a hairline; portal header white (11, 15). |
| Harbour: split success from the accent | Success is its own leaf scale (3.3). |
| Harbour: focus ring ≥ 4.8:1 on light surfaces | brand-600: 5.98 white, 5.58 canvas, 5.19 sidebar, 5.15 tinted button (4.79 only on a translucent bar over a navy creative). |
| Harbour: pending receipt node 3:1 + word | ink-400 ring 3.57:1 + "Pending" (14.3). |
| Harbour: on-ink token set | Not needed (no dark chrome); toast/tooltip on-dark colours verified (brand-300 9.59:1, ink-300 10.88:1). |
| Iris: person bubble neutral; Working not the accent; no coloured glow | ink-100 bubble; Working is info; `--shadow-primary: none`. |

---

## 25. Risks and how they are handled

1. **Accent discipline is manual.** The mechanical rename turned 764 orange uses into Pine, and a review pass with before/after screenshots moved most of them to neutral or warning. A new screen can bring decorative Pine back: review it against principle 1 with a screenshot.
2. **Success chip text margin is thin** (success-600 on success-50 is 4.68:1; the success icon is 3.17:1 on its chip). Both pass; do not lighten success further, and never put success text on ink-100.
3. **Status hues stay distinct for colour-blind users, but only 7–9 apart at the closest pairs** (info vs neutral icon 7.9 under protanopia; warning vs success text 7.4 under deuteranopia). The icon + word rule is mandatory and enforced by the single status partial.
4. **Cross-platform type.** Segoe UI and Roboto are wider than SF Pro: check line breaks of Today rows, buttons and the segmented control at 1366×768 on Windows and 390px on Android. Fallback option: the committed Inter woff2 (0 new bytes).
5. **Cool graphite can feel generic for a premium property audience.** Warmth comes from large real creatives, Pine used sparingly, precise type, human copy and the marketing photograph. Empty workspaces need good empty states.
6. **Control borders at ink-400 look heavier than native fields.** That is the price of WCAG 1.4.11 (3:1); hairlines stay light everywhere else.
7. **The live view adds polling.** Poll only on the Team tab (15s) and pause when the tab is hidden; animate only the working dot.
8. **Old default classes compile to nothing.** The `--color-*: initial` lock in Part A switches Tailwind's default palettes off, so a `bg-stone-100` or `text-orange-700` renders unstyled without any error; `python tools/recolor.py --check` finds them. Never add a default palette back.
9. **Backdrop blur costs GPU on low-end Android:** limited to two bars, with solid fallbacks.
10. **QA additions:** Windows High Contrast pass (focus, selected states, stage nodes), reduced-motion pass (no pulse, instant collapse, static skeleton), keyboard pass of the timeline and chart table, and re-checking every pair in section 23 on any palette change.
