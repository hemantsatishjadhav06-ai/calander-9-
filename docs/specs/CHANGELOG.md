# Beta changelog

One entry per phase of [`docs/BETA_PLAN.md`](../BETA_PLAN.md): the date, what changed, and what the
phase gate (section 6) said. Newest first.

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
- Spec approval: **waiting for the owner.**
