<h1 align="center">SM Bean</h1>

<p align="center">
  <strong>Open-source social media management for creators, agencies, and SMBs.</strong>
</p>

<p align="center">
  <a href="https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/workflows/ci.yml"><img src="https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="License: AGPL-3.0"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12%2B-blue.svg" alt="Python 3.12+"></a>
  <a href="https://www.djangoproject.com/"><img src="https://img.shields.io/badge/Django-5.x-green.svg" alt="Django 5.x"></a>
</p>

---

## About SM Bean

SM Bean is an open-source, self-hostable social media management platform built for creators, agencies and SMBs. It does what Sendible, SocialPilot, or ContentStudio do, but free and without per-seat, per-channel, or per-workspace limits. Plan, compose, schedule, approve, publish, and monitor content across Facebook, Instagram, LinkedIn, TikTok, YouTube, Pinterest, Threads, Bluesky, Google Business Profile, Mastodon, DEV.to, and X (publishing only) from a single multi-workspace dashboard.

It's for people managing many client accounts under one roof who'd rather own their social stack than pay $100–300/month to a SaaS vendor. Seats, workspaces and channels are never metered, and publishing, scheduling, approvals, the client portal, inbox and analytics are all included. One optional add-on — AI Intelligence — runs on a paid third-party model and is billed by usage.

Deploy it with a one-click button on Heroku or Render, run it on your own VPS via Docker, or run it locally. All platform integrations talk directly to the official first-party APIs using your own developer credentials, so there's no aggregator middleman, no vendor lock-in, and no third party sitting between you and your data.

## Features

