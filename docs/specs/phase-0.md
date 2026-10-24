# Phase 0 plan — the per-workspace feature switch

Spec: [`00-cut.md`](00-cut.md) requirements R1–R4. Plan: [`docs/BETA_PLAN.md`](../BETA_PLAN.md) section 6,
Phase 0. Gate: the spec approved by the owner; `python manage.py makemigrations --check --dry-run`
passes. Nothing a person sees changes.

Every behaviour task starts with a failing test (`test-driven-development`): write it, run it, see
it fail for the right reason, then make it pass. Invariant tests are not edited.

## Task 0 — Documentation discovery (done)

Sources read: `CLAUDE.md` invariant 8; `apps/studio/models.py` (`AgencySettings`, `Routine`);
`apps/blog/models.py`; `apps/studio/admin.py`; `apps/common/timezones.py`; `apps/studio/chat.py`;
Django 5.2.17 source (`fields/__init__.py`, `fields/json.py`, `expressions.py`,
`migrations/serializer.py`).

**Allowed APIs and patterns (copy these):**

| Need | Copy from |
|---|---|
| JSONField with a database default | `apps/blog/models.py:152-157`: `models.JSONField(default=list, db_default=Value([], output_field=models.JSONField()), blank=True, …)` with `from django.db.models import Value` (line 20) |
| Its migration operation | `apps/blog/migrations/0003_seo_keywords_search_console.py:25-34` (`migrations.AddField(… db_default=models.Value([], output_field=models.JSONField()) …)`) |
| Migration skeleton for one added field | `apps/studio/migrations/0006_agencysettings_creation_mode.py`; new file depends on `("studio", "0007_routine")` only |
| One-query read that tolerates a missing settings row | `apps/studio/chat.py:803-808`: lazy `from .models import AgencySettings`, then `AgencySettings.objects.filter(workspace=workspace).values_list(…, flat=True).first()` |
| Helper module style | `apps/common/timezones.py`: module docstring saying why it exists, a constant, typed functions with one-line docstrings |
| Admin registration | `apps/studio/admin.py:6-10` (`BrandProfileAdmin`: `@admin.register`, `list_display`, `search_fields`, `raw_id_fields`) |
| Rollback-safe insert test | `apps/accounts/tests/test_cto_review.py:90-102` (raw INSERT without the new column, assert the database default) |
| Query-count assertion | pytest-django `django_assert_num_queries` / `django_assert_max_num_queries` (`apps/analytics/tests/test_services.py:219-254`) |
| Workspace in a test | `Organization.objects.create(name=…)` then `Workspace.objects.create(organization=…, name=…)` (`apps/common/tests/test_navigation_and_guards.py:40-46`) |

**Anti-patterns:**

- `Value({})` without `output_field` (Django cannot resolve the type for a dict; `expressions.py:1193-1215`).
- `default={}` (a mutable default; `JSONField` wants the callable `dict`).
- `workspace.agency_settings` in the helper (raises when the row is missing).
- A module-level import of `apps.studio` or `apps.blog` in `apps/common/features.py`
  (`apps/studio/models.py` imports `apps.common` at module level: import cycle).
- Creating an `AgencySettings` row from the helper (it must stay read-only).

## Task 1 — The field (R1)

Files: `apps/studio/models.py`, `apps/studio/migrations/0008_agencysettings_features.py`,
`apps/studio/tests/test_features_field.py`.

1. Red: a test that a new `AgencySettings` has `features == {}`; and a rollback-safe test that a
   raw `INSERT INTO studio_agency_settings` naming only the columns the previous release knew
   (no `features`) succeeds and reads back `{}` (copy the shape of
   `test_cto_review.RollbackSafeColumnsTests`).
2. Green: `features = models.JSONField(default=dict, db_default=Value({}, output_field=models.JSONField()), blank=True, help_text=…)`
   after `inbox_drafts_enabled`; `python manage.py makemigrations studio --name agencysettings_features`.
3. Verify: the migration contains one `AddField`; `makemigrations --check --dry-run` reports no changes.

## Task 2 — The helper (R2)

Files: `apps/common/features.py`, `apps/common/tests/test_features.py`.

1. Red, one test each:
   - an unknown key raises `ValueError`;
   - `{"queues": true}` → on for that workspace, off for another workspace (no cross-workspace read);
   - `{"blog": false}` with an enabled blog site → off (explicit wins);
   - no `blog` key + an enabled blog site → on; a disabled blog site → off; no site → off;
   - a non-boolean value (`{"queues": "yes"}`) → the default (off);
   - no `AgencySettings` row → defaults, and the row count is unchanged afterwards;
   - at most two queries (`django_assert_max_num_queries(2)`); exactly one when the key is set.
2. Green: `FEATURE_KEYS`, `feature_enabled(workspace, key) -> bool`, `_DEFAULTS` for `blog` as a
   small function of the workspace. Lazy imports inside the function.
3. Verify: `pytest apps/common/tests/test_features.py` green; mypy clean on the file.

## Task 3 — Admin (R3)

Files: `apps/studio/admin.py`, `apps/studio/tests/test_features_field.py`.

1. Red: as a superuser, the `AgencySettings` change page renders and posting
   `features={"queues": true}` saves it (and `feature_enabled` then says on).
2. Green: `@admin.register(AgencySettings)` with `list_display = ("workspace", "autopilot_enabled", "creation_mode")`,
   `search_fields = ("workspace__name",)`, `raw_id_fields = ("workspace", "lead", "backup", "blog_site", "accounts")`.
3. Added after review (each with a failing test first): `accounts` is a raw id, not
   `filter_horizontal`, so the page lists no other organisation's accounts and decrypts no tokens;
   `workspace` is read-only on an existing row (moving it would carry one workspace's settings to
   another); the admin form saves an emptied `features` or `pillars` box as an empty value instead
   of crashing on the NOT NULL column, and refuses anything but known keys with true or false,
   naming the wrong ones.

## Task 4 — Docs and changelog

- `CLAUDE.md` module map, `common` line: add `features.py` (per-workspace feature switches,
  `feature_enabled`), and one sentence under *How to add things* is not needed yet (Phase 2 adds the
  first reader).
- `docs/specs/CHANGELOG.md`: date, phase, what changed, what the gate said.

## Task 5 — Verification and the gate

- `ruff check . && ruff format --check .`; `mypy apps/ config/ providers/ tests/ --ignore-missing-imports`;
  `makemigrations --check --dry-run`; `npm run test:ui`; `tools/recolor.py --check`.
- Tests of the touched apps, then the full suite (BETA_PLAN section 7: run the full suite before
  every phase gate).
- `engineering:code-review` and `requesting-code-review` on the diff; `verification-before-completion`.
- Grep guards: no template, view or URL calls `feature_enabled` yet (R4); no module-level
  `apps.studio` import in `apps/common/features.py`.
- Paste the gate results; wait for the owner to approve the spec and say "go" for Phase 1.
