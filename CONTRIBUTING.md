# Contributing to SM Bean

Thanks for your interest in contributing! This guide will help you get started.

## Getting Started

1. Fork the repository and clone your fork
2. Follow the setup instructions in [README.md](README.md) (Docker or local development)
3. Install the pre-commit hooks (see [Pre-commit hooks](#pre-commit-hooks) below)
4. Create a branch for your work: `git checkout -b your-branch-name`

### Pre-commit hooks

We use [pre-commit](https://pre-commit.com) to run lint, format, type, and secret-scanning checks on every commit. Install it once after cloning:

```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
```

From then on, the hooks run automatically. To run them against every file in the repo (useful after pulling in large changes):

```bash
pre-commit run --all-files
```

The hooks catch common mistakes before a push. CI also runs the full Postgres suite, browser and accessibility tests, performance budgets, dependency audits and image builds; passing the hooks does not establish that those checks pass.

## Development Workflow

### Running the app

See the [README](README.md) for full setup instructions. The quick version:

```bash
cp .env.example .env
# Edit .env if needed (defaults work for local dev with Docker PostgreSQL)
docker compose up postgres -d
python manage.py migrate
python manage.py runserver
```

### Running tests

Use Python 3.12, Node 22 and PostgreSQL 16. Install the committed locks rather
than resolving new versions:

```bash
.venv/bin/pip install --require-hashes -r requirements.lock
npm ci --ignore-scripts
(cd theme/static_src && npm ci && npm run build)
```

The CSS build is required for browser and performance checks; its output is
not committed. Python tests use `config.settings.test` from `pyproject.toml`,
local storage and in-memory mail/cache. PostgreSQL defaults are
`DB_HOST=localhost`, `DB_PORT=5432`, `DB_USER=postgres`, `DB_PASSWORD=postgres`
and `DB_NAME=brightbean_test`. Override those variables for your local test
server. pytest-django creates `test_<DB_NAME>`; use different names for
concurrent suites. SQLite cannot exercise the row-locking tests.

| Layer | Command | What a pass establishes |
|---|---|---|
| Unit and integration | `.venv/bin/pytest --cov=apps --cov-report=term-missing` | Full backend suite, including approval, isolation, privacy, provider mocks and task invariants |
| UI state | `npm run test:ui` | The thread's JavaScript state transitions |
| Template accessibility | `.venv/bin/pytest apps/common/tests/test_a11y_sweep.py` | HTML-level labels, dialogs and contrast conventions |
| Palette | `.venv/bin/python tools/recolor.py --check` | No mapped old palette classes or hex values remain |
| Browser and axe | `CI=1 npm run test:e2e` | Golden paths and accessibility checks on Desktop Chrome, iPhone 13 and Pixel 7 |
| Performance | `node tests/lighthouse/run.mjs` after starting the manifest server below | Authenticated mobile performance budgets on Home, Approvals and Calendar |

Run a single Python app during development with `.venv/bin/pytest apps/studio`;
run the **full** suite before a phase gate. An app subset is not a full-suite
result. Keep pass, fail, skipped, quarantined and unrun outcomes distinct.

#### Browser tests

Install the pinned browser binaries and their operating-system dependencies:

```bash
npx playwright install --with-deps chromium webkit
CI=1 npm run test:e2e
# Focused review of the change-request and client-sign-off paths:
CI=1 npx playwright test tests/e2e/golden/06-request-changes.spec.ts tests/e2e/golden/08-client-portal.spec.ts
```

`playwright.config.ts` starts the local e2e server with a real worker, a fake
team and mocked providers. No real account or provider credentials are
needed. It resets a dedicated database whose name ends in `_e2e`; it refuses
remote database hosts and external network calls. `E2E_PORT` and `DB_NAME`
select a separate port and database for parallel runs. The default server
port is 8150 and default database is `brightbean_e2e`.

Use `CI=1` for the complete device gate: iPhone 13 runs WebKit. Without it,
the local configuration uses Chromium with the iPhone viewport and touch
settings, which does not establish Safari coverage. Traces and screenshots
are kept on failure under `test-results/`; the HTML report is in
`playwright-report/`. See [the e2e guide](tests/e2e/README.md) for the named
fixtures, probes, socket guard and session setup.

Every path runs axe against the screens it reaches; serious and critical
violations fail. Path 12 is the only declared pending golden path: TOTP is
implemented in Phase 4. Count those cases as pending, never passing. Visual
baselines are a Phase 3 task, not an existing Phase 1 guarantee.

#### Lighthouse

Build the CSS, install Chromium as above, and start this server in a separate
terminal. `--reset` only recreates the named local test database:

```bash
DB_NAME=brightbean_lighthouse_e2e .venv/bin/python -m tests.e2e.server --reset --no-worker --static manifest --port 8151
```

Once `/health/` answers successfully, run:

```bash
LIGHTHOUSE_BASE_URL=http://127.0.0.1:8151 node tests/lighthouse/run.mjs
```

The harness collects the static files and WhiteNoise serves the compressed
manifest assets. The runner signs in through a test session fixture and
measures Home, Approvals and Calendar three times in mobile mode. Budgets
live in `.lighthouserc.json`; results live under `.lighthouseci/<timestamp>/`
(or `LIGHTHOUSE_OUTPUT_DIR`). Do not upload
reports containing authenticated page content to public storage.

The section 5 targets are Performance ≥ 90, LCP ≤ 2.5 seconds, CLS ≤ 0.1 and
JavaScript ≤ 150,000 compressed bytes, plus interaction latency ≤ 200 ms.
The runner measures real-input Event Timing at 4× CPU slowdown separately
from navigation TBT, and checks its lab INP upper bound against 200 ms.
TBT remains a reported navigation diagnostic; the measured lab INP replaces
the original spec's TBT stand-in. It is not a second interaction gate.
Gzip totals include inline scripts. These lab measurements do not establish
field p75 INP. The runner's own
budget-validation tests run with `node --test tests/lighthouse/*.test.mjs`.

#### Audits and translation compilation

Install `pip-audit==2.10.1` in a separate tools environment if it is absent,
and install GNU gettext (`msgfmt`) using your operating system's package
manager. Then run:

```bash
pip-audit -r requirements.lock --disable-pip --require-hashes --progress-spinner off
npm audit --audit-level=high
(cd theme/static_src && npm audit --audit-level=high)
DJANGO_SETTINGS_MODULE=config.settings.test .venv/bin/python manage.py compilemessages --ignore=.venv --ignore=node_modules
gitleaks detect --source . --redact --no-banner
```

#### Test-writing and phase-gate rules

- Observe a failing test before every behaviour change. Never edit an
  existing test that enforces a `CLAUDE.md` invariant to accommodate a change.
- Use `data-testid` selectors in e2e; add hooks beside existing attributes.
  A template that fails an accessibility check needs a template fix.
- Await the completed action response before inspecting its database state.
  Fixtures and probes must remain named, typed and local; never add an
  endpoint that executes supplied code.
- CI retries are zero. Quarantine a flaky test with a linked issue the same
  day; do not mask it with retries or count quarantine as a pass.
- Screenshot changes need a `visual:` commit with a before/after pair in the
  PR. Do not create Phase 3 baselines as part of Phase 1.
- The Phase 1 gate needs the full pytest suite, three consecutive complete
  browser runs and green CI with all new jobs. Record the tested commit,
  commands, counts, pending cases and CI link in `docs/specs/CHANGELOG.md`.
  Gate verification does not authorize merging, releasing or starting Phase 2.

### Code style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [mypy](https://mypy-lang.org/) for type checking. Run these before submitting a PR:

```bash
ruff check .              # lint
ruff format --check .     # format check
mypy apps/ config/ providers/ tests/ --ignore-missing-imports
```

To auto-fix lint and formatting issues:

```bash
ruff check --fix .
ruff format .
```

CI runs **Agency UI state tests**, **Lint (ruff)**, **Type check (mypy)**, **Test (pytest)** (with migration checks and `compilemessages`), **Docker build**, **Secret scan (gitleaks)**, **Dependency audit**, **E2E (Playwright)** and **Lighthouse CI** on every pull request to `main`. The owner manages the required-check ruleset separately. Never commit real API keys, tokens, or passwords. Put them in your local `.env` (which is gitignored) and reference them by name in `.env.example`.

## Submitting Changes

1. **Keep PRs focused.** One feature or fix per PR. Small PRs get reviewed faster.
2. **Write descriptive commit messages.** Explain *what* and *why*, not just *how*.
3. **Add tests** for new features or bug fixes when possible.
4. **Make sure CI passes.** The PR must pass lint, typecheck, and test checks.
5. **Update documentation** if your change affects setup, configuration, or user-facing behavior.

### PR process

1. Push your branch to your fork
2. Open a pull request against `main`
3. Fill out the PR template
4. A maintainer listed in [`.github/CODEOWNERS`](.github/CODEOWNERS) is auto-requested for review
5. Wait for review, we'll try to respond within a few days
6. Address review feedback in new commits (don't force-push until after approval, so reviewers can see the diff)
7. Once approved, a maintainer will squash-merge your PR into `main`

## Project Structure

```
apps/           # Django applications (accounts, composer, calendar, etc.)
providers/      # Social platform API integrations (one file per platform)
config/         # Django settings, URLs, WSGI/ASGI
templates/      # Django HTML templates
theme/          # Tailwind CSS theme (django-tailwind)
static/         # Static assets (JS, favicons)
tests/          # Test suite
```

## Adding a New Social Platform Provider

Providers live in `providers/` with one file per platform. To add a new one:

1. Create `providers/your_platform.py`
2. Implement the provider class following the pattern in existing providers (e.g., `providers/bluesky.py` for a simple example, `providers/facebook.py` for a full OAuth flow)
3. Key methods to implement:
   - `get_authorization_url()` - Build the OAuth redirect URL
   - `exchange_code()` - Exchange the auth code for tokens
   - `refresh_token()` - Refresh expired tokens
   - `publish()` - Publish content to the platform
   - `get_comments()` / `reply_to_comment()` - Inbox support (optional)
4. Register the provider in the platform choices and connection flow
5. Add the platform's required environment variables to `.env.example`
6. Add setup instructions to the README under **Platform Credentials**
7. Add tests in `tests/providers/`

## Reporting Bugs

Use the [bug report template](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/new?template=bug_report.yml) on GitHub. Include:

- Steps to reproduce
- Expected vs actual behavior
- Your environment (Docker/local, OS, browser)

## Requesting Features

Use the [feature request template](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/new?template=feature_request.yml) on GitHub.

## Security Issues

**Do not open a public issue for security vulnerabilities.** See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## License

By contributing, you agree that your contributions will be licensed under the [AGPL-3.0 License](LICENSE).