| | |
|---|---|
| **Multi-workspace & teams** | Unlimited orgs → workspaces → members. Granular RBAC with custom roles, invitations, and a separate Client role for external collaborators. |
| **Content composer** | Rich editor with per-platform caption/media overrides, version history, reusable templates, content categories & tags, a Kanban idea board. |
| **Calendar & scheduling** | Visual calendar with recurring weekly posting slots per account and named queues that auto-assign posts to the next available slot. |
| **Publishing engine** | Direct first-party API integrations (no aggregator), automatic retries, per-account rate-limit tracking, and a 90-day publish audit log. |
| **Approval workflows** | Configurable stages (none / optional / internal / internal + client), threaded internal & external comments, reminders, and a full audit trail. |
| **Unified social inbox** | Comments, mentions, DMs, and reviews from every connected platform in one place, with sentiment analysis, assignments, threaded replies, and historical backfill. |
| **Analytics** | Per-post and channel-level performance from every connected platform's native API, with KPI cards, 7/30/90-day trend charts, and a sortable all-posts table for views, engagement, follower growth, reach, and watch time. |
| **AI Agency** | A team of 28 agents in seven departments plans the week, writes and designs posts in the look of your best work, writes SEO blog articles, drafts inbox replies and answers questions in a team thread — staff and clients alike. Everything waits for a person to approve. Needs `ANTHROPIC_API_KEY` (pictures: `FAL_KEY`). See [AI Agency](#ai-agency). |
| **Blog & SEO** | Write posts for the brands' own websites — or have the SEO team write them — with a live SEO score, approve the exact revision, and commit + deploy them through GitHub with a sitemap and RSS feed. Google Search Console rankings per article. Every post gets a designed 1600×900 cover — the title set over its picture in the brand's look — and a "Generate picture" button that paints a wordless image with fal.ai (`FAL_KEY`). |
| **Media library** | Org- and workspace-scoped libraries with nested folders, auto-generated platform-optimized variants, alt text, and built-in Unsplash stock-photo search in the composer. |
| **Client portal** | Passwordless 30-day magic-link access so clients can approve or reject posts without creating an account. |
| **Notifications** | In-app, email, and webhook delivery with per-user preferences for every event type. |
| **Security & ops** | Encrypted token & credential storage, Google SSO, Sentry support, and a 14-day reversible org-deletion grace period. 2FA (TOTP) is on the roadmap. |
| **White-label friendly** | Per-workspace branding (logo, colors) and workspace defaults for hashtags, first comments, and posting templates. |

### A quick look

<table>
  <tr>
    <td colspan="2"><img src=".github/assets/calendar.webp" alt="Calendar view"><br><sub><b>Visual calendar</b> - drag-and-drop scheduling with recurring slots and queues.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src=".github/assets/post-editor.webp" alt="Post editor"><br><sub><b>Post editor</b> - composer with per-platform overrides and previews.</sub></td>
    <td width="50%"><img src=".github/assets/idea-board.webp" alt="Idea kanban board"><br><sub><b>Idea board</b> - Kanban workflow to keep track of all your post ideas.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src=".github/assets/platforms.webp" alt="Connected platforms"><br><sub><b>Connect anything</b> - 10+ first-party integrations, no aggregator.</sub></td>
    <td width="50%"><img src=".github/assets/analytics.webp" alt="Analytics dashboard"><br><sub><b>Performance analytics</b> - per-post and channel-level metrics with KPI cards and trend charts.</sub></td>
  </tr>
</table>

## Supported Platforms

| Platform | Publish | Comments | DMs | Insights |
|---|:---:|:---:|:---:|:---:|
| <img src="https://cdn.simpleicons.org/facebook" width="16" height="16"> Facebook | ✓ | ✓ | ✓ | ✓ |
| <img src="https://cdn.simpleicons.org/instagram" width="16" height="16"> Instagram | ✓ | ✓ | ✓ | ✓ |
| <img src="https://cdn.simpleicons.org/instagram" width="16" height="16"> Instagram (Direct) | ✓ | ✓ | ✓ | ✓ |
| <img src="https://api.iconify.design/logos/linkedin-icon.svg" width="16" height="16"> LinkedIn (Personal) | ✓ | —¹ | — | — |
| <img src="https://api.iconify.design/logos/linkedin-icon.svg" width="16" height="16"> LinkedIn (Company) | ✓ | ✓ | — | ✓ |
| <img src="https://cdn.simpleicons.org/tiktok" width="16" height="16"> TikTok | ✓ | — | — | ✓ |
| <img src="https://cdn.simpleicons.org/youtube" width="16" height="16"> YouTube | ✓ | ✓ | — | ✓ |
| <img src="https://cdn.simpleicons.org/pinterest" width="16" height="16"> Pinterest | ✓ | — | — | ✓ |
| <img src="https://cdn.simpleicons.org/threads" width="16" height="16"> Threads | ✓ | ✓ | — | ✓ |
| <img src="https://cdn.simpleicons.org/bluesky" width="16" height="16"> Bluesky | ✓ | ✓ | — | — |
| <img src="https://api.iconify.design/logos/google-icon.svg" width="16" height="16"> Google Business Profile | ✓ | — | — | ✓ |
| <img src="https://cdn.simpleicons.org/mastodon" width="16" height="16"> Mastodon | ✓ | ✓ | — | — |
| <img src="https://cdn.simpleicons.org/devdotto/000000" width="16" height="16"> DEV.to | ✓ | — | — | — |
| <img src="https://cdn.simpleicons.org/x/000000" width="16" height="16"> X (Twitter) | ✓ | — | — | — |

¹ Reading a member's own posts and their comments needs `r_member_social`, which LinkedIn grants only to select developers. LinkedIn (Company) Pages get comments, first comments posted as the Page, and post statistics. See [LinkedIn](#linkedin).

X's API is pay-per-use with no free tier: every post and every read is billed to the developer account behind your X app, so SM Bean only publishes to X and never polls it for comments, DMs or analytics. See [X (Twitter)](#x-twitter).

---

### One-Click Deploy

| Heroku | Render |
|:------:|:------:|
| [![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/hemantsatishjadhav06-ai/calander-9-) | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/hemantsatishjadhav06-ai/calander-9-) |

After deploying, set these environment variables in your platform's dashboard:

| Variable | Required | Description |
|----------|----------|-------------|
| `DJANGO_SETTINGS_MODULE` | Auto-set | `config.settings.production`. Set if deployment config has not placed it. |
| `SECRET_KEY` | Auto-generated | Django secret key. Set automatically by the deploy button. |
| `ENCRYPTION_KEY_SALT` | Auto-generated | Encryption salt. Set automatically by the deploy button. |
| `DATABASE_URL` | Auto-provisioned | PostgreSQL connection string. Set automatically. |
| `ALLOWED_HOSTS` | Yes | Your app's domain, e.g. `your-app.herokuapp.com` |
| `APP_URL` | Yes | Full public URL, e.g. `https://your-app.herokuapp.com` |
| `STORAGE_BACKEND` | No | Set to `s3` for S3/R2 storage. Default: `local`. Heroku, Render, and Railway have ephemeral filesystems, so uploaded files are lost on redeploy without S3. |
| `SERVE_MEDIA` | No | Only used with `STORAGE_BACKEND=local`. Default: `true`, so Django serves uploads at `/media/`. Those files are served **unauthenticated** — anyone with the path can fetch them. That is required in this mode: Instagram, Threads, Facebook, Pinterest, Google Business and dev.to fetch attachment URLs server-side when publishing, so `/media/` must be publicly reachable. Only the media library, avatars and workspace icons are exposed this way (`PUBLIC_MEDIA_PREFIXES` in `config/urls.py`); comment attachments go through a permission-checked view. Set to `false` only when a reverse proxy or CDN serves those prefixes on the same public path instead. |
| `CADDY_MEDIA_ROOT` | No | docker-compose only. Where Caddy reads uploads from. Default: `/app/media`. Set to `/var/empty` when `STORAGE_BACKEND=s3` — the `media_data` volume survives the switch and Caddy cannot see `SERVE_MEDIA`, so it would otherwise keep serving whatever uploads were left behind. |
| `S3_ENDPOINT_URL` | If using S3 | S3-compatible endpoint URL |
| `S3_ACCESS_KEY_ID` | If using S3 | S3 access key |
| `S3_SECRET_ACCESS_KEY` | If using S3 | S3 secret key |
| `S3_BUCKET_NAME` | If using S3 | S3 bucket name |
| `EMAIL_HOST` | No | SMTP server for sending invitations and password resets |
| `EMAIL_PORT` | No | SMTP port (default: `587`) |
| `EMAIL_HOST_USER` | No | SMTP username |
| `EMAIL_HOST_PASSWORD` | No | SMTP password |
| `GOOGLE_AUTH_CLIENT_ID` | No | For Google OAuth login. Get from [Google Cloud Console](https://console.cloud.google.com/) → Credentials. |
| `GOOGLE_AUTH_CLIENT_SECRET` | No | Google OAuth secret |
| `UNSPLASH_ACCESS_KEY` | No | Enables Unsplash stock-photo search in the composer. Create a free app at [unsplash.com/developers](https://unsplash.com/developers). |

For social media API keys, see [Platform Credentials](#platform-credentials). Full variable reference: `.env.example`.

## Quick Start (Docker)

```bash
git clone https://github.com/hemantsatishjadhav06-ai/calander-9-.git
cd calander-9-
cp .env.example .env
```

Edit `.env` - change `DATABASE_URL` to point to the Docker service name:

```
DATABASE_URL=postgres://postgres:postgres@postgres:5432/brightbean
```

Then start everything:

```bash
docker compose up -d --build
docker compose exec app python manage.py createsuperuser
```

Database migrations run automatically via the `migrate` Compose service before
the `app` and `worker` services start, so there is no separate migrate step.

Tailwind compiles automatically via the `tailwind` Compose service. First build
takes ~60–90 seconds (running `npm install` in a fresh container); subsequent
starts are instant. Watch progress with `docker compose logs -f tailwind`.

Open http://localhost:8000 - you're running.


## Fully Local Development (without Docker)

Run everything natively - no Docker, no PostgreSQL install. Uses SQLite for the database.

### Prerequisites

- Python 3.12+
- Node.js 20+

### Setup

**1. Clone and configure**

```bash
git clone https://github.com/hemantsatishjadhav06-ai/calander-9-.git
cd calander-9-
cp .env.example .env
```

**2. Switch to SQLite**

Open `.env` and replace the `DATABASE_URL` line:

```
DATABASE_URL=sqlite:///db.sqlite3
```

That's it - no database server to install or manage.

**3. Set up Python**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**4. Set up Tailwind CSS**

```bash
cd theme/static_src
npm install
cd ../..
```

**5. Run database migrations**

```bash
python manage.py migrate
```

**6. Create your admin account**

```bash
python manage.py createsuperuser
```

**7. Start the app (3 terminal tabs)**

Tab 1 - Tailwind watcher:
```bash
cd theme/static_src && npm run start
```

Tab 2 - Django dev server:
```bash
source .venv/bin/activate
python manage.py runserver
```

Tab 3 - Background worker:
```bash
source .venv/bin/activate
python manage.py run_worker
```

Open http://localhost:8000 and log in with the superuser you created.

### Daily workflow (Docker-free)

```bash
source .venv/bin/activate                # activate Python env
python manage.py runserver               # start web server
# (open another tab)
python manage.py run_worker              # start worker
```

> **Note:** SQLite is fine for local development and small deployments. For production or heavy concurrent usage, switch to PostgreSQL.

## Running Tests

```bash
pytest
```

With coverage:

```bash
pytest --cov=apps --cov-report=term-missing
```

## Linting & Type Checking

```bash
ruff check .                             # lint
ruff format --check .                    # format check
mypy apps/ config/ --ignore-missing-imports  # type check
```

Auto-fix lint issues:

```bash
ruff check --fix .
ruff format .
```

## Production Deployment

### Docker Compose on a VPS (recommended)

```bash
# On your server:
git clone https://github.com/hemantsatishjadhav06-ai/calander-9-.git
cd calander-9-
cp .env.example .env
# Edit .env:
#   SECRET_KEY=<generate a random 50+ char string>
#   DEBUG=false
#   ALLOWED_HOSTS=yourdomain.com
#   APP_URL=https://yourdomain.com
#   DATABASE_URL=postgres://postgres:<strong-password>@postgres:5432/brightbean

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose exec app python manage.py createsuperuser
```

This starts 5 containers: app (Gunicorn), worker, PostgreSQL, Caddy (auto-HTTPS), and a one-shot migrate container that runs database migrations automatically on startup. Edit the `Caddyfile` with your domain.

With the default `STORAGE_BACKEND=local`, Caddy serves uploaded media directly from the `media_data` volume at `/media/`, so large images and video never occupy a Gunicorn worker thread and byte-range requests (video seeking) work. Django's own `/media/` route stays available as the fallback for deployments without this proxy.

To update:

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Other Platforms

| Platform | Config file | Notes |
|----------|-------------|-------|
| **Heroku** | `Procfile` + `app.json` | Deploy-button ready. Must use Basic+ dynos (Eco dynos break the worker). |
| **Railway** | `railway.toml` | Deploying this repository from [Railway](https://railway.com/new) provisions three services: web (Gunicorn, runs `migrate` on startup), worker (`python manage.py run_worker`), and managed PostgreSQL. The web service's startup `migrate` fires the `post_migrate` hooks that register the recurring tasks, so scheduling works out of the box. |
| **Render** | `render.yaml` | Blueprint with web, worker, PostgreSQL. Must use paid tier. |

All platforms with ephemeral filesystems require `STORAGE_BACKEND=s3` - see `.env.example` for S3 configuration.

**Memory sizing.** Importing the app costs roughly 100 MB before it serves a request, and a warmed Gunicorn worker settles near 200 MB - so the shipped command runs a single threaded worker (`--workers 1 --threads 4`), which fits a 512 MB dyno with room for media handling. Raise `--workers` only when you raise the memory to match; a rule of thumb is 250 MB per worker. Do **not** add `--max-requests`: gthread stops heartbeating at the start of the request that trips the counter, so the arbiter kills the worker mid-request once `--timeout` (30s) passes - which drops whichever upload happened to be that request, and uploads here can be up to 1 GB. The `worker` process needs the same headroom: it downloads videos to disk and streams them to the platform, and if it is killed mid-publish (Heroku's R15, an OOM kill, a deploy) the affected post is failed by the confirmation sweep rather than left in limbo.

**Why the worker runs with `--duration 3600`.** `run_worker` is django-background-tasks' `process_tasks` with three fixes for life as a platform-managed service: it stops gracefully on SIGTERM (the library only listens for SIGTSTP, so a deploy used to kill it mid-task), it releases the task locks a killed worker leaves behind (otherwise `run_publish_cycle` stays locked for an hour after every crash - an hour with no publishing), and it re-registers any recurring schedule the library deleted after repeated failures. Pass `--keep-locks` if you ever run more than one worker replica. Underneath, `process_tasks` is a single non-forking process that runs every task in the same heap and never restarts, so a peak allocation raises RSS permanently - CPython and glibc keep the freed pages in their own arenas. Left alone it ratchets: on a 512 MB Basic dyno it climbed from ~280 MB after a deploy to 566 MB over 15 hours and sat at 110% of quota. `--duration` is checked at the *top* of the run loop, so a task in flight always finishes; the process then exits 0 between tasks and the platform restarts it at its floor. Nothing is lost - a recycle cannot interrupt a publish, and `confirm_pending_publishes` settles anything in flight regardless. Don't go below ~1800s, where Heroku's crash cool-off starts to engage. Other deploy targets keep the plain command: `docker-compose.yml` has no `restart:` policy on the worker, so there a clean exit would simply stop it.

**`MALLOC_ARENA_MAX`.** glibc gives each thread its own arena (up to 64 MB) capped at `8 x nproc`, and containers report the host's core count, so the cap is effectively unbounded. This app has real thread churn - the publisher builds a fresh pool every 15s and boto3's managed transfer adds ten threads per download - and those arenas are never returned to the OS. On Heroku this is already set to 2 by the repo's `.profile`, which applies to web, worker, the release phase and one-off `heroku run` dynos alike; it is written as a default rather than an override, so a config var still wins if you want to tune it. Deploy targets that build from the `Dockerfile` (Render, Railway, docker-compose) do not read `.profile` - set it in their own environment config if the host is memory-tight.

See `architecture.md` for detailed per-platform instructions and cost breakdowns.

## Project Structure

```
calander-9-/
├── config/
│   ├── settings/
│   │   ├── base.py            # Shared settings
│   │   ├── development.py     # Local dev overrides
│   │   ├── production.py      # Production hardening
│   │   └── test.py            # Test overrides
│   ├── urls.py                # Root URL configuration
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   ├── accounts/              # Custom User model, auth, OAuth, sessions
│   ├── organizations/         # Organization management
│   ├── workspaces/            # Workspace CRUD
│   ├── members/               # RBAC, invitations, middleware, decorators
│   ├── settings_manager/      # Configurable defaults with cascade logic
│   ├── credentials/           # Platform API credential storage (encrypted)
│   ├── common/                # Shared: encrypted fields, scoped model managers
│   └── marketing/             # Public pages: /, /features/, /how-it-works/, /platforms/, /developers/, /get-started/
├── providers/                 # Social platform API modules (one file per platform)
├── templates/                 # Django templates
│   ├── base.html              # Layout with sidebar + nav
│   ├── marketing/             # Public marketing site (own layout, no app shell)
│   └── components/            # Reusable HTMX partials
├── static/
│   ├── css/marketing.css      # Hand-written stylesheet for the public pages
│   ├── fonts/                 # Self-hosted web fonts for the public pages (OFL)
│   └── js/                    # Vendored HTMX + Alpine.js, marketing.js
├── theme/                     # django-tailwind theme app
│   └── static_src/
│       ├── src/styles.css     # Tailwind directives
│       └── tailwind.config.js
├── Dockerfile
├── docker-compose.yml         # Dev: app + worker + postgres
├── docker-compose.prod.yml    # Prod override: adds Caddy, uses Gunicorn
├── Caddyfile                  # Reverse proxy + auto-HTTPS config
├── .env.example               # All environment variables
├── Procfile                   # Heroku
├── app.json                   # Heroku deploy button
├── railway.toml               # Railway config
└── render.yaml                # Render blueprint
```

> **Settings selection:** The `DJANGO_SETTINGS_MODULE` environment variable controls which settings file Django uses. The defaults are already wired for each context: `manage.py` uses `development`, `wsgi.py`/`asgi.py` use `production`, and `pytest` uses `test` (via `pyproject.toml`). Docker Compose files and platform deploy configs (Heroku, Render) also set it explicitly. You only need to override it manually if you want a non-default module for a specific command, e.g. `DJANGO_SETTINGS_MODULE=config.settings.production python manage.py check --deploy`.

## Sign in with Google

The login and signup pages show **Sign in with Google** / **Sign up with Google** once both `GOOGLE_AUTH_CLIENT_ID` and `GOOGLE_AUTH_CLIENT_SECRET` are set; without them the button stays hidden (it used to show and lead to Google's "missing client_id" page). Someone new who signs in with Google gets an account and their own workspace, accepts the Terms once, and lands on their calendar — or on the page they were trying to open.

1. In the [Google Cloud Console](https://console.cloud.google.com/apis/credentials), create an **OAuth client ID** of type **Web application**.
2. Add the authorized redirect URI (exactly, with the trailing slash):
   ```
   {APP_URL}/accounts/google/login/callback/
   ```
3. On the **OAuth consent screen**, add the `email` and `profile` scopes and publish the app (while it is in *Testing*, only listed test users can sign in).
4. Set the environment variables on the web service and redeploy:
   ```
   GOOGLE_AUTH_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
   GOOGLE_AUTH_CLIENT_SECRET=your-client-secret
   ```

Who may create an account still follows `SIGNUP_MODE` (default `invite_only`): a Google sign-in from an address that has no invitation and isn't on `SIGNUP_ALLOWLIST` (`ana@agency.com` or a whole domain, `@agency.com`) sees the invite-only page and no account is made. Existing users can sign in with Google if the Google address matches their account's email. Don't also add a Google "Social application" in the Django admin while the variables are set: two apps for one provider make the login page fail. When a Google sign-in fails, the person sees "Google sign-in didn't finish" with a way back, and the reason is logged as `Social sign-in failed: …`.

## Platform Credentials

To connect social media accounts, you need API credentials from each platform's developer portal. You can set these via environment variables in `.env` (see `.env.example`) or, per organization, through the Django admin at `{APP_URL}/admin/` → **Credentials → Platform credentials** (superuser only). If a platform is configured in both places, the `.env` value takes precedence.

**Admin UI access (superuser only):** The Django admin at `{APP_URL}/admin/` (for example `https://social.example.com/admin/`) is restricted to superuser accounts — only a superuser can view or edit platform credentials there. If you don't already have one, create a superuser, then sign in and open **Credentials → Platform credentials**:

```bash
python manage.py createsuperuser
# Docker: docker compose exec app python manage.py createsuperuser
```

**Redirect URI:** When registering your app on any platform, set the OAuth redirect URI to:

```
{APP_URL}/social-accounts/callback/{platform}/
```

For example, if your `APP_URL` is `https://social.example.com`, the Facebook redirect URI would be `https://social.example.com/social-accounts/callback/facebook/`.

> **TikTok:** use the slug `social1` instead of `tiktok` — TikTok rejects redirect URIs containing their brand name. See the [TikTok](#tiktok) section.

### Meta (Facebook, Instagram, Threads)

Facebook and Instagram share the same Meta app credentials. Threads runs on the same Meta app but uses a **separate app identity** — its own App ID, App Secret, and redirect URI list (steps 6-7 below).

1. Go to [Meta for Developers](https://developers.facebook.com/) and create a new app (type: **Business**)
2. Under **App Settings → Basic**, copy your **App ID** and **App Secret** — the plain ones, for Facebook and Instagram. Once the Threads use case is added this page also lists a **Threads App ID** / **Threads App Secret**; those are a different app identity and belong in the Threads variables in step 7, not here.
3. In the App Dashboard, go to **Use cases** and add the following four use cases. For each use case, click into it and go to **Permissions and features** to add the required optional permissions:

   **Use case: "Manage everything on your Page"** (Facebook)
   - This use case auto-includes `business_management`, `pages_show_list`, and `public_profile`
   - Add these optional permissions: `pages_manage_posts`, `pages_manage_engagement`, `pages_read_engagement`, `pages_read_user_content`, `pages_manage_metadata`, `read_insights`

   **Use case: "Messenger from Meta"** (Facebook Messaging)
   - Required to enable the `pages_messaging` permission, which is not available under the "Manage Pages" use case
   - Add the optional permission: `pages_messaging`

   **Use case: "Manage messaging & content on Instagram"** (Instagram)
   - Add these permissions: `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_insights`

   **Use case: "Access the Threads API"** (Threads)
   - This use case auto-includes `threads_basic`
   - Add these optional permissions: `threads_content_publish`, `threads_manage_insights`, `threads_manage_replies`

4. Under **Facebook Login → Settings → Valid OAuth Redirect URIs**, add the following redirect URIs:
   ```
   {APP_URL}/social-accounts/callback/facebook/
   {APP_URL}/social-accounts/callback/instagram/
   ```
   > **Threads is separate.** Its callback does **not** belong here — the Threads use case keeps its own redirect URI list. See step 7.
5. **Webhooks (required for the inbox).** In the App Dashboard, go to **Webhooks** (also reachable via **Use cases → Manage everything on your Page → Webhooks**) and subscribe to the **Page** object:
   - **Callback URL:** `{APP_URL}/webhooks/facebook/`
   - **Verify token:** the value of `FACEBOOK_WEBHOOK_VERIFY_TOKEN` from your `.env` (any random string; generate one and set the env var before clicking *Verify and save*)
   - After verification, subscribe to the `feed`, `mention`, and `messages` fields. `feed` is what carries comments on your Page's posts.

   > **This step is easy to miss and fails silently.** Connecting a Page subscribes it to your app automatically, so the account shows as healthy either way — but without the callback URL configured here, Meta never delivers anything. Comments then arrive only through the 5-minute polling fallback, and mentions not at all. Run `python manage.py diagnose_facebook --account-id <uuid>` to check.

   **If you connect Instagram through this Facebook app, also subscribe to the `Instagram` object** on the same Webhooks page:
   - **Callback URL:** `{APP_URL}/webhooks/facebook/` (the same endpoint — it handles both platforms)
   - Subscribe to the `comments` and `mentions` fields.

   > `comments` and `mentions` belong to the **Instagram** object, not the Page — a Page accepts only its own fields (`feed`, `mention`, `messages`, …). Studio subscribes the Instagram *account* automatically on connect, but the object-level configuration here can only be done in the dashboard. Without it, Instagram comments arrive only via the 5-minute poll and mentions not at all.
6. Set the environment variables:
   ```
   PLATFORM_FACEBOOK_APP_ID=your-app-id
   PLATFORM_FACEBOOK_APP_SECRET=your-app-secret
   # Optional: Facebook Login for Business configuration ID for agency/multi-business onboarding
   PLATFORM_FACEBOOK_CONFIG_ID=your-configuration-id
   FACEBOOK_WEBHOOK_VERIFY_TOKEN=your-random-verify-token
   ```
   When `PLATFORM_FACEBOOK_CONFIG_ID` is set, Facebook and the Facebook-login
   Instagram connector use that Login for Business configuration instead of
   sending an ad-hoc `scope` list. Configure the required permissions and asset
   selection in Meta's configuration, and include every business whose Pages
   should be available to the login.
7. **Threads:** the "Access the Threads API" use case gets its own App ID, App Secret, and redirect URIs. Go to **Use cases → Access the Threads API → Settings** and add the Threads redirect URI:
   ```
   {APP_URL}/social-accounts/callback/threads/
   ```
   Then copy the **Threads App ID** and **Threads App Secret** (also listed under **App settings → Basic**, alongside — and different from — your Facebook App ID) and set:
   ```
   PLATFORM_THREADS_APP_ID=your-threads-app-id
   PLATFORM_THREADS_APP_SECRET=your-threads-app-secret
   ```
   These have no fallback: until both are set, Threads shows as **Not Configured** on the connect page. Sending the Facebook App ID to Threads fails with error `4476002`.

### Instagram (Direct, via Instagram Login)

The Instagram (Direct) connector uses the **Instagram API with Instagram Login** - a separate OAuth flow from the Facebook Login-based Instagram connector above. It works with **Professional** Instagram accounts (Business or Creator) **without** requiring a linked Facebook Page.

> **Account-type requirement:** Personal Instagram accounts have no API access since the Instagram Basic Display API was retired on 2024-12-04. Users must convert their account to Professional first (free, in IG Settings → *Account type and tools* → *Switch to professional account*).

1. In the same Meta app, go to **Use cases** and add the **"Instagram API"** use case
2. Under **API setup with Instagram Login**, note your **Instagram App ID** and **Instagram App Secret** (these are different from your Facebook App ID/Secret)
3. Go to **Permissions and features** and add the required permissions:
   - `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_comments`, `instagram_business_manage_messages`, `instagram_business_manage_insights`
4. Under **API setup with Instagram Login → Step 4: Set up Instagram business login**, click **Set up** and add the redirect URI (must match exactly, including the trailing slash):
   ```
   {APP_URL}/social-accounts/callback/instagram_login/
   ```
5. Under **API setup with Instagram Login → Step 3: Configure webhooks**, set:
   - **Callback URL:** `{APP_URL}/webhooks/instagram_login/`
   - **Verify token:** the value of `INSTAGRAM_LOGIN_WEBHOOK_VERIFY_TOKEN` from your `.env` (any random string; generate one and set the env var before clicking Verify and save). After verification, subscribe to the `messages`, `comments`, and `mentions` fields.
6. Set the environment variables:
   ```
   PLATFORM_INSTAGRAM_APP_ID=your-instagram-app-id
   PLATFORM_INSTAGRAM_APP_SECRET=your-instagram-app-secret
   INSTAGRAM_LOGIN_WEBHOOK_VERIFY_TOKEN=your-random-verify-token
   ```

### LinkedIn

SM Bean supports two LinkedIn paths. Pick whichever your LinkedIn dev app can obtain - or both, on separate apps.

**Path A - Personal-only (any individual developer can do this):**

1. Go to the [LinkedIn Developer Portal](https://developer.linkedin.com/) and create a new app (no Company Page verification required).
2. Under **Products**, request access to (both auto-approved):
   - **Sign In with LinkedIn using OpenID Connect**
   - **Share on LinkedIn**
3. Under **Auth**, add the redirect URI:
   ```
   {APP_URL}/social-accounts/callback/linkedin_personal/
   ```
4. Scopes: `openid`, `profile`, `email`, `w_member_social`.
5. Set the environment variables:
   ```
   PLATFORM_LINKEDIN_PERSONAL_CLIENT_ID=your-client-id
   PLATFORM_LINKEDIN_PERSONAL_CLIENT_SECRET=your-client-secret
   ```

> **Limitations of Path A:** access tokens last ~60 days and LinkedIn does not issue refresh tokens for these scopes - users must manually reconnect every ~60 days. Inbox / comment-reading is not available for personal accounts on this path.

**Path B - Company Pages (also enables full Personal features):**

1. Go to the [LinkedIn Developer Portal](https://developer.linkedin.com/) and create a new app.
2. Verify the app's association with a LinkedIn Company Page.
3. Under **Products**, request access to:
   - **Community Management API** *(restricted - requires LinkedIn review)*
4. Under **Auth**, add **both** redirect URIs:
   ```
   {APP_URL}/social-accounts/callback/linkedin_personal/
   {APP_URL}/social-accounts/callback/linkedin_company/
   ```
5. Scopes requested (all granted by the Community Management API product):
   - **Company:** `r_basicprofile`, `w_member_social`, `w_organization_social`, `r_organization_social`, `rw_organization_admin`, `w_organization_social_feed`, `r_organization_social_feed`
   - **Personal:** `r_basicprofile`, `w_member_social`, `w_member_social_feed`
6. Set the environment variables:
   ```
   PLATFORM_LINKEDIN_COMPANY_CLIENT_ID=your-client-id
   PLATFORM_LINKEDIN_COMPANY_CLIENT_SECRET=your-client-secret
   ```

If you set only the Path B (Company) credentials, SM Bean automatically reuses them for personal connections too, with 365-day refresh tokens. You only need Path A vars if you have a separate Personal-only app.

What a connected Company Page gets:

- **Connecting** lists every Page you are an *Administrator* of (`/rest/organizationAcls`), with its name and logo; pick the ones to add to the workspace.
- **Posts** go out as the Page: text, links, a video, or 1–20 images (two or more become one multi-image post), with each image's alt text from the composer. GIFs are posted as images. `#hashtags` stay real, linked hashtags; every other reserved character is escaped so LinkedIn doesn't cut the caption short.
- **The first comment** (where the link usually goes) and replies from the inbox are posted **by the Page**, not by the admin who connected it. A retried first comment is never doubled.
- **Inbox** picks up comments on the Page's 20 latest posts, leaving out the Page's own.
- **Statistics**: impressions, reactions, comments, reposts and clicks per post (organic), up to 20 posts per API call.
- **Health check** refreshes the Page's name, logo and follower count — and reports the account if the person who connected it is no longer one of its admins.

> **Scopes must match the app.** LinkedIn refuses the whole sign-in when even one requested scope isn't granted to the app (the callback then says so). The app's **Auth** tab on developer.linkedin.com lists the scopes it holds. If yours differs — for example an older app that still holds `r_member_social`, which turns the Personal inbox back on — set the list explicitly, space- or comma-separated:
> ```
> PLATFORM_LINKEDIN_COMPANY_SCOPES=r_basicprofile w_member_social w_organization_social r_organization_social rw_organization_admin
> PLATFORM_LINKEDIN_PERSONAL_SCOPES=r_basicprofile w_member_social r_member_social
> ```
> Without `w_organization_social_feed` the Page can't post its first comment, and without `r_organization_social_feed` its inbox stays empty.

> **Note:** "Sign In with LinkedIn using OpenID Connect" / "Share on LinkedIn" and "Community Management API" are **mutually exclusive** on a single LinkedIn app. You need separate apps for Path A and Path B.

> **Backwards compatibility:** the legacy `PLATFORM_LINKEDIN_CLIENT_ID` / `PLATFORM_LINKEDIN_CLIENT_SECRET` env vars are still honored as a fallback for both `linkedin_personal` and `linkedin_company` - existing self-hosters keep working without changes. The legacy credentials are assumed to be CM-approved; if your legacy app is OIDC-only, migrate it to `PLATFORM_LINKEDIN_PERSONAL_*`.

### TikTok

1. Go to the [TikTok Developer Portal](https://developers.tiktok.com/) and create a new app
2. Add the products **Login Kit** and **Content Posting API**
3. Configure the redirect URI — use `social1`, not `tiktok` (TikTok rejects URIs containing their brand name):
   ```
   {APP_URL}/social-accounts/callback/social1/
   ```
4. Required scopes: `user.info.basic`, `video.publish`, `video.upload`, `video.list`
5. Note: TikTok uses **Client Key** (not Client ID). Copy the **Client Key** and **Client Secret** from your app dashboard
6. Set the environment variables:
   ```
   PLATFORM_TIKTOK_CLIENT_KEY=your-client-key
   PLATFORM_TIKTOK_CLIENT_SECRET=your-client-secret
   ```
7. For production review, record the demo video against a TikTok **Sandbox** showing every requested scope in use.

### Google (YouTube, Google Business Profile)

YouTube and Google Business Profile share the same Google Cloud credentials.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a new project (or select an existing one)
2. Enable the following APIs under **APIs & Services → Library**:
   - **YouTube Data API v3** (for YouTube)
   - **My Business Account Management API**, **My Business Business Information API**, and **Google My Business API** (for Google Business Profile)
3. Go to **APIs & Services → Credentials** and create an **OAuth 2.0 Client ID** (type: Web application)
4. Add the following redirect URIs under **Authorized redirect URIs**:
   ```
   {APP_URL}/social-accounts/callback/youtube/
   {APP_URL}/social-accounts/callback/google_business/
   ```
5. Copy the **Client ID** and **Client Secret**
6. Required scopes:
   - **YouTube:** `https://www.googleapis.com/auth/youtube.upload`, `https://www.googleapis.com/auth/youtube.readonly`, `https://www.googleapis.com/auth/youtube.force-ssl`, `https://www.googleapis.com/auth/yt-analytics.readonly`
   - **Google Business Profile:** `https://www.googleapis.com/auth/business.manage`
7. Set the environment variables:
   ```
   PLATFORM_GOOGLE_CLIENT_ID=your-client-id
   PLATFORM_GOOGLE_CLIENT_SECRET=your-client-secret
   ```

### Pinterest

1. Go to the [Pinterest Developer Portal](https://developers.pinterest.com/) and create a new app
2. Under your app settings, add the redirect URI:
   ```
   {APP_URL}/social-accounts/callback/pinterest/
   ```
3. Copy the **App ID** and **App Secret**
4. Required scopes: `user_accounts:read`, `boards:read`, `pins:read`, `pins:write`
5. Set the environment variables:
   ```
   PLATFORM_PINTEREST_APP_ID=your-app-id
   PLATFORM_PINTEREST_APP_SECRET=your-app-secret
   ```

### Bluesky

No developer app registration needed. Users connect by entering their Bluesky handle and an **App Password**:

1. Log in to [Bluesky](https://bsky.app/)
2. Go to **Settings → Privacy and Security → App Passwords**
3. Create a new app password and use it when connecting your account in SM Bean

### Mastodon

No developer app registration needed. SM Bean automatically registers an OAuth application on each Mastodon instance when a user connects their account. Users just need to enter their instance URL (e.g., `mastodon.social`).

### DEV.to

No developer app registration needed. Users connect by entering a personal **API key**:

1. Log in to [DEV.to](https://dev.to/) and open **[Settings → Extensions](https://dev.to/settings/extensions)**
2. Under **DEV Community API Keys**, enter a description (e.g. `SM Bean`) and click **Generate API Key**
3. Copy the generated key and paste it when connecting your account in SM Bean

Posts publish as DEV.to articles (title + Markdown body). The key can be revoked at any time from the same settings page.

### X (Twitter)

SM Bean publishes to X through the official X API v2 with OAuth 2.0 (Authorization Code + PKCE). It is **publishing only**: text with up to 4 images, or one video or GIF. Comments, DMs and analytics are deliberately not wired up.

> **X's API is pay-per-use, with no free tier.** Requests are billed to the credits of the developer account that owns the app: each published post (as of October 2026 roughly $0.015, or about $0.20 when the post contains a link), and reads too, including the profile lookup the connection health check makes every six hours. Inbox polling and analytics sync would run unattended and spend those credits, which is why SM Bean doesn't do either for X. When the balance runs out, X refuses posts and they fail with "X rejected the post: the X developer account has no API credits. Add credits at console.x.com." Check current prices on the X developer console before you connect.

1. Sign in to the [X developer console](https://console.x.com/) and create an app
2. Enable **OAuth 2.0** user authentication for it as a **confidential client** (a web app, not a native/public one) with read and write permission
3. Add the callback URI:
   ```
   {APP_URL}/social-accounts/callback/x/
   ```
   If you send clients connection links (onboarding), add `{APP_URL}/onboarding/connect/callback/x/` as well.
4. Copy the **OAuth 2.0 Client ID** and **Client Secret** (not the API Key / API Secret, which are OAuth 1.0a credentials)
5. Scopes requested: `tweet.read`, `tweet.write`, `users.read`, `offline.access`, `media.write`
6. Add API credits to the developer account
7. Set the environment variables:
   ```
   PLATFORM_X_CLIENT_ID=your-oauth2-client-id
   PLATFORM_X_CLIENT_SECRET=your-oauth2-client-secret
   ```

Access tokens last two hours and are refreshed automatically; X rotates the refresh token on every refresh. The composer counts X's 280-character limit the way X does: every link counts as 23 characters, and CJK characters and emoji count as two.

### fal.ai (blog cover pictures)

The blog editor's **Generate picture** button asks fal.ai for a wordless 16:9 picture that fits the post, saves it to the media library and selects it as the featured image. The **designed cover** then sets the title, category tag and brand wordmark over it with Pillow (`apps/blog/covers.py`, fonts bundled under `apps/blog/fonts/`), so the website's hero, the index card and the `og:image` all carry the headline — the model is never asked to draw text.

1. Create an API key at [fal.ai/dashboard/keys](https://fal.ai/dashboard/keys) and add credit to the account.
2. Set the environment variables (on the web **and** worker services):
   ```
   FAL_KEY=your-fal-key
   FAL_IMAGE_MODEL=fal-ai/flux/dev   # optional; fal-ai/flux/schnell is faster, fal-ai/flux-pro/v1.1 finer
   ```
3. Without `FAL_KEY` the button is shown disabled with a note; posts still get the designed cover on the brand background, and uploaded pictures work as before.

Each post's **Cover** setting chooses between the designed cover (default) and the plain featured image.

## AI Agency

**Agency** in the sidebar is a team of 28 agents — 23 running on Claude, one painting pictures with fal.ai, one setting type with Pillow, and three plain-code agents — organised like a small agency in seven departments. It plans, writes, designs, checks and proposes times for posts and blog articles, reads what people say and how posts did, and learns the house style from your best creatives. **Nothing it makes goes out until a person approves it**: every post and article lands in the normal approval queue.

| Department | Agents |
|---|---|
| Client services | **Account manager** (answers questions and change requests in the team thread, and hands them to the right agent) · **Client reporter** (the weekly report) |
| Strategy | **Content strategist** (three angles from one idea) · **Content planner** (next week's posts for your open slots) · **Moments scout** (festivals, seasons, industry dates) |
| Insights | **Performance analyst** (what worked, against each account's own average) · **Audience listener** (questions, praise and complaints in comments, messages and reviews) · **Creative memory curator** (studies your best creatives and your designer's references and writes down the house style) |
| Creative | **Copywriter** · **Channel editor** (the version each network needs) · **Art director** · **Prompt engineer** (writes the image prompt from the art director's direction and your best past creatives) · **Illustrator** (fal.ai) · **Graphic designer** (Pillow) |
| Quality | **Brand reviewer** · **QA inspector** (lengths per network, hashtags, links, alt text, contrast) · **Fact checker** · **Editor-in-chief** |
| Publishing | **Scheduler** (proposes the best free time from the account's history; never schedules) · **Producer** (creates the draft and submits it for approval) · **Community manager** and **Reviews manager** (draft replies for a person to send; unhappy reviews are flagged) |
| Blog & SEO | **SEO strategist** · **Outline editor** · **Blog writer** · **SEO editor** · **Repurposer** (turns an article into posts) · **SEO monitor** (scores published articles, reads Google rankings, suggests refreshes) |

**A post**, from one line or from the weekly plan: strategist → copywriter → art director → prompt engineer → illustrator → designer → brand reviewer → channel editor → QA inspector → scheduler → producer. Two to four minutes later it waits on the agency home under *Waiting for you* with a proposed time; **Approve & schedule for <time>** is one click by an owner or manager.

**Same look as your best work.** With *Match the look of the last post* on (the default), the next graphic copies the layout, canvas, colour treatment and picture style of the last one. **Agency → Creative memory** ranks published creatives against each account's own average, lets you mark any of them — or upload your designer's best work — as *Learn from this*, and keeps a house-style paragraph the curator writes (editable by managers). The art director, the prompt engineer and the reviewer all read it.

**Autopilot** (**Agency → Autopilot**, workspace owners): posts per week, accounts, content pillars, the weekday and hour to plan, blog articles per month and a monthly budget. At the planning time the planner fills next week's open slots and the team makes every post; the lead approver gets one notification when they are all ready. It never approves or schedules — *Nothing goes out without you*.

**Ask the team.** The agency home and every post have a thread with the account manager: ask a question, or ask for a change ("make the headline shorter", "new picture", "write one about Saturday's site visit") and the right agent does it. Staff can leave internal notes clients never see. Clients get the same thread in the client portal (**Talk to the team**, and *Ask a question* / *Request a change* on each post waiting for them), and the portal's **Reports** page shows the weekly report. Their requests still need internal approval.

**Blog & SEO.** **Write with the team** on the blog list turns a topic into a full article: keyword and intent, outline, the article with links to your other articles, a fact check against the brand facts, the search title, description and slug, an editor's final read and a designed cover — then it waits for approval like any article. The editor shows a live **SEO score** (0–100, each check with its fix) and the Google result preview; *Ask the SEO team* and *Improve SEO* send an article back for a revision; *Make social posts* turns an approved article into posts. Published pages get complete Open Graph and Article structured data, related articles, and the blog's `sitemap.xml` and RSS `feed.xml` are written in the same commit. Connect **Google Search Console** on the blog list to see each article's position, clicks and top searches; **Run an SEO check-up** (and a weekly run) has the SEO monitor suggest what to refresh.

**Inbox drafts.** With *Draft replies to comments, messages and reviews* on in Autopilot (or **Draft replies with the team** in the inbox), new comments, mentions, reviews and recent messages get a reply drafted by the community manager or the reviews manager, labelled as such in the inbox. A person sends it; one- and two-star reviews are flagged to the inbox staff.

**Cost control.** Every agent's turn is recorded with tokens and an estimated cost at list prices (Claude Opus 5.5: tens of cents per post, around a dollar per article; fal.ai about $0.03 per picture). Autopilot, the thread and the blog team stop starting new work when the month's estimated spend reaches the workspace's budget, and the agency home shows the meter. The thread has a daily reply cap per workspace. Agent work runs below publishing in the worker's queue, so it never delays a scheduled post by more than one agent's turn.

Setup — on the web **and** worker services (the agents run in the background worker):

```
ANTHROPIC_API_KEY=sk-ant-...        # required; console.anthropic.com
STUDIO_MODEL=claude-opus-5-5        # optional; the Claude model every agent uses
STUDIO_EFFORT=                      # optional; low|medium|high|xhigh|max for every agent (default: per agent)
STUDIO_TIMEOUT=300                  # optional; seconds per agent turn
STUDIO_FALLBACKS=true               # optional; retry a falsely declined request on Anthropic's fallback model
STUDIO_WEB_SEARCH=false             # optional; lets the moments scout and SEO strategist search the web ($0.01 a search)
AGENCY_MAX_ACTIVE_BRIEFS=3          # optional; posts the autopilot has in the works at once, across workspaces
FAL_KEY=...                         # optional; pictures (see fal.ai above)
GSC_CLIENT_ID=                      # optional; Google Search Console rankings (see below)
GSC_CLIENT_SECRET=
INDEXNOW_KEY=                       # optional; tells Bing and other IndexNow engines when an article goes live
```

**Google Search Console** (optional): in Google Cloud Console create an OAuth client ID (Web application), enable the *Google Search Console API*, add the redirect URI `{APP_URL}/blog/search-console/callback/`, and set `GSC_CLIENT_ID` / `GSC_CLIENT_SECRET` on both services. Then an owner chooses **Connect Google Search Console** on the blog list and picks the property for that website (the Google account must have access to it). Rankings sync daily.

## Inbox: Backfill Historical Messages

See the [Supported Platforms](#supported-platforms) matrix above for per-platform inbox capabilities.

To import historical messages (e.g., from the last 7 days):

```bash
python manage.py backfill_inbox --days 7
```

Options:
- `--days N` - Number of days to backfill (default: 7)
- `--platform NAME` - Only backfill a specific platform (e.g., `facebook`, `youtube`, `linkedin`, `tiktok`)
- `--account-id UUID` - Only backfill a specific account

For Facebook this recovers comments on the Page's posts from the last 30 days — useful after fixing a webhook that was never delivering, since comments missed while it was broken are otherwise invisible:

```bash
python manage.py backfill_inbox --platform facebook --days 30
```

## Inbox: Diagnosing a Facebook Page That Receives Nothing

When a Page's comments never reach the inbox, or a post's first comment never appears, the cause is usually a permission that was not granted or a webhook that was never configured — neither of which is visible from inside the app. Ask Meta directly:

```bash
python manage.py diagnose_facebook --account-id <uuid>
```

It reports the token's granted scopes (a missing `pages_manage_engagement` is why first comments fail), which app is subscribed to the Page and to which fields (`feed` is what carries comments), and whether comments are readable at all. Add `--subscribe` to repair a missing Page subscription in place, or `--json` for output to paste into an incident.

## API & MCP for Agents

SM Bean ships a REST API and an MCP (Model Context Protocol) server so agents and scripts can read analytics, manage media, and create or schedule posts. Both share the same authentication, permission model, rate limits, and audit log. Pick whichever protocol fits your client.

**Base URL:** `{APP_URL}/api/v1/` (e.g. `https://your-studio.example.com/api/v1/`)

### Authentication

Issue an API key from **Organization → API Keys**. Keys are workspace-scoped, can be allowlisted to specific social accounts, and inherit a subset of the issuer's workspace permissions. Revocation takes effect immediately. Send the key as a Bearer token:

```
Authorization: Bearer bb_studio_...
```

Permission keys: `create_posts`, `publish_directly`, `upload_media`, `view_analytics`, `use_inbox`, `reply_from_inbox`. Each endpoint requires the relevant permission; missing permissions return `403`.

### Rate Limits

| Scope | Limit |
|---|---|
| Per-key writes | 120 / min |
| Per-key reads | 300 / min |
| Per-workspace aggregate | 1000 / min |

Rate-limit responses (`429`) include `Retry-After`, `X-RateLimit-Limit`, and `X-RateLimit-Remaining` headers.

### REST Endpoints

| Method | Path | Purpose | Permission |
|---|---|---|---|
| `GET` | `/me` | Inspect caller scope and workspace permissions | — |
| `GET` | `/accounts` | List connected social accounts | — |
| `POST` | `/posts` | Create a draft or scheduled post | `create_posts` (+ `publish_directly` to schedule) |
| `GET` | `/posts/{post_id}` | Read a single post | — |
| `PATCH` | `/posts/{post_id}` | Update draft fields | `create_posts` |
| `POST` | `/posts/{post_id}/schedule` | Schedule a draft | `create_posts` + `publish_directly` |
| `POST` | `/posts/{post_id}/cancel` | Revert a scheduled post to draft | `create_posts` |
| `GET` | `/analytics/accounts/{account_id}` | Channel analytics summary (7/30/90-day window) | `view_analytics` |
| `GET` | `/analytics/posts/{post_id}` | Post analytics with per-platform metrics | `view_analytics` |
| `POST` | `/media` | Upload a media file (multipart) | `upload_media` |
| `GET` | `/media/{media_id}` | Retrieve a media asset | — |
| `GET` | `/media` | List media assets (filter, paginate) | — |
| `GET` | `/inbox` | List inbox messages (filter by status/type/account, paginate) | `use_inbox` |
| `GET` | `/inbox/{message_id}` | Read one inbox message with its reply thread | `use_inbox` |
| `POST` | `/inbox/{message_id}/replies` | Draft a reply (set `send: true` to deliver it now) | `use_inbox` (+ `reply_from_inbox` to send) |
| `PATCH` | `/inbox/replies/{reply_id}` | Edit a draft reply | `use_inbox` |
| `POST` | `/inbox/replies/{reply_id}/send` | Deliver a draft reply to the platform | `reply_from_inbox` |
| `DELETE` | `/inbox/replies/{reply_id}` | Discard a draft reply | `use_inbox` |
| `POST` | `/mcp` | JSON-RPC 2.0 endpoint for MCP clients | — |

Post creation, media uploads, and inbox reply creation accept `idempotency_key` (or `Idempotency-Key` header) for safe retries.

For inbox reply creation, reuse the same key and request to replay the original response without creating or sending another reply. A failed create-and-send response is replayed too; retrieve the retained failed reply from the message thread and retry delivery via `/inbox/replies/{reply_id}/send`.

### MCP Tools

The MCP server lives at `POST {APP_URL}/api/v1/mcp` and speaks JSON-RPC 2.0 over Streamable HTTP. It implements the standard `initialize`, `tools/list`, `tools/call`, and `ping` methods. Tools:

| Tool | Purpose | Permission |
|---|---|---|
| `list_accounts` | List social accounts this API key can act on | — |
| `create_draft` | Create a draft post (caption, title, media, first comment, optional proposed publish time) | `create_posts` |
| `schedule_post` | Create and schedule a post in one step | `create_posts` + `publish_directly` |
| `schedule_draft` | Schedule an existing draft | `create_posts` + `publish_directly` |
| `get_post` | Retrieve a post with aggregate status and per-platform state | — |
| `list_posts` | List posts newest-first, with optional status filter and cursor pagination | — |
| `cancel_post` | Revert a scheduled post back to draft | `create_posts` |
| `search_media` | Find media assets by query, type, tags, or folder | — |
| `get_media` | Retrieve a single media asset by ID | — |
| `upload_media` | Upload a small base64-encoded file (≤ 1 MB raw). For larger files, use REST `POST /media`. | `upload_media` |
| `get_account_analytics` | Channel analytics over a rolling 7–90 day window | `view_analytics` |
| `get_post_analytics` | Per-platform metrics for a single post (safe for polling drafts) | `view_analytics` |
| `list_inbox_messages` | List inbox items (comments, mentions, DMs, reviews) with their reply threads | `use_inbox` |
| `get_inbox_message` | Retrieve one inbox message and its reply thread | `use_inbox` |
| `create_reply_draft` | Draft a reply to an inbox message (saved, not sent) | `use_inbox` |
| `update_reply_draft` | Replace the body of a draft (or failed) reply | `use_inbox` |
| `discard_reply_draft` | Delete a draft (or failed) reply | `use_inbox` |
| `send_reply` | Deliver a reply (`reply_id`, or `message_id` + `body` to draft-and-send) | `reply_from_inbox` |

### Connecting an MCP client

The server is at `{APP_URL}/api/v1/mcp` and supports two authentication modes — pick whichever your client uses.

**Claude Desktop (and other native OAuth connectors).** In Claude Desktop open **Settings → Connectors → Add custom connector**, name it, and enter the server URL `{APP_URL}/api/v1/mcp`. Claude registers itself (Dynamic Client Registration) and opens a browser to log in to SM Bean and approve access — **no API key required**. Any Studio user can connect; the connection acts with **their own** workspace permissions (read-only roles get the read tools, while posting/scheduling/uploading require the matching permission), operating on their last-active workspace. Requires Studio to be served over a public **https** URL.

**Claude Code, Cursor, custom agents (static API key).** Point the client at the same URL and send an API key as a Bearer token (`Authorization: Bearer bb_studio_...`). For Claude Code:

```bash
claude mcp add --transport http smbean {APP_URL}/api/v1/mcp \
  --header "Authorization: Bearer bb_studio_..."
```

### Pre-built agent skill


---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.x |
| Frontend | Django templates, HTMX, Alpine.js |
| CSS | Tailwind CSS 4 via django-tailwind |
| Database | PostgreSQL 16+ |
| Background jobs | django-background-tasks (no Redis required) |
| Auth | django-allauth (email + Google OAuth) |
| Media | Pillow (images), FFmpeg (video) |
| Deployment | Docker, Gunicorn, Caddy |

---

## Troubleshooting

**Docker: `postgres` container is unhealthy**
Wait 10-15 seconds after `docker compose up` for the health check to pass, then retry your command. Check logs with `docker compose logs postgres`.

**`python manage.py migrate` fails with connection errors**
Make sure PostgreSQL is running and healthy. For Docker: `docker compose ps` should show postgres as "healthy". For local: verify the `DATABASE_URL` in `.env` matches your setup.

**Tailwind CSS changes not appearing**
Make sure the Tailwind watcher is running: `cd theme/static_src && npm run start`. If styles still don't update, try `npm run build` for a full rebuild.

**OAuth callback errors ("redirect URI mismatch")**
The redirect URI registered on the platform must exactly match `{APP_URL}/social-accounts/callback/{platform}/`. Check that `APP_URL` in `.env` matches the URL you're accessing (including `http` vs `https` and port number).

**Threads: "No app ID was provided in the request" (error `4476002`)**
Threads uses its own App ID, not the Facebook one. Set `PLATFORM_THREADS_APP_ID` / `PLATFORM_THREADS_APP_SECRET` from **Use cases → Access the Threads API → Settings**, and register `{APP_URL}/social-accounts/callback/threads/` in that same panel — the Facebook Login redirect URI list does not cover Threads. See the [Meta](#meta-facebook-instagram-threads) section.

**Background tasks not running (posts not publishing)**
Make sure the worker is running: `python manage.py run_worker`. In Docker: check `docker compose logs worker`.

**A post is stuck on "Publishing"**
It shouldn't stay there. `confirm_pending_publishes` runs every 60s and settles anything in that status: asynchronous publishes (TikTok accepts the upload, then transcodes) are confirmed against the platform and marked published or failed with the platform's own reason, and a post whose worker died mid-publish is failed after `PUBLISHER_STALE_PUBLISHING_TIMEOUT` so it becomes editable and retryable again. It is never re-published automatically - we can't tell "the platform never saw it" from "the platform took it and we crashed before recording that", and a duplicate video on a live account can't be undone. A third case is kept distinct on purpose: when the platform accepted the upload but we can't reach it to ask what happened, the sweep keeps reconciling for `PUBLISHER_UNCONFIRMED_TIMEOUT` (6h by default) and, if it never learns the answer, fails the post with copy that tells the user to **check the account before republishing** rather than to try again - the post may already be live. If posts sit on "Publishing" for longer than that, the worker isn't running (see above) or is being killed repeatedly - check its memory.

**Uploaded images 404 in production (and Instagram/Facebook/Pinterest posts fail)**
With `STORAGE_BACKEND=local`, `/media/` must be publicly reachable. Check that `SERVE_MEDIA` is not set to `false` unless your reverse proxy serves `MEDIA_ROOT` at that same path, and that `MEDIA_ROOT` is on a persistent volume. Those platforms fetch attachment URLs server-side, so a 404 there fails the publish, not just the thumbnail.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding guidelines, and how to submit pull requests.

## Security

To report a security vulnerability, see [SECURITY.md](SECURITY.md). Do not open a public issue.

## License

[AGPL-3.0](LICENSE) - see LICENSE for details.
