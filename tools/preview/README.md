# Static preview

`build_static_preview.mjs` builds a clickable, read-only copy of SM Bean's screens for the Netlify
site **smbean-preview**, while the real app is set up elsewhere. It holds demo data only and saves
nothing: every page is the HTML the e2e server rendered, frozen.

## What it builds

Against a running e2e server (`python -m tests.e2e.server`, which uses the faked team and mocked
providers, so nothing reaches a real service), the script:

1. adds demo data to the seeded workspace A ("Neopolis") through the harness's own fixtures
   (`publishing_review_post`, `publishing_scheduled_post`, `unread_notification`) and through Home's
   own thread: one request taken through Go ahead to a draft waiting for approval, one left at its
   brief card. A second run against the same server finds the data and adds nothing;
2. signs in as the seeded owner with the `session` fixture and crawls same-origin GET links
   breadth-first from Home, Approvals, the Calendar (month, week, day and each list tab), Inbox,
   Analytics, Activity, every Settings tab, Set up, the composer, Ideas, Drafts, Media, the posting
   schedule, members, notifications and the account page; then, signed out, the public pages and the
   login page;
3. skips `/admin`, `/__e2e__/`, `/api/`, MCP, OAuth and Google sign-in, the client portal, webhooks,
   logout, anything that deletes, disconnects, exports or downloads, any path that ends in an action
   (`approve/`, `publish/`, `send/`, ...) and any answer that is not `200 text/html`;
4. saves each page's server HTML at `<out>/<path>/index.html`. A query that changes the page
   (`?mode=`, `?view=`, `?tab=`) gets a path of its own (`calendar/?mode=list&tab=drafts` is
   `calendar/list-drafts/`) and the links to it are rewritten; other queries stay on links as they
   are. A link the server redirects (`/` for someone signed in, `analytics/`) points at its target;
5. saves the fragments those pages load through `hx-get` (polls, tabs, the notifications drawer, the
   list tabs' URLs in the page's script) at their own paths, or under `/_fragments/` when a page owns
   that path, and points the `hx-get` there. A link that HTMX would load in place becomes a plain link;
6. collects the static files (`manage.py collectstatic --noinput` with the e2e settings, into a
   temporary `STATIC_ROOT` under the gitignored `e2e_media/`) into `<out>/static/`, and copies the
   pictures the pages show;
7. puts a fixed 32 px bar at the top of every page ("Preview with demo data. Nothing you do here is
   saved.") and gives the body, the app shell and the public header room for it; the phone bar, the
   drawer and dialogs are not covered;
8. replaces every CSRF token with `preview`, drops script nonces, makes links to the e2e origin
   root-relative, and fails the build if the output still holds a session or CSRF cookie value, an
   e2e credential, a local absolute path or an email address other than the seeded fictional ones
   (`@e2e.test`) and `example.com` placeholders;
9. writes `_headers` (`X-Robots-Tag: noindex, nofollow`), `robots.txt` (`Disallow: /`),
   `netlify.toml` (`publish = "."`, no build command), `404.html`, `index.html` (the public Home,
   signed out) and `preview.json` (the source SHA, the build time and the pages).

## Commands

From a worktree checked out at the commit to preview, with its CSS built and its root lock
installed (Playwright 1.56 and its Chromium):

```bash
git worktree add ../smbean-preview-src <sha>
cd ../smbean-preview-src
(cd theme/static_src && npm ci && npm run build)
npm ci --ignore-scripts

# Terminal 1: the e2e server with its worker, on its own port and database
DB_NAME=smbean_preview_e2e ../calander-9-/.venv/bin/python -m tests.e2e.server --reset --port 8401

# Terminal 2, in the same worktree (the script itself can live in any checkout)
DB_NAME=smbean_preview_e2e node ../calander-9-/tools/preview/build_static_preview.mjs \
  --base-url http://127.0.0.1:8401 --out /tmp/smbean-preview/site \
  --sha "$(git rev-parse HEAD)" --app-dir . --python ../calander-9-/.venv/bin/python

# Look at it before deploying, then stop both servers
(cd /tmp/smbean-preview/site && python3 -m http.server 8402)
```

`--out` must be a new or empty folder, or an earlier preview (it is replaced). `--max-pages`
(500) and `--max-fragments` (400) bound the crawl; `--no-demo-data` crawls what the server holds.
It takes about a minute and writes about 70 pages and 17 MB.

Deploy the folder as it is to the Netlify site `smbean-preview` (nothing builds on Netlify), for
example `netlify deploy --prod --dir /tmp/smbean-preview/site --site smbean-preview`.

## What does not work in the preview

Anything that saves: forms, Approve, Go ahead, the thread's Send, drag and drop on the calendar
(a POST meets Netlify's 404 page or an error). Filters and date arrows that build their URL in
script show the saved period or list. Polls return the moment the preview was built. The unread
count's JSON poll answers 404 and the bell keeps its count. The client portal, Google sign-in and
the Agent API are not included.

The output is demo data from the e2e harness. Never commit it.
